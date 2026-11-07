"""Check cross-process GDI drawing and foreign drawable coordinates on a private Xvfb."""
import argparse
import ctypes as C
import json
import hashlib
import os
from pathlib import Path
import selectors
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime', required=True, type=Path)
parser.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
runtime, work = args.runtime.resolve(strict=True), args.output.resolve()
work.mkdir(parents=True, exist_ok=False)
prefix = work / 'prefix'
subprocess.run(['i686-w64-mingw32-gcc', '-O2', '-Wall', '-Wextra',
                str(Path(__file__).with_name('foreign-dc-test.c')),
                '-o', str(work / 'foreign-dc-test.exe'), '-lgdi32', '-luser32'], check=True)
env = os.environ.copy()
env.update(WINEPREFIX=str(prefix), WINEDEBUG='-all', WINESERVER=str(runtime / 'bin/wineserver'),
           XMODIFIERS='@im=none', WINEDLLOVERRIDES='mscoree,mshtml,winemenubuilder=',
           DBUS_SYSTEM_BUS_ADDRESS='unix:path=' + str(work / 'no-system-bus'))
for name in ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'LD_PRELOAD', 'WINEDLLPATH', 'DBUS_SESSION_BUS_ADDRESS'):
    env.pop(name, None)
log = (work / 'wine.log').open('wb')
read_fd, write_fd = os.pipe()
try:
    xvfb = subprocess.Popen(['Xvfb', '-displayfd', str(write_fd), '-screen', '0', '800x600x24',
                             '-nolisten', 'tcp', '-ac'], pass_fds=(write_fd,), stdout=log, stderr=log, env=env)
finally:
    os.close(write_fd)
app = None


class XImage(C.Structure):
    _fields_ = [(n, C.c_int) for n in ('width', 'height', 'xoffset', 'format')]
    _fields_ += [('data', C.c_void_p)]
    _fields_ += [(n, C.c_int) for n in ('byte_order', 'bitmap_unit', 'bitmap_bit_order', 'bitmap_pad',
                                     'depth', 'bytes_per_line', 'bits_per_pixel')]


try:
    with os.fdopen(read_fd) as pipe, selectors.DefaultSelector() as ready:
        ready.register(pipe, selectors.EVENT_READ)
        assert ready.select(10), 'Xvfb did not become ready'
        number = pipe.readline().strip()
        assert number.isdecimal(), 'Xvfb did not allocate a private display'
    env['DISPLAY'] = ':' + number
    subprocess.run([str(runtime / 'bin/wine'), 'wineboot.exe', '-u'], env=env,
                   stdout=log, stderr=log, check=True, timeout=60)
    x = C.CDLL('libX11.so.6')
    x.XOpenDisplay.restype = C.c_void_p
    x.XGetImage.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.c_int, C.c_uint, C.c_uint, C.c_ulong, C.c_int]
    x.XGetImage.restype = C.POINTER(XImage)
    x.XDestroyImage.argtypes = [C.c_void_p]
    x.XSetWindowBackground.argtypes = [C.c_void_p, C.c_ulong, C.c_ulong]
    x.XClearArea.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.c_int, C.c_uint, C.c_uint, C.c_int]
    x.XSync.argtypes = [C.c_void_p, C.c_int]
    x.XCloseDisplay.argtypes = [C.c_void_p]
    display = x.XOpenDisplay(env['DISPLAY'].encode())
    assert display
    app = subprocess.Popen([str(runtime / 'bin/wine'), str(work / 'foreign-dc-test.exe')], env=env,
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True, bufsize=1)
    reader = selectors.DefaultSelector()
    reader.register(app.stdout, selectors.EVENT_READ)
    results = []
    for command in (None, 'expose', 'repaint', 'hide', 'show', 'move'):
        if command == 'expose':
            x.XSetWindowBackground(display, stage['xid'], 0)
            x.XClearArea(display, stage['xid'], 40, 40, 80, 80, 1)
            x.XSync(display, 0)
        if command:
            app.stdin.write(command + '\n')
            app.stdin.flush()
        assert reader.select(15), 'Probe stage timed out'
        stage = json.loads(app.stdout.readline())
        image = x.XGetImage(display, stage['xid'], 0, 0, 400, 300, C.c_ulong(-1).value, 2)
        assert image
        info = image.contents
        assert info.bits_per_pixel == 32 and info.byte_order == 0
        data = C.string_at(info.data, info.bytes_per_line * info.height)
        pixel = lambda px, py: list(data[py * info.bytes_per_line + px * 4:py * info.bytes_per_line + px * 4 + 3])
        old, new = pixel(60, 60), pixel(180, 180)
        expected = ([255, 0, 0], [255, 0, 0]) if command == 'hide' else \
                   ([255, 0, 0], [0, 255, 0]) if command == 'move' else ([0, 255, 0], [255, 0, 0])
        stage.update(old_position_bgr=old, new_position_bgr=new, passed=(old, new) == expected)
        results.append(stage)
        x.XDestroyImage(image)
    app.stdin.write('quit\n')
    app.stdin.flush()
    assert app.wait(timeout=5) == 0, 'Probe did not exit normally'
    x.XCloseDisplay(display)
    report = {'display': env['DISPLAY'], 'host_desktop_used': False, 'account_data_used': False, 'stages': results,
              'win32u_sha256': hashlib.sha256((runtime / 'lib/wine/x86_64-unix/win32u.so').read_bytes()).hexdigest(),
              'winex11_sha256': hashlib.sha256((runtime / 'lib/wine/x86_64-unix/winex11.so').read_bytes()).hexdigest(),
              'test_exe_sha256': hashlib.sha256((work / 'foreign-dc-test.exe').read_bytes()).hexdigest()}
    report['passed'] = all(stage['passed'] for stage in results)
    (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
finally:
    subprocess.run([str(runtime / 'bin/wineserver'), '-k'], env=env)
    subprocess.run([str(runtime / 'bin/wineserver'), '-w'], env=env)
    if app:
        app.wait(timeout=5)
    xvfb.terminate()
    xvfb.wait(timeout=5)
    log.close()

if not all(stage['passed'] for stage in results):
    raise SystemExit(1)
