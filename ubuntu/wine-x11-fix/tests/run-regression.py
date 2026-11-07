#!/usr/bin/env python3
"""Check popup geometry, alpha and input regions on a private Xvfb/Openbox desktop."""
import argparse
import ctypes as C
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime', required=True, type=Path)
parser.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
runtime, root = args.runtime.resolve(strict=True), args.output.resolve()
root.mkdir(parents=True, exist_ok=False)
driver = runtime / 'lib/wine/x86_64-unix/winex11.so'
prefix, logs = root / 'prefix', root
subprocess.run(['i686-w64-mingw32-gcc', '-O2', '-Wall', '-Wextra',
                str(Path(__file__).with_name('window-regression.c')),
                '-o', str(root / 'window-regression.exe'), '-lgdi32', '-luser32'], check=True)
env = os.environ.copy()
env.update(WINEPREFIX=str(prefix), WINEDEBUG='-all',
           WINEDLLOVERRIDES='mscoree,mshtml,winemenubuilder=',
           WINESERVER=str(runtime / 'bin/wineserver'), XDG_CONFIG_HOME=str(logs / 'config'),
           XDG_CACHE_HOME=str(logs / 'cache'), XMODIFIERS='@im=none',
           DBUS_SYSTEM_BUS_ADDRESS='unix:path=' + str(root / 'no-system-bus'))
for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'WINEDLLPATH', 'LD_PRELOAD', 'DBUS_SESSION_BUS_ADDRESS'):
    env.pop(key, None)
processes = []
files = []
completed = False
report = {'started_at': datetime.now(timezone.utc).isoformat(),
          'driver_sha256': hashlib.sha256(driver.read_bytes()).hexdigest(),
          'test_exe_sha256': hashlib.sha256((root / 'window-regression.exe').read_bytes()).hexdigest(),
          'test_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'host_desktop_used': False, 'account_data_used': False, 'stages': [], 'checks': []}


class Rect(C.Structure):
    _fields_ = [('x', C.c_short), ('y', C.c_short), ('width', C.c_ushort), ('height', C.c_ushort)]


class Attributes(C.Structure):
    _fields_ = [(n, C.c_int) for n in ('x', 'y', 'width', 'height', 'border_width', 'depth')]
    _fields_ += [('visual', C.c_void_p), ('root', C.c_ulong)]
    _fields_ += [(n, C.c_int) for n in ('window_class', 'bit_gravity', 'win_gravity', 'backing_store')]
    _fields_ += [('backing_planes', C.c_ulong), ('backing_pixel', C.c_ulong), ('save_under', C.c_int),
                ('colormap', C.c_ulong), ('map_installed', C.c_int), ('map_state', C.c_int),
                ('all_event_masks', C.c_long), ('your_event_mask', C.c_long),
                ('do_not_propagate_mask', C.c_long), ('override_redirect', C.c_int), ('screen', C.c_void_p)]


class XImage(C.Structure):
    _fields_ = [(n, C.c_int) for n in ('width', 'height', 'xoffset', 'format')]
    _fields_ += [('data', C.c_void_p)]
    _fields_ += [(n, C.c_int) for n in ('byte_order', 'bitmap_unit', 'bitmap_bit_order', 'bitmap_pad',
                                     'depth', 'bytes_per_line', 'bits_per_pixel')]


def start(args, name):
    stream = (logs / (name + '.log')).open('wb')
    files.append(stream)
    process = subprocess.Popen(args, env=env, stdout=stream, stderr=subprocess.STDOUT)
    processes.append(process)
    return process


def check(name, passed):
    report['checks'].append({'name': name, 'passed': bool(passed)})


def mask(xid, kind, width, height):
    count, order = C.c_int(), C.c_int()
    rects = shape.XShapeGetRectangles(display, xid, kind, C.byref(count), C.byref(order))
    pixels = bytearray(width * height)
    for i in range(count.value):
        r = rects[i]
        for y in range(max(0, r.y), min(height, r.y + r.height)):
            left, right = max(0, r.x), min(width, r.x + r.width)
            pixels[y * width + left:y * width + right] = b'\1' * max(0, right - left)
    x.XFree(rects)
    return pixels


try:
    read_fd, write_fd = os.pipe()
    stream = (logs / 'xvfb.log').open('wb')
    files.append(stream)
    try:
        xvfb = subprocess.Popen(['Xvfb', '-displayfd', str(write_fd), '-screen', '0', '1600x1000x24',
                                 '-nolisten', 'tcp', '-ac'], env=env, pass_fds=(write_fd,),
                                stdout=stream, stderr=stream)
        processes.append(xvfb)
    finally:
        os.close(write_fd)
    with os.fdopen(read_fd) as pipe, selectors.DefaultSelector() as ready:
        ready.register(pipe, selectors.EVENT_READ)
        assert ready.select(10), 'Xvfb did not become ready'
        number = pipe.readline().strip()
        assert number.isdecimal(), 'Xvfb did not allocate a private display'
    env['DISPLAY'] = ':' + number
    report['display'] = env['DISPLAY']
    start(['openbox'], 'openbox')
    start(['xcompmgr', '-a'], 'compositor')
    with (logs / 'wineboot.log').open('wb') as boot:
        subprocess.run([str(runtime / 'bin/wine'), 'wineboot.exe', '-u'], env=env,
                       stdout=boot, stderr=boot, check=True, timeout=60)
    x, shape = C.CDLL('libX11.so.6'), C.CDLL('libXext.so.6')
    x.XOpenDisplay.argtypes = [C.c_char_p]
    x.XOpenDisplay.restype = C.c_void_p
    x.XGetWindowAttributes.argtypes = [C.c_void_p, C.c_ulong, C.POINTER(Attributes)]
    x.XTranslateCoordinates.argtypes = [C.c_void_p, C.c_ulong, C.c_ulong, C.c_int, C.c_int,
                                       C.c_void_p, C.c_void_p, C.c_void_p]
    x.XFree.argtypes = [C.c_void_p]
    x.XCloseDisplay.argtypes = [C.c_void_p]
    x.XGetImage.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.c_int, C.c_uint, C.c_uint, C.c_ulong, C.c_int]
    x.XGetImage.restype = C.POINTER(XImage)
    x.XDestroyImage.argtypes = [C.c_void_p]
    shape.XShapeGetRectangles.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.c_void_p, C.c_void_p]
    shape.XShapeGetRectangles.restype = C.POINTER(Rect)
    display = x.XOpenDisplay(env['DISPLAY'].encode())
    assert display
    err = (logs / 'wine.log').open('wb')
    files.append(err)
    app = subprocess.Popen([str(runtime / 'bin/wine'), str(root / 'window-regression.exe')], env=env,
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, text=True, bufsize=1)
    processes.append(app)
    reader = selectors.DefaultSelector()
    reader.register(app.stdout, selectors.EVENT_READ)
    ring = bytearray(int(4 <= min(x0, y0, 127 - x0, 127 - y0) < 24)
                     for y0 in range(128) for x0 in range(128))
    first_foreground = None
    commands = [None, 'resize', 'onepixel', 'palette', 'appwindow', 'resizable', 'edgemenu', 'bordered',
                'layered', 'plain', 'retagged', 'transparent',
                'interactive', 'remap', 'region', 'colorkey', 'cycles', 'stress', 'activate']
    for command in commands:
        if command:
            app.stdin.write(command + '\n')
            app.stdin.flush()
        deadline = time.monotonic() + 45
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not reader.select(remaining):
                raise TimeoutError('Wine probe stage timed out: ' + str(command))
            line = app.stdout.readline()
            if not line:
                raise RuntimeError('Wine probe exited early')
            if line.startswith('{'):
                stage = json.loads(line)
                break
        xid = stage['xid']
        assert xid
        attributes = Attributes()
        assert x.XGetWindowAttributes(display, xid, C.byref(attributes))
        wm_attributes = Attributes()
        assert x.XGetWindowAttributes(display, stage.get('wm_xid') or xid, C.byref(wm_attributes))
        left, top, child = C.c_int(), C.c_int(), C.c_ulong()
        assert x.XTranslateCoordinates(display, xid, attributes.root, 0, 0,
                                       C.byref(left), C.byref(top), C.byref(child))
        stage.update(width=attributes.width, height=attributes.height, mapped=attributes.map_state == 2,
                     override_redirect=bool(attributes.override_redirect), left=left.value, top=top.value)
        bounding = mask(xid, 0, attributes.width, attributes.height)
        inputs = mask(xid, 2, attributes.width, attributes.height)
        stage.update(bounding_pixels=sum(bounding), input_pixels=sum(inputs),
                     input_sha256=hashlib.sha256(inputs).hexdigest())
        name = stage['stage']
        if first_foreground is None:
            first_foreground = stage['foreground']
        if name == 'empty':
            check('zero-area popup remains unmapped', not stage['mapped'])
        elif name == 'resized':
            check('resized popup maps at 320x120', stage['mapped'] and
                  (attributes.width, attributes.height) == (320, 120))
            check('rounded non-ARGB visual region retained', 0 < sum(bounding) < 320 * 120)
        elif name == 'onepixel':
            check('nonempty 1x1 popup still maps', stage['mapped'] and
                  (attributes.width, attributes.height) == (1, 1))
        elif name in ('palette', 'appwindow', 'resizable', 'activated'):
            check(name + ': normal WM management retained', not wm_attributes.override_redirect)
            if name == 'activated':
                check('owned tool accepts explicit activation', stage['active'] == stage['hwnd'])
        elif name in ('edgemenu', 'bordered'):
            expected = (648, 900, 320, 100) if name == 'edgemenu' else (600, 852, 416, 196)
            if name == 'edgemenu':
                check('fixed menu stays unmanaged', stage['override_redirect'])
            check(name + ': requested position and size retained at screen bottom', stage['mapped'] and
                  (left.value, top.value, attributes.width, attributes.height) == expected)
            check(name + ': foreground unchanged', stage['foreground'] == first_foreground)
            if name == 'bordered':
                check('bordered shadow remains input transparent', not any(inputs))
        elif name in ('layered', 'plain', 'retagged', 'interactive', 'remapped', 'cycles', 'stress'):
            grouped = stage.get('wm_xid') and stage['wm_xid'] != xid
            check(name + ': ARGB visual region retained', bounding == ring if grouped else sum(bounding) == 128 * 128)
            check(name + ': exact alpha input mask retained', inputs == ring)
            check(name + ': tool owned by managed window stays managed', not wm_attributes.override_redirect)
            check(name + ': nonactivating popup leaves foreground unchanged', stage['foreground'] == first_foreground)
            image = x.XGetImage(display, xid, 0, 0, 128, 128, C.c_ulong(-1).value, 2)
            assert image and image.contents.bits_per_pixel == 32 and image.contents.byte_order == 0
            pixels = C.string_at(image.contents.data, image.contents.bytes_per_line * 128)
            expected = bytes((min(x0, y0, 127 - x0, 127 - y0) - 3) * 8 if ring[y0 * 128 + x0] else 0
                             for y0 in range(128) for x0 in range(128))
            check(name + ': original alpha gradient retained', pixels[3::4] == expected)
            x.XDestroyImage(image)
        elif name == 'transparent':
            check('WS_EX_TRANSPARENT input is empty', not any(inputs))
        elif name == 'region':
            expected = bytearray(v if i % 128 < 64 else 0 for i, v in enumerate(ring))
            check('explicit ARGB visual region is honored', bounding == expected)
        elif name == 'colorkey':
            expected = bytearray(int(8 <= x0 < 120 and 8 <= y0 < 120)
                                 for y0 in range(128) for x0 in range(128))
            check('color-key visual mask is honored', bounding == expected)
        report['stages'].append(stage)
    app.stdin.write('quit\n')
    app.stdin.flush()
    check('probe exits normally', app.wait(timeout=8) == 0)
    x.XCloseDisplay(display)
    completed = True
finally:
    subprocess.run([str(runtime / 'bin/wineserver'), '-k'], env=env, capture_output=True, timeout=10)
    subprocess.run([str(runtime / 'bin/wineserver'), '-w'], env=env, capture_output=True, timeout=10)
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    for stream in files:
        stream.close()
    report['completed'] = completed
    report['passed'] = (completed and len(report['stages']) == len(commands) and
                        all(c['passed'] for c in report['checks']))
    (logs / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'checks': len(report['checks']), 'passed': report['passed'],
                      'failures': [item['name'] for item in report['checks'] if not item['passed']]}))

if not report['passed']:
    raise SystemExit(1)
