#!/usr/bin/env python3
"""Private two-process IMM delivery, native XIM anchor, and buffered-event regression."""
import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'frame-composition'))
from isolated import desktop

parser = argparse.ArgumentParser()
parser.add_argument('--runtime', type=Path, required=True)
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--core', type=Path)
parser.add_argument('--driver', type=Path)
parser.add_argument('--imm32-i386', type=Path)
parser.add_argument('--imm32-x64', type=Path)
parser.add_argument('--parent-bits', choices=('32', '64'), default='64')
parser.add_argument('--child-bits', choices=('32', '64'), default='64')
parser.add_argument('--expect-missing', action='store_true')
parser.add_argument('--wake-driver', action='store_true')
parser.add_argument('--rounds', type=int, default=12)
parser.add_argument('--queue-probe', action='store_true')
parser.add_argument('--expect-queue-stall', action='store_true')
parser.add_argument('--diagnose', action='store_true')
parser.add_argument('--trace', action='store_true')
args = parser.parse_args()
qa = args.output.resolve()
qa.mkdir(parents=True)
(qa / '.wecom-frame-qa').touch()
os.environ['WECOM_QA_ROOT'] = str(qa)
runtime = args.runtime.resolve()
args.core = (args.core or runtime / 'lib/wine/x86_64-unix/win32u.so').resolve()
args.driver = (args.driver or runtime / 'lib/wine/x86_64-unix/winex11.so').resolve()
header = (args.source / 'include/ntuser.h').read_text()
internal = header.split('enum wine_internal_message')[1].split('};')[0]
assert internal.split('WM_WINE_IME_UPDATE')[0].count('WM_WINE_') == 16, 'Update the fixture message code'
assert 'NtUserImeDriverCall       = 0x0305' in header
assert 'WINE_IME_TO_ASCII_EX,\n    WINE_IME_POST_UPDATE' in header
overlay = qa / 'wine'
(overlay / 'lib/wine/x86_64-unix').mkdir(parents=True)
shutil.copytree(runtime / 'bin', overlay / 'bin', symlinks=True)
for name in ('share', 'include'):
    if (runtime / name).exists(): (overlay / name).symlink_to(runtime / name, target_is_directory=True)
for arch in ('i386-windows', 'x86_64-windows'):
    selected = args.imm32_i386 if arch == 'i386-windows' else args.imm32_x64
    directory = overlay / 'lib/wine' / arch
    if selected:
        directory.mkdir()
        for module in (runtime / 'lib/wine' / arch).iterdir():
            (directory / module.name).symlink_to(module.resolve(), target_is_directory=module.is_dir())
        (directory / 'imm32.dll').unlink()
        shutil.copy2(selected, directory / 'imm32.dll')
    else:
        directory.symlink_to(runtime / 'lib/wine' / arch, target_is_directory=True)
for source in (runtime / 'lib/wine/x86_64-unix').iterdir():
    target = overlay / 'lib/wine/x86_64-unix' / source.name
    if source.name in ('wine', 'wine-preloader', 'ntdll.so'): shutil.copy2(source, target)
    else: target.symlink_to(source.resolve(), target_is_directory=source.is_dir())
for name, source in (('win32u.so', args.core), ('winex11.so', args.driver)):
    target = overlay / 'lib/wine/x86_64-unix' / name
    target.unlink()
    shutil.copy2(source, target)
for bits, compiler in (('32', 'i686-w64-mingw32-gcc'), ('64', 'x86_64-w64-mingw32-gcc')):
    subprocess.run([compiler, '-mwindows', '-O2', '-Wall', '-Wextra', str(ROOT / 'ime-position/ime-process.c'),
                    '-o', str(qa / ('ime-process' + bits + '.exe')), '-limm32', '-luser32'], check=True)
subprocess.run(['gcc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra',
                str(ROOT / 'ime-position/ime-process-driver.c'), '-o', str(qa / 'ime-process-driver.so'),
                '-ldl', '-lX11'], check=True)
report = {'arguments': {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
          'events': [], 'cursor_locations': [], 'host_desktop_used': False, 'account_data_used': False,
          'components': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (args.core, args.driver)}}
report['imm32_sha256'] = {
    arch: hashlib.sha256((overlay / 'lib/wine' / arch / 'imm32.dll').read_bytes()).hexdigest()
    for arch in ('i386-windows', 'x86_64-windows')}
events = queue.Queue()
app = ibus = monitor = None
try:
    with desktop(qa, size='3200x2000', bare=True) as env:
        env.update(WINEPREFIX=str(qa / 'prefix'), WINESERVER=str(overlay / 'bin/wineserver'),
                   WINEDEBUG='-all,+imm,+xim' if args.trace else '-all',
                   WECOM_IME_FIXTURE='1', WINE_X11_OWNED_FRAME='1',
                   XMODIFIERS='@im=ibus', LANG='en_US.UTF-8', LC_CTYPE='en_US.UTF-8',
                   IBUS_ADDRESS='unix:abstract=ime-process-' + str(os.getpid()),
                   WINEDLLOVERRIDES='winewayland.drv=d;mscoree,mshtml,winemenubuilder=')
        log = (qa / 'wine.log').open('w')
        buslog = (qa / 'ibus.log').open('w')
        ibus = subprocess.Popen(['ibus-daemon', '--xim', '--single', '--emoji-extension=disable', '--cache=none',
                                 '--address=' + env['IBUS_ADDRESS']], env=env, stdout=buslog, stderr=buslog)
        subprocess.run([str(overlay / 'bin/wine'), 'reg.exe', 'add', 'HKCU\\Control Panel\\Desktop',
                        '/v', 'LogPixels', '/t', 'REG_DWORD', '/d', '192', '/f'], env=env, stdout=log,
                       stderr=log, check=True, timeout=20)
        subprocess.run([str(overlay / 'bin/wine'), 'reg.exe', 'add', 'HKCU\\Software\\Wine\\X11 Driver',
                        '/v', 'InputStyle', '/d', 'OnTheSpot', '/f'], env=env, stdout=log,
                       stderr=log, check=True, timeout=10)
        subprocess.run([str(overlay / 'bin/wineserver'), '-k'], env=env, check=True, timeout=10)
        subprocess.run([str(overlay / 'bin/wineserver'), '-w'], env=env, check=True, timeout=10)
        monitor = subprocess.Popen(['dbus-monitor', '--address', env['IBUS_ADDRESS'],
            "type='method_call',interface='org.freedesktop.IBus.InputContext',member='SetCursorLocation'"],
            env=env, stdout=subprocess.PIPE, stderr=buslog, text=True, bufsize=1)
        def read_bus():
            values = None
            for line in monitor.stdout:
                if line.startswith('method call') and 'SetCursorLocation' in line: values = []
                elif values is not None and line.strip().startswith('int32 '):
                    values.append(int(line.split()[1]))
                    if len(values) == 4:
                        report['cursor_locations'].append(values)
                        values = None
        threading.Thread(target=read_bus, daemon=True).start()
        app = subprocess.Popen([str(overlay / 'bin/wine'), str(qa / ('ime-process' + args.parent_bits + '.exe')),
                                 'Z:' + str(qa / ('ime-process' + args.child_bits + '.exe'))],
                                env=env | {'LD_PRELOAD': str(qa / 'ime-process-driver.so'),
                                           'WECOM_WIN32U_PATH': str(overlay / 'lib/wine/x86_64-unix/win32u.so')},
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=log, text=True, bufsize=1)
        def read_events():
            for line in app.stdout:
                try: value = json.loads(line)
                except ValueError: value = {'event': 'bad-output', 'line': line}
                events.put(value)
        threading.Thread(target=read_events, daemon=True).start()
        def wait_for(predicate, timeout=8):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try: value = events.get(timeout=max(.001, deadline - time.monotonic()))
                except queue.Empty: break
                report['events'].append(value)
                if predicate(value): return value
            marker = b'WINEPREFIX=' + os.fsencode(qa / 'prefix')
            for proc in Path('/proc').glob('[0-9]*') if args.diagnose else ():
                try:
                    if marker not in (proc / 'environ').read_bytes().split(b'\0'): continue
                    mapped = (proc / 'maps').read_text().splitlines()
                    if not any('ime-process' in line and '.exe' in line for line in mapped):
                        continue
                    with (qa / ('timeout-stack-' + proc.name + '.log')).open('w') as stack:
                        subprocess.run(['gdb', '-nx', '--batch', '-p', proc.name, '-ex', 'set pagination off',
                                        '-ex', 'thread apply all bt 12'], env=os.environ | {'DEBUGINFOD_URLS': ''},
                                       stdout=stack, stderr=subprocess.STDOUT, timeout=8)
                except (OSError, subprocess.TimeoutExpired): pass
            raise AssertionError('Expected event missing: ' + json.dumps(report['events'][-8:]))
        ready = wait_for(lambda v: v['event'] == 'ready', 25)
        assert ready['focus'] == ready['hwnd'], ready
        report['ready'] = ready
        report['application_modules'] = []
        marker = b'WINEPREFIX=' + os.fsencode(qa / 'prefix')
        for proc in Path('/proc').glob('[0-9]*'):
            try:
                if marker not in (proc / 'environ').read_bytes().split(b'\0'): continue
                mapped = (proc / 'maps').read_text().splitlines()
                if not any('ime-process' in line and '.exe' in line for line in mapped): continue
                modules = {Path(line.split()[-1]).name: line.split()[-1] for line in mapped
                           if 'r-xp' in line and line.split()[-1].endswith(('/win32u.so', '/winex11.so'))}
                expected = {name: str(overlay / 'lib/wine/x86_64-unix' / name) for name in report['components']}
                assert modules == expected, modules
                role = 'child' if re.search(rb'(?:^|[ \0"])child(?:[ \0"]|$)',
                                           (proc / 'cmdline').read_bytes()) else 'parent'
                imm32 = [line.split()[-1] for line in mapped if line.split()[2] == '00000000' and
                         line.endswith('/imm32.dll')]
                assert len(imm32) == 1, imm32
                digest = hashlib.sha256(Path(imm32[0]).read_bytes()).hexdigest()
                assert digest in report['imm32_sha256'].values(), imm32
                report['application_modules'].append({'pid': int(proc.name), 'role': role,
                                                       'modules': modules, 'imm32_sha256': digest})
            except (FileNotFoundError, PermissionError, ProcessLookupError): pass
        assert len(report['application_modules']) == 2, report['application_modules']
        class KeyEvent(C.Structure):
            _fields_ = [('type', C.c_int), ('serial', C.c_ulong), ('send_event', C.c_int),
                        ('display', C.c_void_p), ('window', C.c_ulong), ('root', C.c_ulong),
                        ('subwindow', C.c_ulong), ('time', C.c_ulong), ('x', C.c_int), ('y', C.c_int),
                        ('x_root', C.c_int), ('y_root', C.c_int), ('state', C.c_uint),
                        ('keycode', C.c_uint), ('same_screen', C.c_int)]
        class Event(C.Union):
            _fields_ = [('key', KeyEvent), ('pad', C.c_long * 24)]
        x11 = C.CDLL('libX11.so.6')
        x11.XOpenDisplay.argtypes = [C.c_char_p]; x11.XOpenDisplay.restype = C.c_void_p
        x11.XInternAtom.argtypes = [C.c_void_p, C.c_char_p, C.c_int]; x11.XInternAtom.restype = C.c_ulong
        x11.XSendEvent.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.c_long, C.POINTER(Event)]
        x11.XFlush.argtypes = [C.c_void_p]; x11.XCloseDisplay.argtypes = [C.c_void_p]
        old_auth = os.environ.get('XAUTHORITY')
        os.environ['XAUTHORITY'] = env['XAUTHORITY']
        display = x11.XOpenDisplay(env['DISPLAY'].encode())
        if old_auth is None: os.environ.pop('XAUTHORITY', None)
        else: os.environ['XAUTHORITY'] = old_auth
        assert display
        def command(value):
            operations = {'preedit': 1, 'result': 2, 'empty': 3, 'end': 4, 'probe': 9}
            if value in operations:
                event = Event()
                event.key.type = 2
                event.key.display = display
                event.key.window = ready['xid']
                event.key.root = ready['root']
                event.key.time = operations[value]
                event.key.keycode = 255
                event.key.same_screen = True
                assert x11.XSendEvent(display, ready['xid'], False, 1, C.byref(event))
                x11.XFlush(display)
                if args.wake_driver:
                    app.stdin.write('state\n'); app.stdin.flush()
                wait_for(lambda v: v['event'] == 'driver' and v['operation'] ==
                         operations[value])
                return
            app.stdin.write(value + '\n'); app.stdin.flush()
        if args.queue_probe:
            command('probe')
            try:
                wait_for(lambda v: v['event'] == 'driver' and v['operation'] == 10, 2)
            except AssertionError:
                if not args.expect_queue_stall: raise
                report['queue_stall_reproduced'] = True
            else:
                assert not args.expect_queue_stall, 'Expected old driver to leave the buffered event pending'
                report['buffered_events_passed'] = True
        command('preedit')
        if args.expect_missing:
            try:
                wait_for(lambda v: v['event'] == 'composition' and v['child'] == 1, 1)
            except AssertionError:
                report['negative_control_reproduced'] = True
            else: raise AssertionError('Old components unexpectedly delivered foreign composition')
        else:
            if not any(v.get('comp') == [97, 0xd83d, 0xde42] and v.get('child') == 1 for v in report['events']):
                wait_for(lambda v: v.get('comp') == [97, 0xd83d, 0xde42] and v.get('child') == 1)
            command('result')
            wait_for(lambda v: v.get('result') == [0x6d4b, 0x8bd5] and v.get('child') == 1)
            for index in range(args.rounds):
                command('preedit')
                wait_for(lambda v: v.get('comp') == [97, 0xd83d, 0xde42] and v.get('child') == 1)
                command('result')
                wait_for(lambda v: v.get('result') == [0x6d4b, 0x8bd5] and v.get('child') == 1)
            command('end')
            command('preedit')
            wait_for(lambda v: v.get('comp') == [97, 0xd83d, 0xde42] and v.get('child') == 1)
            command('empty')
            wait_for(lambda v: v.get('comp') == [] and v.get('child') == 1)
            wait_for(lambda v: v['event'] == 'end' and v['child'] == 1)
            command('end')
            deadline = time.monotonic() + 3
            while not report['cursor_locations'] and time.monotonic() < deadline: time.sleep(.02)
            assert ready['physical'] in [v[:2] for v in report['cursor_locations']], report['cursor_locations']
            assert not any(v.get('child') == 0 and v['event'] == 'composition' for v in report['events'])
            report['composition_and_position_passed'] = True
            command('root')
            focused = wait_for(lambda v: v['event'] == 'root-focus')
            assert focused['focus'] == focused['hwnd']
            start = len(report['events'])
            command('stale')
            wait_for(lambda v: v['event'] == 'fence')
            assert not any(v['event'] == 'composition' for v in report['events'][start:])
            command('preedit')
            wait_for(lambda v: v.get('comp') == [97, 0xd83d, 0xde42] and v.get('child') == 0)
            command('result')
            wait_for(lambda v: v.get('result') == [0x6d4b, 0x8bd5] and v.get('child') == 0)
            command('focus')
            wait_for(lambda v: v['event'] == 'child-focus')
            start = len(report['events'])
            command('invalid')
            wait_for(lambda v: v['event'] == 'fence')
            assert not any(v['event'] == 'composition' for v in report['events'][start:])
            command('preedit')
            wait_for(lambda v: v.get('comp') == [97, 0xd83d, 0xde42] and v.get('child') == 1)
            command('result')
            wait_for(lambda v: v.get('result') == [0x6d4b, 0x8bd5] and v.get('child') == 1)
            report['focus_lifecycle_and_invalid_packet_passed'] = True
            parent_pid = next(p['pid'] for p in report['application_modules'] if p['role'] == 'parent')
            wait_for(lambda v: v['event'] == 'end' and v.get('child') == 1)
            for operation, number in [('complete', 1), ('cancel', 4)]:
                start = len(report['events'])
                command(operation)
                wait_for(lambda v: v['event'] == 'notify' and v['operation'] == number)
                assert not any(v['event'] == 'native-reset' for v in report['events'][start:])
            report['empty_context_does_not_reset_native_passed'] = True
            for operation, number in [('complete', 1), ('cancel', 4)]:
                command('preedit')
                wait_for(lambda v: v.get('comp') == [97, 0xd83d, 0xde42] and v.get('child') == 1)
                start = len(report['events'])
                command(operation)
                done = wait_for(lambda v: v['event'] == 'notify' and v['operation'] == number)
                assert done['ok'] == 1
                response = report['events'][start:]
                resets = [v for v in response if v['event'] == 'native-reset']
                assert len(resets) == 1 and resets[0]['native_pid'] == parent_pid, response
                results = [v['result'] for v in response if 'result' in v]
                assert results == ([[97, 0xd83d, 0xde42]] if operation == 'complete' else []), response
            report['native_complete_cancel_passed'] = True
        command('quit')
        app.wait(timeout=10)
        assert app.returncode == 0
        x11.XCloseDisplay(display)
        report['passed'] = True
finally:
    for process in (app, monitor, ibus):
        if process is not None and process.poll() is None:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
    (qa / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'report': str(qa / 'result.json'), 'passed': report.get('passed', False)}))
