from datetime import datetime, timezone
import hashlib
import ctypes as C
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
from PIL import Image
from isolated import desktop
from screencast import recording

qa = Path(os.environ['WECOM_QA_ROOT']).resolve()
name = 'foreign-frame-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
report = {'account_data_used': False, 'main_desktop_used': False, 'samples': [],
          'driver_sha256': hashlib.sha256((qa / 'wine/lib/wine/x86_64-unix/winex11.so').read_bytes()).hexdigest()}
subprocess.run(['x86_64-w64-mingw32-gcc', '-O2', '-Wall', '-Wextra',
                str(Path(__file__).with_name('foreign-frame.c')), '-o', str(qa / 'foreign-frame.exe'),
                '-lgdi32', '-luser32'], check=True)
with desktop(qa) as env:
    env.update(WINEPREFIX=str(qa / 'prefix'), WINESERVER=str(qa / 'wine/bin/wineserver'),
               WINEDEBUG=os.environ.get('QA_WINEDEBUG', '-all,+x11drv'), WINE_X11_OWNED_FRAME='1',
               WINEDLLOVERRIDES='winewayland.drv=d;mscoree,mshtml,winemenubuilder=')
    with recording(qa, env, name) as capture, (qa / (name + '.log')).open('w') as log:
        app = subprocess.Popen([str(qa / 'wine/bin/wine'), str(qa / 'foreign-frame.exe')],
                               env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True, bufsize=1)
        lines = queue.Queue()
        def read():
            for line in app.stdout:
                lines.put(json.loads(line))
        threading.Thread(target=read, daemon=True).start()
        def wait(event, sequence=None):
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                value = lines.get(timeout=max(.01, deadline-time.monotonic()))
                if value['event'] == event and (sequence is None or value.get('sequence') == sequence):
                    return value
            raise TimeoutError(event)
        try:
            report['ready'] = wait('ready')
            time.sleep(1)
            x = C.CDLL('libX11.so.6'); comp = C.CDLL('libXcomposite.so.1')
            x.XOpenDisplay.restype = C.c_void_p
            comp.XCompositeNameWindowPixmap.argtypes = [C.c_void_p, C.c_ulong]
            comp.XCompositeNameWindowPixmap.restype = C.c_ulong
            x.XGetImage.argtypes = [C.c_void_p,C.c_ulong,C.c_int,C.c_int,C.c_uint,C.c_uint,C.c_ulong,C.c_int]
            x.XGetImage.restype = C.c_void_p
            x.XGetPixel.argtypes = [C.c_void_p,C.c_int,C.c_int]; x.XGetPixel.restype = C.c_ulong
            x.XDestroyImage.argtypes = [C.c_void_p]
            x.XFreePixmap.argtypes = [C.c_void_p,C.c_ulong]
            x.XCloseDisplay.argtypes = [C.c_void_p]
            saved_authority = os.environ.get('XAUTHORITY'); os.environ['XAUTHORITY'] = env['XAUTHORITY']
            display = x.XOpenDisplay(env['DISPLAY'].encode())
            if saved_authority is None: os.environ.pop('XAUTHORITY')
            else: os.environ['XAUTHORITY'] = saved_authority
            assert display
            def source_pixel(px, py):
                pixmap = comp.XCompositeNameWindowPixmap(display, report['ready']['body'])
                image = x.XGetImage(display, pixmap, px, py, 1, 1, C.c_ulong(-1).value, 2)
                assert image
                value = x.XGetPixel(image, 0, 0) & 0xffffff
                x.XDestroyImage(image); x.XFreePixmap(display, pixmap)
                return value
            report['source_pixel_below_overlay'] = source_pixel(100, 20)
            report['application_source_unchanged'] = report['source_pixel_below_overlay'] == 0x808080
            for sequence in range(1, 9):
                if sequence == 5:
                    app.stdin.write('arm\n'); app.stdin.flush(); wait('armed')
                    x.XResizeWindow.argtypes = [C.c_void_p, C.c_ulong, C.c_uint, C.c_uint]
                    x.XFlush.argtypes = [C.c_void_p]
                    x.XResizeWindow(display, report['ready']['frame'], 900, 650); x.XFlush(display)
                else:
                    app.stdin.write('draw\n'); app.stdin.flush()
                event = wait('draw', sequence)
                if sequence == 5: report['nested'] = wait('nested')
                started = time.monotonic()
                expected = (255, 0, 0) if sequence & 1 else (0, 0, 255)
                target = qa / f'{name}-{sequence}.png'
                while True:
                    capture(target)
                    pixel = Image.open(target).convert('RGB').getpixel((400, 300))
                    if pixel == expected or time.monotonic() - started > 1:
                        break
                    time.sleep(.025)
                elapsed_ms = (time.monotonic() - started) * 1000
                # Read the source after the visible-frame deadline, so readback cannot trigger success.
                native_pixel = source_pixel(200, 200)
                source_rgb = tuple((native_pixel >> shift) & 255 for shift in (16, 8, 0))
                gdi_pixel = sum(value << shift for value, shift in zip(expected, (0, 8, 16)))
                report['samples'].append(dict(sequence=sequence, draw=event, native_source_pixel=native_pixel,
                                              pixel=pixel, expected=expected,
                                              trigger='nested-resize' if sequence == 5 else 'direct-event',
                                              passed=elapsed_ms <= 1000 and pixel == expected and
                                                     source_rgb == expected and event['pixel'] == gdi_pixel,
                                              elapsed_ms=elapsed_ms))
            x.XCloseDisplay(display)
        finally:
            if app.poll() is None:
                app.stdin.write('quit\n'); app.stdin.flush()
                app.wait(timeout=10)
            report['application_exit_code'] = app.returncode
            subprocess.run([env['WINESERVER'], '-k'], env=env, check=True)
            subprocess.run([env['WINESERVER'], '-w'], env=env, check=True, timeout=8)
report['passed'] = (report['application_exit_code'] == 0 and report['application_source_unchanged'] and
                    all(sample['passed'] for sample in report['samples']))
report['timing_note'] = 'Sample five starts timing after the artificial nested loop returns; other samples start at draw acknowledgement.'
path = qa / (name + '.json')
path.write_text(json.dumps(report, indent=2) + '\n')
print(path)
print(json.dumps(report))
raise SystemExit(0 if report['passed'] else 1)
