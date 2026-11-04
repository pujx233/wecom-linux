"""Keep prepared pixels private until a frame move and extent change have been acknowledged."""
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import threading
import time

from isolated import desktop, processes

qa = Path(os.environ['WECOM_QA_ROOT']).resolve()
source = Path(__file__).with_name('resize-extents.c')
subprocess.run(['x86_64-w64-mingw32-gcc', '-O2', '-Wall', '-Wextra', '-Werror', str(source),
                '-o', str(qa / 'resize-extents.exe'), '-lgdi32', '-luser32'], check=True)
driver = qa / 'wine/lib/wine/x86_64-unix/winex11.so'
report = {'driver_sha256': hashlib.sha256(driver.read_bytes()).hexdigest(),
          'real_desktop_used': False, 'account_data_used': False,
          'wm_delayed': os.environ.get('WECOM_QA_DELAY_WM', '1') == '1'}
x = C.CDLL('libX11.so.6')
composite = C.CDLL('libXcomposite.so.1')
ext = C.CDLL('libXext.so.6')

class SyncValue(C.Structure):
    _fields_ = [('hi', C.c_int), ('lo', C.c_uint)]

ext.XSyncQueryCounter.argtypes = [C.c_void_p, C.c_ulong, C.POINTER(SyncValue)]
x.XOpenDisplay.argtypes = [C.c_char_p]
x.XOpenDisplay.restype = C.c_void_p
x.XGetImage.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.c_int, C.c_uint, C.c_uint, C.c_ulong, C.c_int]
x.XGetImage.restype = C.c_void_p
x.XGetPixel.argtypes = [C.c_void_p, C.c_int, C.c_int]
x.XGetPixel.restype = C.c_ulong
x.XDestroyImage.argtypes = [C.c_void_p]
x.XFreePixmap.argtypes = [C.c_void_p, C.c_ulong]
x.XCloseDisplay.argtypes = [C.c_void_p]
composite.XCompositeNameWindowPixmap.argtypes = [C.c_void_p, C.c_ulong]
composite.XCompositeNameWindowPixmap.restype = C.c_ulong

with desktop(qa) as env:
    env.update(WINEPREFIX=str(qa / 'prefix'), WINESERVER=str(qa / 'wine/bin/wineserver'),
               WINEDEBUG='-all,+x11drv', WINE_X11_OWNED_FRAME='1',
               WINE_X11_FRAME_ATTACHED_CLASSES='ResizeExtentsShadow',
               WINE_X11_FRAME_DECORATION_CLASSES='ResizeExtentsShadow',
               WINE_WECOM_FIRST_PRESENT_ARGB='1', WINE_X11_FIXED_TRANSIENT_ARGB='1',
               WINE_X11_FIXED_TRANSIENT_UTILITY='1',
               WINEDLLOVERRIDES='winewayland.drv=d;mscoree,mshtml,winemenubuilder=')
    os.environ['XAUTHORITY'] = env['XAUTHORITY']
    display = x.XOpenDisplay(env['DISPLAY'].encode())
    assert display

    def geometry(window):
        info = subprocess.check_output(['xwininfo', '-id', str(window), '-stats'], env=env, text=True)
        return [int(re.search(pattern, info)[1]) for pattern in
                (r'Absolute upper-left X:\s+(-?\d+)', r'Absolute upper-left Y:\s+(-?\d+)',
                 r'Width:\s+(\d+)', r'Height:\s+(\d+)')]

    def pixel(window, point):
        pixmap = composite.XCompositeNameWindowPixmap(display, window)
        image = x.XGetImage(display, pixmap, point[0], point[1], 1, 1, C.c_ulong(-1).value, 2)
        assert image
        value = x.XGetPixel(image, 0, 0) & 0xffffff
        x.XDestroyImage(image)
        x.XFreePixmap(display, pixmap)
        return value

    def counter(window):
        prop = subprocess.check_output(['xprop', '-id', str(window), '_NET_WM_SYNC_REQUEST_COUNTER'],
                                       env=env, text=True)
        match = re.search(r'COUNTER\(CARDINAL\) = (\d+), (\d+)', prop)
        assert match, prop
        value = SyncValue()
        assert ext.XSyncQueryCounter(display, int(match[2]), C.byref(value))
        return value.hi << 32 | value.lo

    with (qa / 'resize-extents.log').open('w') as log:
        app = subprocess.Popen([str(qa / 'wine/bin/wine'), str(qa / 'resize-extents.exe')], env=env,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True)
        replies = queue.Queue()

        def read():
            for line in app.stdout:
                replies.put(json.loads(line))

        threading.Thread(target=read, daemon=True).start()

        def command(value):
            app.stdin.write(value + '\n')
            app.stdin.flush()

        stopped = None
        try:
            ready = replies.get(timeout=20)
            assert ready['phase'] == 'ready', ready
            time.sleep(.3)
            mappings = [line for line in Path(f'/proc/{app.pid}/maps').read_text().splitlines()
                        if '/winex11.so' in line]
            assert mappings and all(int(line.split()[4]) == driver.stat().st_ino for line in mappings), mappings
            report['loaded_driver_verified'] = True
            report['initial'] = {'win32': ready['rect'], 'frame': geometry(ready['frame']),
                                 'body': geometry(ready['body']),
                                 'corner': pixel(ready['frame'], [10, 10]),
                                 'counter': counter(ready['frame'])}
            shells = [pid for pid, argv in processes(qa)
                      if argv and Path(os.fsdecode(argv[0])).name == 'gnome-shell']
            assert len(shells) == 1, shells
            if report['wm_delayed']:
                stopped = shells[0]
                os.kill(stopped, signal.SIGSTOP)
            command('g')
            grown = replies.get(timeout=10)
            assert grown['phase'] == 'grown', grown
            time.sleep(.3)
            report['transition'] = {'win32': grown['rect'], 'frame': geometry(ready['frame']),
                                     'body': geometry(ready['body']),
                                     'corner': pixel(ready['frame'], [10, 10]),
                                     'counter': counter(ready['frame'])}
            if stopped is not None:
                os.kill(stopped, signal.SIGCONT)
                stopped = None
            time.sleep(.5)
            command('s')
            final = replies.get(timeout=10)
            report['settled'] = {'win32': final['rect'], 'frame': geometry(ready['frame']),
                                 'body': geometry(ready['body']),
                                 'corner': pixel(ready['frame'], [10, 10]),
                                 'counter': counter(ready['frame'])}
        finally:
            if stopped is not None:
                os.kill(stopped, signal.SIGCONT)
            if app.poll() is None:
                command('q')
                app.wait(timeout=10)
            subprocess.run([env['WINESERVER'], '-k'], env=env, timeout=10)
            subprocess.run([env['WINESERVER'], '-w'], env=env, timeout=10)
            x.XCloseDisplay(display)
initial, transition, settled = (report[phase] for phase in ('initial', 'transition', 'settled'))
expected = [400, 300, 416, 336]
report['passed'] = (settled['win32'] == [400, 300, 816, 636] and settled['body'] == expected and
                    settled['frame'] == expected and settled['corner'] == 0xff and
                    settled['counter'] % 2 == 0 and settled['counter'] > initial['counter'])
if report['wm_delayed']:
    report['passed'] = (report['passed'] and transition['frame'] == initial['frame'] and
                        transition['corner'] == initial['corner'] and transition['counter'] % 2 == 1)
(qa / 'resize-extents.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
raise SystemExit(0 if report['passed'] else 1)
