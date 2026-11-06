#!/usr/bin/env python3
"""Keep pixels outside a child's bounding shape out of the shared frame."""
import argparse
from contextlib import nullcontext
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading

from isolated import desktop

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--fixture', type=Path, help='Precompiled shape-clip.c for a container without MinGW')
parser.add_argument('--existing-niri', action='store_true', help='Use a marked private niri session already running')
args = parser.parse_args()
runtime, qa = args.runtime.resolve(strict=True), args.output.resolve()
qa.mkdir(parents=True, exist_ok=False)
(qa / '.wecom-frame-qa').touch()
(qa / 'wine').symlink_to(runtime)
os.environ['WECOM_QA_ROOT'] = str(qa)
source = Path(__file__).with_name('shape-clip.c')
fixture = args.fixture.resolve(strict=True) if args.fixture else qa / 'shape-clip.exe'
if not args.fixture:
    subprocess.run(['x86_64-w64-mingw32-gcc', '-O2', '-Wall', '-Wextra', '-Werror', str(source),
                    '-o', str(fixture), '-luser32', '-lgdi32'], check=True)
report = {'host_desktop_used': False, 'account_data_used': False, 'phases': [],
          'driver_sha256': hashlib.sha256((runtime / 'lib/wine/x86_64-unix/winex11.so').read_bytes()).hexdigest(),
          'fixture_sha256': hashlib.sha256(fixture.read_bytes()).hexdigest(), 'existing_niri': args.existing_niri}
x = C.CDLL('libX11.so.6')
composite = C.CDLL('libXcomposite.so.1')
x.XOpenDisplay.argtypes = [C.c_char_p]
x.XOpenDisplay.restype = C.c_void_p
x.XCloseDisplay.argtypes = [C.c_void_p]
x.XCreateGC.argtypes = [C.c_void_p, C.c_ulong, C.c_ulong, C.c_void_p]
x.XCreateGC.restype = C.c_void_p
x.XFreeGC.argtypes = [C.c_void_p, C.c_void_p]
x.XSetForeground.argtypes = [C.c_void_p, C.c_void_p, C.c_ulong]
x.XFillRectangle.argtypes = [C.c_void_p, C.c_ulong, C.c_void_p, C.c_int, C.c_int, C.c_uint, C.c_uint]
x.XFreePixmap.argtypes = [C.c_void_p, C.c_ulong]
x.XSync.argtypes = [C.c_void_p, C.c_int]
x.XGetImage.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.c_int, C.c_uint, C.c_uint, C.c_ulong, C.c_int]
x.XGetImage.restype = C.c_void_p
x.XGetPixel.argtypes = [C.c_void_p, C.c_int, C.c_int]
x.XGetPixel.restype = C.c_ulong
x.XDestroyImage.argtypes = [C.c_void_p]
composite.XCompositeNameWindowPixmap.argtypes = [C.c_void_p, C.c_ulong]
composite.XCompositeNameWindowPixmap.restype = C.c_ulong

if args.existing_niri:
    private = Path(os.environ['XDG_RUNTIME_DIR']).resolve()
    assert (private.parent / '.wecom-frame-qa').is_file() and qa.is_relative_to(private.parent)
    assert Path(os.environ['NIRI_SOCKET']).parent.resolve() == private
    subprocess.run(['niri', 'msg', '--json', 'focused-output'], check=True, stdout=subprocess.DEVNULL)
    context = nullcontext(os.environ | {'XAUTHORITY': os.environ.get('XAUTHORITY', '')})
else:
    context = desktop(qa)

with context as env:
    env.update(WINEPREFIX=str(qa / 'prefix'), WINESERVER=str(runtime / 'bin/wineserver'),
               WINEDEBUG='-all', WINE_X11_OWNED_FRAME='1',
               WINE_X11_FRAME_ATTACHED_CLASSES='ShapeClipDecoration',
               WINE_X11_FRAME_DECORATION_CLASSES='ShapeClipDecoration',
               WINEDLLOVERRIDES='winewayland.drv=d;mscoree,mshtml,winemenubuilder=')
    saved = os.environ.get('XAUTHORITY')
    os.environ['XAUTHORITY'] = env['XAUTHORITY']
    display = x.XOpenDisplay(env['DISPLAY'].encode())
    if saved is None:
        os.environ.pop('XAUTHORITY')
    else:
        os.environ['XAUTHORITY'] = saved
    assert display

    def pixel(drawable, left, top):
        image = x.XGetImage(display, drawable, left, top, 1, 1, C.c_ulong(-1).value, 2)
        assert image
        value = x.XGetPixel(image, 0, 0)
        x.XDestroyImage(image)
        return value

    with (qa / 'wine.log').open('w') as log:
        app = subprocess.Popen([str(runtime / 'bin/wine'), str(fixture)], env=env,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True, bufsize=1)
        messages = queue.Queue()

        def read():
            for line in app.stdout:
                messages.put(json.loads(line))

        threading.Thread(target=read, daemon=True).start()
        pixmap = gc = None
        try:
            ready = messages.get(timeout=20)
            assert ready['phase'] == 'ready', ready
            assert ready['frame'] != ready['body']
            pixmap = composite.XCompositeNameWindowPixmap(display, ready['decoration'])
            gc = x.XCreateGC(display, pixmap, 0, None)
            # Outside a bounding shape, backing pixels are unspecified. Poison them deliberately.
            x.XSetForeground(display, gc, 0xffffffff)
            x.XFillRectangle(display, pixmap, gc, 80, 8, 8, 8)
            x.XSync(display, False)
            assert pixel(pixmap, 84, 12) & 0xffffff == 0xffffff
            for phase, color in (('blue', 0xff0000ff), ('green', 0xff00ff00), ('blue-again', 0xff0000ff)):
                app.stdin.write(phase + '\n')
                app.stdin.flush()
                state = messages.get(timeout=10)
                assert state['phase'] == phase, state
                sample = {'phase': phase, 'source_outside': pixel(pixmap, 84, 12),
                          'frame_outside': pixel(ready['frame'], 84, 12),
                          'decoration': pixel(ready['frame'], 8, 80),
                          'body': pixel(ready['frame'], 80, 80)}
                sample['passed'] = (sample['source_outside'] & 0xffffff == 0xffffff and sample['frame_outside'] == 0 and
                                    sample['decoration'] == 0xffff0000 and sample['body'] == color)
                report['phases'].append(sample)
        finally:
            if gc:
                x.XFreeGC(display, gc)
            if pixmap:
                x.XFreePixmap(display, pixmap)
            if app.poll() is None:
                app.stdin.write('quit\n')
                app.stdin.flush()
                app.wait(timeout=10)
            subprocess.run([env['WINESERVER'], '-k'], env=env, check=True)
            subprocess.run([env['WINESERVER'], '-w'], env=env, check=True, timeout=10)
            x.XCloseDisplay(display)
report['passed'] = len(report['phases']) == 3 and all(phase['passed'] for phase in report['phases'])
(qa / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
raise SystemExit(0 if report['passed'] else 1)
