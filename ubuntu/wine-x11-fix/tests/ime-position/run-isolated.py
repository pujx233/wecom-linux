#!/usr/bin/env python3
"""Coordinates only: disposable Wine + private Mutter/Xwayland + private IBus."""
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
from gi.repository import Gio, GLib

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent / 'frame-composition'
sys.path.insert(0, str(TOOLS))
from isolated import desktop

parser = argparse.ArgumentParser()
parser.add_argument('--runtime', type=Path, required=True)
parser.add_argument('--driver', type=Path)
parser.add_argument('--core', type=Path)
parser.add_argument('--name', default='ime-' + str(time.time_ns()))
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--dpi', type=int, choices=(96, 192), default=192)
parser.add_argument('--awareness', choices=('pm', 'system', 'unaware'), default='pm')
parser.add_argument('--frame', choices=('0', '1'), default='1')
parser.add_argument('--preedit', choices=('callbacks', 'position'), default='callbacks')
parser.add_argument('--trace', action='store_true')
parser.add_argument('--mixed-scale', action='store_true')
parser.add_argument('--candidate', action='store_true', help='Also check explicit candidate and exclusion anchors')
parser.add_argument('--bits', choices=('32', '64'), default='64')
args = parser.parse_args()
assert args.name and all(c.isalnum() or c in '-_' for c in args.name)
output = args.output.resolve()
marker = output / '.wecom-ime-tests'
if output.exists() and any(output.iterdir()):
    assert marker.is_file(), 'Use an empty output directory or a marked IME test directory'
output.mkdir(parents=True, exist_ok=True)
marker.touch()
assert not (output / f'{args.name}.json').exists(), 'Use a new report name to preserve previous evidence'
qa = output / args.name
qa.mkdir()
compiler = 'i686-w64-mingw32-gcc' if args.bits == '32' else 'x86_64-w64-mingw32-gcc'
executable = qa / f'ime-position{args.bits}.exe'
subprocess.run([compiler, '-mwindows', '-O2', '-Wall', '-Wextra', str(HERE / 'ime-position.c'),
                '-o', str(executable), '-limm32', '-luser32', '-lshcore'], check=True)
(qa / '.wecom-frame-qa').touch()
os.environ['WECOM_QA_ROOT'] = str(qa)
runtime = args.runtime.resolve()
assert (runtime / 'bin/wine').is_file()
# Each report gets its selected runtime and a fresh prefix, including when reusing output.
# Read-only symlinks for immutable PE libraries; independent loader and test modules.
overlay = qa / 'wine'
(overlay / 'lib/wine/x86_64-unix').mkdir(parents=True)
shutil.copytree(runtime / 'bin', overlay / 'bin', symlinks=True)
for name in ('share', 'include'):
    if (runtime / name).exists(): (overlay / name).symlink_to(runtime / name, target_is_directory=True)
for name in ('i386-windows', 'x86_64-windows'):
    (overlay / 'lib/wine' / name).symlink_to(runtime / 'lib/wine' / name, target_is_directory=True)
for path in (runtime / 'lib/wine/x86_64-unix').iterdir():
    target = overlay / 'lib/wine/x86_64-unix' / path.name
    if path.name in ('wine', 'wine-preloader', 'ntdll.so'):
        shutil.copy2(path, target)
    else:
        target.symlink_to(path.resolve(), target_is_directory=path.is_dir())
for name, source in (('ntdll.so', None), ('winex11.so', args.driver), ('win32u.so', args.core)):
    source = (source or runtime / 'lib/wine/x86_64-unix' / name).resolve()
    target = overlay / 'lib/wine/x86_64-unix' / name
    temp = target.with_suffix('.fixture-new')
    shutil.copy2(source, temp)
    temp.replace(target)
report = {'account_data_used': False, 'host_desktop_used': False, 'arguments': vars(args).copy(), 'cases': []}
report['boot_id'] = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
report['arguments'] = {k: str(v) if isinstance(v, Path) else v for k, v in report['arguments'].items()}
report['core_sha256'] = hashlib.sha256((overlay / 'lib/wine/x86_64-unix/win32u.so').read_bytes()).hexdigest()
report['driver_sha256'] = hashlib.sha256((overlay / 'lib/wine/x86_64-unix/winex11.so').read_bytes()).hexdigest()
pe_arch = 'i386-windows' if args.bits == '32' else 'x86_64-windows'
report['imm32_sha256_by_arch'] = {
    arch: hashlib.sha256((runtime / 'lib/wine' / arch / 'imm32.dll').read_bytes()).hexdigest()
    for arch in ('i386-windows', 'x86_64-windows')}
report['imm32_sha256'] = report['imm32_sha256_by_arch'][pe_arch]
report['wineserver_sha256'] = hashlib.sha256((overlay / 'bin/wineserver').read_bytes()).hexdigest()
report['test_sha256'] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in (HERE / 'ime-position.c', Path(__file__), executable)}

with desktop(qa, size='3200x2000', bare=True,
             second_monitor='3840x2160' if args.mixed_scale else None) as env:
    if args.mixed_scale:
        assert env['DISPLAY'] != ':0'
        assert env['DBUS_SESSION_BUS_ADDRESS'] != os.environ['DBUS_SESSION_BUS_ADDRESS']
        connection = Gio.DBusConnection.new_for_address_sync(
            env['DBUS_SESSION_BUS_ADDRESS'], Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT |
            Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
        def display_call(method, params=None):
            return connection.call_sync('org.gnome.Mutter.DisplayConfig', '/org/gnome/Mutter/DisplayConfig',
                                        'org.gnome.Mutter.DisplayConfig', method, params, None,
                                        Gio.DBusCallFlags.NONE, 5000, None).unpack()
        try:
            state = display_call('GetCurrentState')
            monitors = sorted(state[1], key=lambda monitor: monitor[0][0])
            assert len(monitors) == 2
            configurations = []
            for index, monitor in enumerate(monitors):
                mode = next(mode for mode in monitor[1] if mode[6].get('is-current'))
                scale = float(index + 1)
                assert scale in mode[5]
                configurations.append((0 if not index else 3200, 0, scale, 0, not index,
                                       [(monitor[0][0], mode[0], {})]))
            display_call('ApplyMonitorsConfig', GLib.Variant('(uua(iiduba(ssa{sv}))a{sv})',
                         (state[0], 1, configurations, {})))
            time.sleep(.5)
            report['private_displays'] = display_call('GetCurrentState')[2]
            assert sorted(monitor[2] for monitor in report['private_displays']) == [1.0, 2.0]
        finally:
            connection.close_sync(None)
    env.update(WINEPREFIX=str(qa / 'prefix'), WINESERVER=str(overlay / 'bin/wineserver'), WINEDEBUG='-all,+xim',
               XMODIFIERS='@im=ibus', WINE_X11_OWNED_FRAME=args.frame, WECOM_IME_FIXTURE='1',
               LANG='zh_CN.UTF-8', LC_CTYPE='zh_CN.UTF-8',
               WINEDLLOVERRIDES='winewayland.drv=d;mscoree,mshtml,winemenubuilder=')
    env.pop('WECOM_IME_COORD_TRACE', None)
    if args.trace: env['WECOM_IME_COORD_TRACE'] = '1'
    env['IBUS_ADDRESS'] = 'unix:abstract=wecom-ime-' + str(os.getpid())
    x = C.CDLL('libX11.so.6')
    x.XOpenDisplay.argtypes = [C.c_char_p]; x.XOpenDisplay.restype = C.c_void_p
    x.XInternAtom.argtypes = [C.c_void_p, C.c_char_p, C.c_int]; x.XInternAtom.restype = C.c_ulong
    x.XGetSelectionOwner.argtypes = [C.c_void_p, C.c_ulong]; x.XGetSelectionOwner.restype = C.c_ulong
    x.XCloseDisplay.argtypes = [C.c_void_p]
    x.XDefaultRootWindow.argtypes = [C.c_void_p]; x.XDefaultRootWindow.restype = C.c_ulong
    x.XTranslateCoordinates.argtypes = [C.c_void_p, C.c_ulong, C.c_ulong, C.c_int, C.c_int,
                                       C.POINTER(C.c_int), C.POINTER(C.c_int), C.POINTER(C.c_ulong)]
    x.XGetGeometry.argtypes = [C.c_void_p, C.c_ulong, C.POINTER(C.c_ulong), C.POINTER(C.c_int),
                              C.POINTER(C.c_int), C.POINTER(C.c_uint), C.POINTER(C.c_uint),
                              C.POINTER(C.c_uint), C.POINTER(C.c_uint)]
    old_auth = os.environ.get('XAUTHORITY')
    os.environ['XAUTHORITY'] = env['XAUTHORITY']
    display = x.XOpenDisplay(env['DISPLAY'].encode())
    if old_auth is None: os.environ.pop('XAUTHORITY')
    else: os.environ['XAUTHORITY'] = old_auth
    assert display
    assert env['DISPLAY'] != ':0'
    with ((output / f'{args.name}-ibus.log').open('w') as ibus_log,
          (output / f'{args.name}-wine.log').open('w') as wine_log):
        ibus = subprocess.Popen(['ibus-daemon', '--xim', '--single', '--emoji-extension=disable', '--cache=none',
                                 '--address=' + env['IBUS_ADDRESS']], env=env, stdout=ibus_log, stderr=ibus_log)
        app = monitor = None
        try:
            selection = x.XInternAtom(display, b'@server=ibus', False)
            deadline = time.monotonic() + 12
            while not x.XGetSelectionOwner(display, selection):
                assert ibus.poll() is None, 'private IBus exited'
                assert time.monotonic() < deadline, 'private XIM did not become ready'
                time.sleep(.05)
            subprocess.run([str(overlay / 'bin/wine'), 'reg.exe', 'add', 'HKCU\\Control Panel\\Desktop',
                            '/v', 'LogPixels', '/t', 'REG_DWORD', '/d', str(args.dpi), '/f'],
                           env=env, stdout=wine_log, stderr=wine_log, check=True, timeout=10)
            subprocess.run([str(overlay / 'bin/wine'), 'reg.exe', 'add', 'HKCU\\Software\\Wine\\X11 Driver',
                            '/v', 'InputStyle', '/d',
                            'OverTheSpot' if args.preedit == 'position' else 'OnTheSpot', '/f'],
                           env=env, stdout=wine_log, stderr=wine_log, check=True, timeout=10)
            subprocess.run([str(overlay / 'bin/wineserver'), '-k'], env=env, check=True, timeout=10)
            subprocess.run([str(overlay / 'bin/wineserver'), '-w'], env=env, check=True, timeout=10)
            monitor = subprocess.Popen(['dbus-monitor', '--address', env['IBUS_ADDRESS'],
                "type='method_call',interface='org.freedesktop.IBus.InputContext',member='SetCursorLocation'"],
                env=env, stdout=subprocess.PIPE, stderr=ibus_log, text=True, bufsize=1)
            coordinates = []
            def read_bus():
                header = None
                values = []
                for line in monitor.stdout:
                    line = line.strip()
                    if line.startswith('method call') and 'member=SetCursorLocation' in line:
                        header = line
                        values = []
                    elif header and line.startswith('int32 '):
                        values.append(int(line.split()[1]))
                        if len(values) == 4:
                            coordinates.append({'time': time.monotonic(), 'rect': values[:], 'header': header})
                            header = None
            threading.Thread(target=read_bus, daemon=True).start()
            time.sleep(.2)
            command = [str(overlay / 'bin/wine'), str(executable), args.awareness]
            app = subprocess.Popen(command, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=wine_log, text=True, bufsize=1)
            lines = queue.Queue()
            def read_app():
                for line in app.stdout:
                    lines.put(json.loads(line))
            threading.Thread(target=read_app, daemon=True).start()
            ready = lines.get(timeout=20)
            assert ready['event'] == 'ready', ready
            report['ready'] = ready
            report['launcher_process'] = app.pid
            styles = re.findall(r'selected style (0x[0-9a-f]+)',
                                (output / f'{args.name}-wine.log').read_text())
            assert styles, 'No selected XIM style was recorded'
            report['xim_styles'] = sorted({int(style, 16) for style in styles})
            preedit_bit = 4 if args.preedit == 'position' else 2
            assert all(style & preedit_bit for style in report['xim_styles']), report['xim_styles']
            report['active_modules'] = []
            report['imm32_modules'] = []
            report['application_processes'] = []
            marker = b'WINEPREFIX=' + os.fsencode(qa / 'prefix')
            for process in Path('/proc').glob('[0-9]*'):
                try:
                    if marker not in (process / 'environ').read_bytes().split(b'\0'):
                        continue
                    maps = (process / 'maps').read_text().splitlines()
                    if any(line.endswith(' ' + str(executable)) for line in maps):
                        report['application_processes'].append(int(process.name))
                    report['active_modules'].extend(
                        {'pid': int(process.name), 'mapping': line} for line in maps if 'r-xp' in line and
                        any(module in line for module in ('winex11.so', 'win32u.so')))
                    report['imm32_modules'].extend(
                        {'pid': int(process.name), 'mapping': line,
                         'sha256': hashlib.sha256(Path(line.split()[-1]).read_bytes()).hexdigest()}
                        for line in maps if 'r-xp' in line and line.endswith('/imm32.dll'))
                except (FileNotFoundError, PermissionError, ProcessLookupError):
                    continue
            names = {entry['mapping'].split()[-1] for entry in report['active_modules']}
            assert names == {str(overlay / 'lib/wine/x86_64-unix' / name)
                             for name in ('winex11.so', 'win32u.so')}, names
            assert report['imm32_modules'], 'No mapped IMM32 implementation found'
            assert all(module['sha256'] in report['imm32_sha256_by_arch'].values()
                       for module in report['imm32_modules'])
            assert len(report['application_processes']) == 1, report['application_processes']
            fixture_pid = report['application_processes'][0]
            assert any(module['pid'] == fixture_pid and module['sha256'] == report['imm32_sha256']
                       for module in report['imm32_modules']), 'Fixture loaded a different IMM32 architecture or build'
            time.sleep(.3)
            steps = [('caret', 30, 40), ('caret', 130, 40), ('caret', 30, 80),
                     ('composition', 80, 110), ('maximize', 0, 0), ('restore', 0, 0),
                     ('move', 800, 300), ('composition', 210, 200), ('caret', 30, 240),
                     ('composition', 30, 240),
                     ('tall', 70, 280), ('composition', 70, 280), ('area', 70, 280),
                     ('small-area', 70, 280), ('force', 70, 280), ('maximize', 0, 0), ('restore', 0, 0),
                     ('move', 500, 200), ('composition', 180, 300), ('stale', 70, 280),
                     ('blur', 70, 280), ('destroy', 70, 280), ('force', 70, 280)]
            if args.mixed_scale:
                steps.extend([('screen', 1, 0), ('composition', 80, 120), ('caret', 80, 120),
                              ('composition', 80, 120), ('screen', 0, 0), ('composition', 80, 120)])
            if args.candidate:
                steps.extend([('caret', 120, 160), ('composition', 120, 160), ('candidate', 120, 160),
                              ('force', 120, 160), ('exclude', 120, 160),
                              ('move', 600, 240), ('candidate', 180, 200)])
            anchor_uses_bottom = False
            caret_point = None
            for command, xvalue, yvalue in steps:
                start = len(coordinates)
                app.stdin.write(f'{command} {xvalue} {yvalue}\n'); app.stdin.flush()
                result = lines.get(timeout=8)
                time.sleep(.25)
                if command == 'stale':
                    assert result['caret'] == result['hwnd'] and result['focus'] != result['hwnd'], result
                if command in ('caret', 'tall'):
                    caret_point = (xvalue, yvalue)
                    anchor_uses_bottom = args.preedit == 'callbacks'
                elif command == 'exclude':
                    anchor_uses_bottom = True
                elif command in ('composition', 'force'):
                    anchor_uses_bottom = args.preedit == 'callbacks' and caret_point == (xvalue, yvalue)
                elif command in ('blur', 'destroy', 'stale'):
                    caret_point = None
                    anchor_uses_bottom = False
                elif command in ('area', 'small-area', 'candidate'):
                    anchor_uses_bottom = False
                expected = result['lower_physical'] if anchor_uses_bottom else result['physical']
                native_x, native_y, native_child = C.c_int(), C.c_int(), C.c_ulong()
                native_root, local_x, local_y = C.c_ulong(), C.c_int(), C.c_int()
                width, height, border, depth = C.c_uint(), C.c_uint(), C.c_uint(), C.c_uint()
                assert x.XTranslateCoordinates(display, result['xid'], x.XDefaultRootWindow(display), 0, 0,
                                               C.byref(native_x), C.byref(native_y), C.byref(native_child))
                assert x.XGetGeometry(display, result['xid'], C.byref(native_root), C.byref(local_x),
                                      C.byref(local_y), C.byref(width), C.byref(height),
                                      C.byref(border), C.byref(depth))
                native_size = [width.value, height.value]
                assert all(dpi > 0 for dpi in result['root_raw_dpi']), result
                native_client_size = [(size * result['root_dpi'] + dpi // 2) // dpi
                                      for size, dpi in zip(native_size, result['root_raw_dpi'])]
                anchor_origin = result['root_anchor_origin']
                native_expected = [native_x.value + expected[0] - anchor_origin[0],
                                   native_y.value + expected[1] - anchor_origin[1]]
                updates = coordinates[start:]
                actual = updates[-1]['rect'][:2] if updates else None
                report['cases'].append({'command': command, 'point': [xvalue, yvalue], 'application': result,
                                        'ibus_updates': updates, 'expected': native_expected, 'actual': actual,
                                        'win32_expected': expected,
                                        'native_origin': [native_x.value, native_y.value],
                                        'native_size': native_size,
                                        'native_client_size': native_client_size,
                                        'passed': result['ok'] == 1 and actual == native_expected and
                                                  native_client_size == result['root_client_size']})
                assert native_client_size == result['root_client_size'], report['cases'][-1]
            app.stdin.write('quit\n'); app.stdin.flush()
            app.wait(timeout=10)
            report['all_ibus_updates'] = coordinates
            report['application_exit'] = app.returncode
            report['coordinate_collection_completed'] = app.returncode == 0
            report['passed'] = app.returncode == 0 and all(case['passed'] for case in report['cases'])
        finally:
            if app is not None and app.poll() is None:
                app.terminate(); app.wait(timeout=5)
            if monitor is not None:
                monitor.terminate(); monitor.wait(timeout=5)
            ibus.terminate(); ibus.wait(timeout=5)
            x.XCloseDisplay(display)
            (output / f'{args.name}.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'report': str(output / f'{args.name}.json'), 'cases': len(report['cases']),
                  'passed': report.get('passed', False)}))

if not report.get('passed'):
    sys.exit(1)
