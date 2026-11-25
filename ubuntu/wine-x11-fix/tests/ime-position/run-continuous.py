#!/usr/bin/env python3
"""Type consecutive words through real private IBus and check the foreign editor's IMM results."""
import argparse
from contextlib import contextmanager
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import queue
import select
import signal
import shutil
import subprocess
import sys
import threading
import time
from gi.repository import Gio, GLib

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'frame-composition'))
from isolated import desktop, link_runtime_libraries, processes


@contextmanager
def keyboard_input(qa, env):
    metadata = json.loads((qa / 'desktop.json').read_text())
    assert env['DISPLAY'] == metadata['display'] and env['XDG_RUNTIME_DIR'] == metadata['runtime']
    assert env['DBUS_SESSION_BUS_ADDRESS'] == metadata['bus']
    assert Path(f"/proc/{metadata['xwayland_pid']}/stat").read_text().split()[21] == metadata['xwayland_start']
    connection = Gio.DBusConnection.new_for_address_sync(
        metadata['bus'], Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT |
        Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
    service = 'org.gnome.Mutter.RemoteDesktop'
    try:
        session = connection.call_sync(service, '/org/gnome/Mutter/RemoteDesktop', service, 'CreateSession',
                                       None, None, Gio.DBusCallFlags.NONE, 5000, None).unpack()[0]

        def call(method, parameters=None):
            return connection.call_sync(service, session, service + '.Session', method, parameters,
                                        None, Gio.DBusCallFlags.NONE, 5000, None)

        call('Start')
        try:
            def send_key(value, pressed):
                call('NotifyKeyboardKeysym', GLib.Variant('(ub)', (value, pressed)))

            yield send_key
        finally:
            call('Stop')
    finally:
        connection.close_sync(None)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime', type=Path, required=True)
parser.add_argument('--driver', type=Path)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--bits', choices=('32', '64'), default='64')
parser.add_argument('--expect-failure', action='store_true')
parser.add_argument('--gnome-restarts', action='store_true', help='Use the stock one-shot GNOME XIM frontend')
parser.add_argument('--xim-helper', type=Path, help='Candidate helper for --gnome-restarts; defaults to the package')
parser.add_argument('--trace', action='store_true')
args = parser.parse_args()
qa = args.output.resolve()
qa.mkdir(parents=True, exist_ok=False)
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
exe = qa / 'ime-process.exe'
subprocess.run([compiler, '-O2', '-Wall', '-Wextra', str(HERE / 'ime-process.c'), '-o', str(exe),
                '-limm32', '-luser32'], check=True)
report = {'bits': args.bits, 'events': [], 'account_data_used': False, 'host_desktop_used': False,
          'input_transport': 'org.gnome.Mutter.RemoteDesktop.Session.NotifyKeyboardKeysym',
          'virtual_keyboard_created_before_application': True,
          'driver_sha256': hashlib.sha256(driver.read_bytes()).hexdigest()}
lines = queue.Queue()
app = ibus = frontend = engine = None

def wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try: value = lines.get(timeout=max(.01, deadline - time.monotonic()))
        except queue.Empty: break
        if value is None: raise RuntimeError('Wine fixture exited')
        report['events'].append(value)
        if predicate(value): return value
    raise TimeoutError('Expected editor response did not arrive')


try:
    with desktop(qa, size='1600x1000', bare=True, keyboard=True) as env, keyboard_input(qa, env) as send_key:
        env.update(WINEPREFIX=str(qa / 'prefix'), WINESERVER=str(overlay / 'bin/wineserver'), WINEDEBUG='-all,+xim',
                   XMODIFIERS='@im=ibus', LANG='zh_CN.UTF-8', LC_CTYPE='zh_CN.UTF-8', WECOM_IME_FIXTURE='1',
                   WINEDLLOVERRIDES='winewayland.drv=d;mscoree,mshtml,winemenubuilder=',
                   IBUS_ADDRESS='unix:abstract=wecom-continuous-' + str(os.getpid()))
        if args.gnome_restarts:
            # Stock GNOME lets ibus-daemon publish a new address each time.
            env.pop('IBUS_ADDRESS')
            env.pop('IBUS_ADDRESS_FILE', None)
        if args.trace: env['WINEDEBUG'] = '-all,+xim,+imm,+timestamp,+pid'
        x = C.CDLL('libX11.so.6')
        x.XOpenDisplay.argtypes = [C.c_char_p]; x.XOpenDisplay.restype = C.c_void_p
        x.XInternAtom.argtypes = [C.c_void_p, C.c_char_p, C.c_int]; x.XInternAtom.restype = C.c_ulong
        x.XGetSelectionOwner.argtypes = [C.c_void_p, C.c_ulong]; x.XGetSelectionOwner.restype = C.c_ulong
        x.XCloseDisplay.argtypes = [C.c_void_p]
        old_auth = os.environ.get('XAUTHORITY')
        os.environ['XAUTHORITY'] = env['XAUTHORITY']
        display = x.XOpenDisplay(env['DISPLAY'].encode())
        if old_auth is None: os.environ.pop('XAUTHORITY', None)
        else: os.environ['XAUTHORITY'] = old_auth
        assert display
        with (qa / 'ibus.log').open('w') as bus_log, (qa / 'wine.log').open('w') as wine_log:
            def start_daemon():
                command = ['ibus-daemon', '--single', '--emoji-extension=disable', '--cache=none']
                if not args.gnome_restarts:
                    command.extend(['--xim', '--address=' + env['IBUS_ADDRESS']])
                return subprocess.Popen(command, env=env, stdout=bus_log, stderr=bus_log)

            def wait_owner(atom, present=True):
                deadline = time.monotonic() + 10
                while bool(owner := x.XGetSelectionOwner(display, atom)) != present:
                    assert time.monotonic() < deadline, f'XIM selection {atom}, expected present={present}'
                    time.sleep(.025)
                return owner

            default = x.XInternAtom(display, b'@server=ibus', False)
            private = x.XInternAtom(display, b'@server=wecom-ibus-0', False)
            ibus = start_daemon()
            command = [str(overlay / 'bin/wine'), str(exe), str(exe)]
            if args.gnome_restarts:
                subprocess.run(['gdbus', 'wait', '--session', '--timeout=8', 'org.freedesktop.IBus'],
                               env=env, check=True)
                frontend = subprocess.Popen(['/usr/libexec/ibus-x11'], env=env | {'GDK_BACKEND': 'x11'},
                                            stdout=bus_log, stderr=bus_log)
                if not args.expect_failure:
                    helper = args.xim_helper or runtime.parent / 'template/wecom-compat/scripts/ibus-xim.py'
                    command = ['/usr/bin/python3', str(helper), *command]
            default_owner = wait_owner(default)
            app = subprocess.Popen(command, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=wine_log, text=True, bufsize=1)
            if args.gnome_restarts and not args.expect_failure:
                assert wait_owner(private) != default_owner
                assert x.XGetSelectionOwner(display, default) == default_owner

            def read_lines():
                for line in app.stdout:
                    if line.startswith('{'): lines.put(json.loads(line))
                lines.put(None)

            threading.Thread(target=read_lines, daemon=True).start()
            report['ready'] = wait_for(lambda v: v['event'] == 'ready')
            def type_words(repetitions):
                for character in 'ceshi wenjian zhongwen ' * repetitions:
                    send_key(ord(character), True)
                    send_key(ord(character), False)
                    time.sleep(.008)
                time.sleep(.8)
                app.stdin.write('state\n')
                app.stdin.flush()
                report['state'] = wait_for(lambda event: event['event'] == 'posted')
                return [n for event in report['events'] for n in event.get('result', [])]

            passes = []
            word = list(map(ord, '测试文件中文'))
            for generation in range(3 if args.gnome_restarts else 1):
                if generation:
                    ibus.terminate()
                    ibus.wait(timeout=8)
                    wait_owner(default, False)
                    if not args.expect_failure:
                        wait_owner(private, False)
                    ibus = start_daemon()
                    subprocess.run(['gdbus', 'wait', '--session', '--timeout=8', 'org.freedesktop.IBus'],
                                   env=env, check=True)
                    if not args.expect_failure:
                        wait_owner(private)
                    assert not x.XGetSelectionOwner(display, default)
                engine = subprocess.Popen([sys.executable, '-u', str(HERE / 'word-engine.py')], env=env,
                                          stdout=subprocess.PIPE, stderr=bus_log, text=True)
                assert select.select([engine.stdout], [], [], 10)[0] and engine.stdout.readline().strip() == 'ready'
                time.sleep(.3)
                passes.append(type_words(1 if args.gnome_restarts else 4))
                if args.gnome_restarts and not args.expect_failure and generation == 0:
                    children = [pid for pid, argv in processes(qa) if argv == [
                        b'/usr/libexec/ibus-x11', b'--server-name', b'wecom-ibus-0']]
                    assert len(children) == 1
                    os.kill(children[0], signal.SIGKILL)
                    wait_owner(private, False)
                    wait_owner(private)
                    assert x.XGetSelectionOwner(display, default) == default_owner
                    passes.append(type_words(1))
                engine.terminate()
                engine.wait(timeout=6)
            report['native_owner_state'] = next(v for v in reversed(report['events']) if v['event'] == 'root-state')
            if args.gnome_restarts:
                expected = [word, word, word] if args.expect_failure else [word * n for n in (1, 2, 3, 4)]
                success = passes == expected
                report.update(real_daemon_restarts=2, phases=passes, checked_app_frontend_exit=not args.expect_failure)
            else:
                expected = [word * 4]
                success = passes == expected and report['native_owner_state']['open'] == 1
                if args.expect_failure:
                    success = not success
            report.update(actual=passes[-1], expected=expected[-1], input_interval_ms=8,
                          negative_control_reproduced=success and args.expect_failure, passed=success)
            app.stdin.write('quit\n')
            app.stdin.flush()
            app.wait(timeout=10)
            assert app.returncode == 0
            if args.gnome_restarts and not args.expect_failure:
                wait_owner(private, False)
        x.XCloseDisplay(display)
except Exception as error:
    report.update(error=str(error), passed=False)
finally:
    for process in (engine, app, frontend, ibus):
        if process is not None and process.poll() is None:
            process.terminate(); process.wait(timeout=8)
    (qa / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({k: report.get(k) for k in ('passed', 'error', 'actual', 'expected', 'state')}))
sys.exit(0 if report['passed'] else 1)
