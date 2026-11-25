#!/usr/bin/env python3
"""Restart real private IBus while Wine GUI threads survive, exit, and are recreated."""
import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'frame-composition'))
from isolated import desktop, link_runtime_libraries

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime', type=Path, required=True)
parser.add_argument('--driver', type=Path)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--bits', choices=('32', '64'), default='64')
parser.add_argument('--rounds', type=int, default=6)
parser.add_argument('--expect-cross-thread', action='store_true')
parser.add_argument('--disable-xim', action='store_true')
parser.add_argument('--one-shot-frontend', action='store_true',
                    help='Model GNOME Wayland starting ibus-x11 separately, once per Xwayland session')
args = parser.parse_args()
assert 1 <= args.rounds <= 100
qa = args.output.resolve()
qa.mkdir(parents=True)
(qa / '.wecom-frame-qa').touch()
os.environ['WECOM_QA_ROOT'] = str(qa)
runtime = args.runtime.resolve()
driver = (args.driver or runtime / 'lib/wine/x86_64-unix/winex11.so').resolve()
overlay = qa / 'wine'
(overlay / 'lib/wine/x86_64-unix').mkdir(parents=True)
link_runtime_libraries(runtime, overlay)
shutil.copytree(runtime / 'bin', overlay / 'bin', symlinks=True)
for name in ('share', 'include'):
    if (runtime / name).exists(): (overlay / name).symlink_to(runtime / name, target_is_directory=True)
for name in ('i386-windows', 'x86_64-windows'):
    (overlay / 'lib/wine' / name).symlink_to(runtime / 'lib/wine' / name, target_is_directory=True)
for path in (runtime / 'lib/wine/x86_64-unix').iterdir():
    dest = overlay / 'lib/wine/x86_64-unix' / path.name
    if path.name in ('wine', 'wine-preloader', 'ntdll.so'): shutil.copy2(path, dest)
    else: dest.symlink_to(path.resolve(), target_is_directory=path.is_dir())
(overlay / 'lib/wine/x86_64-unix/winex11.so').unlink()
shutil.copy2(driver, overlay / 'lib/wine/x86_64-unix/winex11.so')
compiler = 'i686-w64-mingw32-gcc' if args.bits == '32' else 'x86_64-w64-mingw32-gcc'
exe, probe = qa / 'ime-reconnect.exe', qa / 'xim-display-owner.so'
subprocess.run([compiler, '-O2', '-Wall', '-Wextra', str(HERE / 'ime-reconnect.c'), '-o', str(exe),
                '-luser32'], check=True)
subprocess.run(['gcc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', str(HERE / 'xim-display-owner.c'),
                '-o', str(probe), '-ldl', '-lX11'], check=True)
report = {'bits': args.bits, 'rounds': [], 'account_data_used': False, 'host_desktop_used': False,
          'driver_sha256': hashlib.sha256(driver.read_bytes()).hexdigest(),
          'expect_cross_thread': args.expect_cross_thread, 'disable_xim': args.disable_xim,
          'frontend': 'one-shot Xwayland session hook' if args.one_shot_frontend else 'ibus-daemon --xim'}
app = ibus = frontend = None
lines = queue.Queue()
try:
    with desktop(qa, size='1600x1000', bare=True) as env:
        env.update(WINEPREFIX=str(qa / 'prefix'), WINESERVER=str(overlay / 'bin/wineserver'), WINEDEBUG='-all,+xim',
                   XMODIFIERS='@im=ibus', LANG='zh_CN.UTF-8', LC_CTYPE='zh_CN.UTF-8',
                   WINEDLLOVERRIDES='winewayland.drv=d;mscoree,mshtml,winemenubuilder=',
                   IBUS_ADDRESS='unix:abstract=wecom-reconnect-' + str(os.getpid()))
        x = C.CDLL('libX11.so.6')
        x.XOpenDisplay.argtypes = [C.c_char_p]; x.XOpenDisplay.restype = C.c_void_p
        x.XInternAtom.argtypes = [C.c_void_p, C.c_char_p, C.c_int]; x.XInternAtom.restype = C.c_ulong
        x.XGetSelectionOwner.argtypes = [C.c_void_p, C.c_ulong]; x.XGetSelectionOwner.restype = C.c_ulong
        x.XCloseDisplay.argtypes = [C.c_void_p]
        old_auth = os.environ.get('XAUTHORITY')
        os.environ['XAUTHORITY'] = env['XAUTHORITY']
        display = x.XOpenDisplay(env['DISPLAY'].encode())
        if old_auth is None: os.environ.pop('XAUTHORITY')
        else: os.environ['XAUTHORITY'] = old_auth
        assert display
        selection = x.XInternAtom(display, b'@server=ibus', False)

        def wait_owner(present):
            deadline = time.monotonic() + 12
            while bool(owner := x.XGetSelectionOwner(display, selection)) != present:
                if time.monotonic() > deadline: raise TimeoutError('XIM selection did not change')
                time.sleep(.03)
            return owner

        with (qa / 'ibus.log').open('w') as bus_log, (qa / 'wine.log').open('w') as wine_log:
            def start_bus():
                process = subprocess.Popen(['ibus-daemon', *([] if args.one_shot_frontend else ['--xim']),
                                            '--single', '--emoji-extension=disable',
                                            '--cache=none', '--address=' + env['IBUS_ADDRESS']],
                                           env=env, stdout=bus_log, stderr=bus_log)
                if args.one_shot_frontend:
                    subprocess.run(['gdbus', 'wait', '--session', '--timeout=10', 'org.freedesktop.IBus'],
                                   env=env, stdout=bus_log, stderr=bus_log, check=True, timeout=12)
                else:
                    wait_owner(True)
                return process

            def start_frontend():
                path = shutil.which('ibus-x11') or '/usr/libexec/ibus-x11'
                process = subprocess.Popen([path], env=env | {'GDK_BACKEND': 'x11'},
                                           stdout=bus_log, stderr=bus_log)
                wait_owner(True)
                return process

            def response():
                value = lines.get(timeout=15)
                if value is None: raise RuntimeError('Wine fixture exited before its response')
                return value

            def command(text):
                app.stdin.write(text + '\n'); app.stdin.flush()
                return response()

            if args.disable_xim:
                subprocess.run([str(overlay / 'bin/wine'), 'reg.exe', 'add',
                                'HKCU\\Software\\Wine\\X11 Driver', '/v', 'UseXIM', '/d', 'N', '/f'],
                               env=env, stdout=wine_log, stderr=wine_log, check=True, timeout=15)
            ibus = start_bus()
            if args.one_shot_frontend:
                frontend = start_frontend()
            app = subprocess.Popen([str(overlay / 'bin/wine'), str(exe)],
                                   env=env | {'LD_PRELOAD': str(probe),
                                              'WECOM_XIM_OWNER_LOG': str(qa / 'owners.jsonl')},
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=wine_log, text=True, bufsize=1)

            def read_lines():
                for line in app.stdout:
                    if line.startswith('{'): lines.put(json.loads(line))
                lines.put(None)

            threading.Thread(target=read_lines, daemon=True).start()
            report['ready'] = response()
            for cycle in range(args.rounds):
                ibus.terminate(); ibus.wait(timeout=8); ibus = None
                wait_owner(False)
                dropped = command('drop')
                spawned = command('spawn')
                if args.one_shot_frontend:
                    frontend.wait(timeout=8)
                ibus = start_bus()
                state = {}
                if args.one_shot_frontend:
                    # The restarted daemon is reachable. Check ownership before the positive
                    # control supplies the frontend that a one-shot session hook cannot restart.
                    state['automatic_xim_owner'] = x.XGetSelectionOwner(display, selection)
                    assert not state['automatic_xim_owner'] and ibus.poll() is None, state
                    frontend = start_frontend()
                    state['supplied_xim_owner'] = x.XGetSelectionOwner(display, selection)
                time.sleep(.5)
                alive = command('ping')
                report['rounds'].append({'cycle': cycle, 'drop': dropped, 'spawn': spawned, 'alive': alive, **state})
            app.stdin.write('quit\n'); app.stdin.flush(); app.wait(timeout=15)
            report['application_exit'] = app.returncode
        x.XCloseDisplay(display)
except Exception as error:
    report['error'] = str(error)
finally:
    report['application_exit_before_cleanup'] = app.poll() if app is not None else None
    report['cleanup_terminated_application'] = app is not None and app.poll() is None
    for process in (app, frontend, ibus):
        if process is not None and process.poll() is None:
            process.terminate(); process.wait(timeout=8)
    owners, violations, opens = {}, [], 0
    path = qa / 'owners.jsonl'
    for line in path.read_text().splitlines() if path.exists() else []:
        item = json.loads(line)
        key = item['pid'], item['display']
        if item['event'] == 'display': owners[key] = item['tid']
        else:
            opens += 1
            if owners.get(key) != item['tid']:
                violations.append(item | {'display_owner_tid': owners.get(key)})
    report.update(open_im_calls=opens, cross_thread_calls=violations)
    report['passed'] = bool(violations) if args.expect_cross_thread else (
        'error' not in report and report.get('application_exit') == 0 and len(report['rounds']) == args.rounds and
        (opens == 0 if args.disable_xim else opens >= 12 * (args.rounds + 1)) and not violations)
    (qa / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'output': str(qa), 'passed': report['passed'], 'open_im_calls': opens,
                  'cross_thread_calls': len(violations), 'error': report.get('error')}))
sys.exit(0 if report['passed'] else 1)
