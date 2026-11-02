"""Check native drawable size and newly exposed pixels inside synchronous WM_SIZE."""
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import threading
import time

from isolated import desktop

qa = Path(os.environ['WECOM_QA_ROOT']).resolve()
source = Path(__file__).with_name('resize-drawable.c')
subprocess.run(['x86_64-w64-mingw32-gcc', '-O2', '-Wall', '-Wextra', '-Werror', str(source),
                '-o', str(qa / 'resize-drawable.exe'), '-lgdi32', '-luser32'], check=True)
driver = qa / 'wine/lib/wine/x86_64-unix/winex11.so'
report = {'real_desktop_used': False, 'account_data_used': False, 'phases': [],
          'driver_sha256': hashlib.sha256(driver.read_bytes()).hexdigest()}
x = C.CDLL('libX11.so.6')
composite = C.CDLL('libXcomposite.so.1')
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
               WINE_X11_FRAME_ATTACHED_CLASSES='ResizeDrawableShadow',
               WINE_X11_FRAME_DECORATION_CLASSES='ResizeDrawableShadow',
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

    with (qa / 'resize-drawable.log').open('w') as log:
        app = subprocess.Popen([str(qa / 'wine/bin/wine'), str(qa / 'resize-drawable.exe')], env=env,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True)
        replies = queue.Queue()

        def read():
            for line in app.stdout:
                replies.put(json.loads(line))

        threading.Thread(target=read, daemon=True).start()

        def command(value):
            app.stdin.write(value + '\n')
            app.stdin.flush()

        try:
            ready = replies.get(timeout=20)
            assert ready['phase'] == 'ready', ready
            report['initial_client'] = ready['client']
            report['initial_frame'] = geometry(ready['frame'])
            mappings = [line for line in Path(f'/proc/{app.pid}/maps').read_text().splitlines()
                        if '/winex11.so' in line]
            assert mappings and all(int(line.split()[4]) == driver.stat().st_ino for line in mappings), mappings
            report['loaded_driver_verified'] = True
            command('m')
            for phase in ('before-draw', 'after-draw', 'done'):
                state = replies.get(timeout=10)
                assert state['phase'] == phase, state
                native = geometry(state['body'])[2:]
                state['native_drawable'] = native
                state['geometry_matches'] = native == state['client']
                state['native_frame'] = geometry(state['frame'])
                state['frame_geometry_held'] = state['native_frame'][2:] == report['initial_frame'][2:]
                if phase == 'after-draw' and state['geometry_matches']:
                    deadline = time.monotonic() + 2
                    while True:
                        value = pixel(state['body'], [native[0] - 10, native[1] - 10])
                        if value == 0xff or time.monotonic() >= deadline:
                            break
                        time.sleep(.01)
                    state['new_region_pixel'] = value
                    state['new_region_blue'] = value == 0xff
                report['phases'].append(state)
                if phase == 'before-draw': command('d')
                elif phase == 'after-draw': command('f')
            deadline = time.monotonic() + 3
            while True:
                body, frame = geometry(ready['body']), geometry(ready['frame'])
                point = [body[i] - frame[i] + state['client'][i] - 10 for i in (0, 1)]
                fits = all(0 <= point[i] < frame[i + 2] for i in (0, 1))
                value = pixel(ready['frame'], point) if fits else None
                presented = (value == 0xff and body[2:] == state['client'] and
                             frame[2:] != report['initial_frame'][2:])
                if presented or time.monotonic() >= deadline:
                    break
                time.sleep(.01)
            report['settled'] = {'native_body': body, 'native_frame': frame, 'point': point,
                                 'new_region_pixel': value, 'new_region_blue': presented}
        finally:
            if app.poll() is None:
                command('q')
                app.wait(timeout=10)
            subprocess.run([env['WINESERVER'], '-k'], env=env, timeout=10)
            subprocess.run([env['WINESERVER'], '-w'], env=env, timeout=10)
            x.XCloseDisplay(display)
report['passed'] = (all(report['phases'][0]['client'][i] > report['initial_client'][i] for i in (0, 1)) and
                    all(state['geometry_matches'] for state in report['phases']) and
                    all(state['frame_geometry_held'] for state in report['phases'][:2]) and
                    report['phases'][1].get('new_region_blue', False) and report['settled']['new_region_blue'])
(qa / 'resize-drawable.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'passed': report['passed'], 'driver_sha256': report['driver_sha256'],
                  'geometry_matches': [state['geometry_matches'] for state in report['phases']]}))
raise SystemExit(0 if report['passed'] else 1)
