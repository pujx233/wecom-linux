"""Verify foreign-process cursor pixels using one pinned runtime on a private Xvfb."""
import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--wine', type=Path, required=True, help='complete Wine runtime directory')
parser.add_argument('--manifest', type=Path, required=True, help='JSON containing runtime_sha256')
parser.add_argument('--exe', type=Path, required=True, help='compiled foreign-cursor-test.c')
parser.add_argument('--out', type=Path, required=True, help='new disposable result directory')
parser.add_argument('--xvfb', default='Xvfb', help='Xvfb executable')
args = parser.parse_args()
runtime, exe, out = args.wine.resolve(), args.exe.resolve(), args.out.resolve()
assert not out.is_relative_to(runtime), 'QA output must be outside the runtime'
out.mkdir(parents=True, exist_ok=False)
components = {'wineserver': runtime / 'bin/wineserver', 'wine': runtime / 'bin/wine'}
for module in ('winex11.so', 'win32u.so', 'ntdll.so'):
    components[module] = runtime / 'lib/wine/x86_64-unix' / module
inputs = components | {'fixture': exe, 'runner': Path(__file__).resolve(),
                       'fixture_source': Path(__file__).with_name('foreign-cursor-test.c')}
report = {'passed': False, 'host_desktop_used': False, 'account_data_used': False, 'stages': [],
          'runtime_path': str(runtime), 'fixture_path': str(exe), 'manifest_path': str(args.manifest.resolve())}
env = os.environ.copy()
for name in tuple(env):
    if name.startswith('WINE') or name in ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'LD_PRELOAD',
                                          'LD_LIBRARY_PATH', 'DBUS_SESSION_BUS_ADDRESS'):
        env.pop(name)
for directory in ('runtime', 'config', 'data', 'cache'):
    (out / directory).mkdir(mode=0o700)
env.update(XDG_RUNTIME_DIR=str(out / 'runtime'), XDG_CONFIG_HOME=str(out / 'config'),
           XDG_DATA_HOME=str(out / 'data'), XDG_CACHE_HOME=str(out / 'cache'), LC_ALL='C',
           WINEPREFIX=str(out / 'prefix'), WINESERVER=str(components['wineserver']), WINEDEBUG='-all,+cursor',
           WINEDLLOVERRIDES='winewayland.drv=d;mscoree,mshtml,winemenubuilder=', XMODIFIERS='@im=none')
log = (out / 'cursor.log').open('wb')
app = xvfb = display = None
wine_started = False


class Cursor(C.Structure):
    _fields_ = [('x', C.c_short), ('y', C.c_short), ('width', C.c_ushort), ('height', C.c_ushort),
                ('xhot', C.c_ushort), ('yhot', C.c_ushort), ('serial', C.c_ulong),
                ('pixels', C.POINTER(C.c_ulong)), ('atom', C.c_ulong), ('name', C.c_char_p)]


class Attributes(C.Structure):
    _fields_ = [(name, C.c_int) for name in ('x', 'y', 'width', 'height', 'border_width', 'depth')]
    _fields_ += [('visual', C.c_void_p), ('root', C.c_ulong)]
    _fields_ += [(name, C.c_int) for name in ('window_class', 'bit_gravity', 'win_gravity', 'backing_store')]
    _fields_ += [('backing_planes', C.c_ulong), ('backing_pixel', C.c_ulong), ('save_under', C.c_int),
                ('colormap', C.c_ulong), ('map_installed', C.c_int), ('map_state', C.c_int),
                ('all_event_masks', C.c_long), ('your_event_mask', C.c_long),
                ('do_not_propagate_mask', C.c_long), ('override_redirect', C.c_int), ('screen', C.c_void_p)]


def fingerprint():
    pointer = fixes.XFixesGetCursorImage(display)
    assert pointer, 'XFixes returned no cursor image'
    try:
        cursor = pointer.contents
        assert cursor.width and cursor.height and cursor.pixels, 'XFixes returned an empty cursor'
        pixels = b''.join((int(pixel) & 0xffffffff).to_bytes(4, 'little')
                          for pixel in cursor.pixels[:cursor.width * cursor.height])
        return {'position': [cursor.x, cursor.y], 'size': [cursor.width, cursor.height],
                'hotspot': [cursor.xhot, cursor.yhot], 'name': cursor.name.decode() if cursor.name else None,
                'pixels_sha256': hashlib.sha256(pixels).hexdigest()}
    finally:
        x.XFree(pointer)


try:
    before = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in inputs.items()}
    report['sha256_before'] = before
    manifest = json.loads(args.manifest.read_text())['runtime_sha256']
    for name in ('wineserver', 'winex11.so', 'win32u.so', 'ntdll.so'):
        assert before[name] == manifest[name], f'runtime manifest mismatch: {name}'
    report['manifest_verified'] = True
    read_fd, write_fd = os.pipe()
    try:
        xvfb = subprocess.Popen([args.xvfb, '-displayfd', str(write_fd), '-screen', '0', '800x600x24',
                                 '-nolisten', 'tcp', '-ac'], pass_fds=(write_fd,), stdout=log, stderr=log, env=env)
    finally:
        os.close(write_fd)
    with os.fdopen(read_fd) as pipe, selectors.DefaultSelector() as ready:
        ready.register(pipe, selectors.EVENT_READ)
        assert ready.select(10), 'Xvfb did not become ready'
        number = pipe.readline().strip()
        assert number.isdecimal(), 'Xvfb did not allocate a private display'
    env['DISPLAY'] = ':' + number
    report['display'] = env['DISPLAY']
    x, fixes, cursors = C.CDLL('libX11.so.6'), C.CDLL('libXfixes.so.3'), C.CDLL('libXcursor.so.1')
    x.XOpenDisplay.argtypes, x.XOpenDisplay.restype = [C.c_char_p], C.c_void_p
    x.XDefaultRootWindow.argtypes, x.XDefaultRootWindow.restype = [C.c_void_p], C.c_ulong
    x.XWarpPointer.argtypes = [C.c_void_p, C.c_ulong, C.c_ulong, C.c_int, C.c_int,
                              C.c_uint, C.c_uint, C.c_int, C.c_int]
    x.XDefineCursor.argtypes = [C.c_void_p, C.c_ulong, C.c_ulong]
    x.XFreeCursor.argtypes = [C.c_void_p, C.c_ulong]
    x.XGetWindowAttributes.argtypes = [C.c_void_p, C.c_ulong, C.POINTER(Attributes)]
    x.XSync.argtypes = [C.c_void_p, C.c_int]
    x.XFree.argtypes = [C.c_void_p]
    x.XCloseDisplay.argtypes = [C.c_void_p]
    fixes.XFixesGetCursorImage.argtypes = [C.c_void_p]
    fixes.XFixesGetCursorImage.restype = C.POINTER(Cursor)
    cursors.XcursorLibraryLoadCursor.argtypes = [C.c_void_p, C.c_char_p]
    cursors.XcursorLibraryLoadCursor.restype = C.c_ulong
    display = x.XOpenDisplay(env['DISPLAY'].encode())
    assert display
    root = x.XDefaultRootWindow(display)
    x.XWarpPointer(display, 0, root, 0, 0, 0, 0, 700, 500)
    expected = {}
    # Obtain independent host pixels for the three standard cursor roles, before Wine starts.
    for label, names in (('parent', ('left_ptr',)), ('text', ('xterm', 'text')),
                         ('link', ('hand2', 'pointer', 'pointing-hand'))):
        cursor = 0
        for name in names:
            cursor = cursors.XcursorLibraryLoadCursor(display, name.encode())
            if cursor:
                break
        assert cursor, f'host cursor theme lacks {label}'
        x.XDefineCursor(display, root, cursor)
        x.XFreeCursor(display, cursor)
        x.XSync(display, False)
        expected[label] = fingerprint()
    assert len({value['pixels_sha256'] for value in expected.values()}) == 3, 'cursor references are not distinct'
    report['expected'] = expected
    wine_started = True
    subprocess.run([str(components['wine']), 'wineboot.exe', '-u'], env=env, stdout=log, stderr=log,
                   check=True, timeout=60)
    app = subprocess.Popen([str(components['wine']), str(exe)], env=env,
                           stdout=subprocess.PIPE, stderr=log, text=True)
    with selectors.DefaultSelector() as ready:
        ready.register(app.stdout, selectors.EVENT_READ)
        assert ready.select(15), 'cursor fixture did not start'
        window = json.loads(app.stdout.readline())
    report['window'] = window
    assert window['xid'], 'fixture has no X window'
    attributes = Attributes()
    deadline = time.monotonic() + 3
    while True:
        assert app.poll() is None, 'fixture exited before mapping'
        assert x.XGetWindowAttributes(display, window['xid'], C.byref(attributes))
        if attributes.map_state == 2:
            break
        assert time.monotonic() < deadline, 'fixture did not become viewable'
        time.sleep(.01)
    for label, px, py in [('parent', 350, 250), ('text', 60, 60), ('link', 160, 60),
                          ('parent', 350, 250), ('text', 60, 60), ('link', 160, 60)]:
        x.XWarpPointer(display, 0, root, 0, 0, 0, 0, px, py)
        x.XSync(display, False)
        start, matched_since = time.monotonic(), None
        while True:
            assert app.poll() is None, 'fixture exited while sampling'
            actual = fingerprint()
            now = time.monotonic()
            matches = actual['position'] == [px, py] and all(
                actual[key] == expected[label][key] for key in ('size', 'hotspot', 'pixels_sha256'))
            matched_since = (matched_since or now) if matches else None
            passed = matched_since is not None and now - matched_since >= .05
            if passed or now - start >= 2:
                break
            time.sleep(.01)
        report['stages'].append(actual | {'region': label, 'passed': passed,
                                          'elapsed_ms': round((now - start) * 1000, 2)})
    report['passed'] = all(stage['passed'] for stage in report['stages'])
except Exception as error:
    report['error'] = f'{type(error).__name__}: {error}'
finally:
    cleanup_errors = []
    if wine_started:
        for option in ('-k', '-w'):
            try:
                result = subprocess.run([str(components['wineserver']), option], env=env,
                                        stdout=log, stderr=log, timeout=10)
                # -k also returns 1 when no server is running; -w still confirms it stopped.
                if result.returncode not in ((0, 1) if option == '-k' else (0,)):
                    raise subprocess.CalledProcessError(result.returncode, result.args)
            except (OSError, subprocess.SubprocessError) as error:
                cleanup_errors.append(f'wineserver {option}: {type(error).__name__}: {error}')
    if display:
        try:
            x.XCloseDisplay(display)
        except (OSError, C.ArgumentError) as error:
            cleanup_errors.append(f'X display: {type(error).__name__}: {error}')
    for label, process in (('fixture', app), ('Xvfb', xvfb)):
        if process is None:
            continue
        try:
            if process is xvfb:
                process.terminate()
            process.wait(timeout=5)
        except (OSError, subprocess.SubprocessError) as error:
            cleanup_errors.append(f'{label}: {type(error).__name__}: {error}')
            try:
                process.kill()
                process.wait(timeout=5)
            except (OSError, subprocess.SubprocessError) as error:
                cleanup_errors.append(f'{label} kill: {type(error).__name__}: {error}')
    try:
        log.close()
    except OSError as error:
        cleanup_errors.append(f'log: {type(error).__name__}: {error}')
    try:
        report['sha256_after'] = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in inputs.items()}
    except OSError as error:
        cleanup_errors.append(f'fingerprint: {type(error).__name__}: {error}')
    report['cleanup_errors'] = cleanup_errors
    report['inputs_unchanged'] = bool(report.get('sha256_before')) and (
        report.get('sha256_before') == report.get('sha256_after'))
    report['passed'] = report['passed'] and report['inputs_unchanged'] and not cleanup_errors
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
raise SystemExit(0 if report['passed'] else 1)
