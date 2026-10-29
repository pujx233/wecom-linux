from datetime import datetime, timezone
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
from isolated import desktop
from screencast import recording
from PIL import Image

qa = Path(os.environ['WECOM_QA_ROOT']).resolve()
name = 'popup-input-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
subprocess.run(['x86_64-w64-mingw32-gcc', '-O2', '-Wall', '-Wextra',
                str(Path(__file__).with_name('popup-input.c')), '-o', str(qa / 'popup-input.exe'),
                '-lgdi32', '-luser32'], check=True)
x = C.CDLL('libX11.so.6')
x.XOpenDisplay.restype = C.c_void_p
x.XDefaultRootWindow.argtypes = [C.c_void_p]; x.XDefaultRootWindow.restype = C.c_ulong
x.XCreateSimpleWindow.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.c_int, C.c_uint,
                                  C.c_uint, C.c_uint, C.c_ulong, C.c_ulong]
x.XCreateSimpleWindow.restype = C.c_ulong
for function in ('XMapRaised', 'XDestroyWindow', 'XPending', 'XFlush', 'XCloseDisplay'):
    getattr(x, function).argtypes = [C.c_void_p] + (
        [] if function in ('XPending', 'XFlush', 'XCloseDisplay') else [C.c_ulong])
x.XSelectInput.argtypes = [C.c_void_p, C.c_ulong, C.c_long]
x.XSetInputFocus.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.c_ulong]
x.XSync.argtypes = [C.c_void_p, C.c_int]
x.XNextEvent.argtypes = [C.c_void_p, C.c_void_p]
x.XQueryPointer.argtypes = [C.c_void_p, C.c_ulong] + [C.c_void_p] * 7
report = {'driver_sha256': hashlib.sha256((qa / 'wine/lib/wine/x86_64-unix/winex11.so').read_bytes()).hexdigest(),
          'account_data_used': False, 'main_desktop_used': False, 'cases': []}
with desktop(qa) as env:
    env.update(WINEPREFIX=str(qa / 'prefix'), WINESERVER=str(qa / 'wine/bin/wineserver'),
               WINEDEBUG='-all,+x11drv', WINE_X11_OWNED_FRAME='1',
               WINE_X11_FRAME_ATTACHED_CLASSES='PopupInputRegression',
               WINE_WECOM_FIRST_PRESENT_ARGB='1', WINE_X11_FIXED_TRANSIENT_ARGB='1',
               WINE_X11_FIXED_TRANSIENT_UTILITY='1',
               WINEDLLOVERRIDES='winewayland.drv=d;mscoree,mshtml,winemenubuilder=')
    saved = os.environ.get('XAUTHORITY'); os.environ['XAUTHORITY'] = env['XAUTHORITY']
    d = x.XOpenDisplay(env['DISPLAY'].encode())
    if saved is None: os.environ.pop('XAUTHORITY')
    else: os.environ['XAUTHORITY'] = saved
    assert d
    root = x.XDefaultRootWindow(d)
    sentinel = x.XCreateSimpleWindow(d, root, 150, 100, 1100, 800, 0, 0, 0x00ff00)
    x.XSelectInput(d, sentinel, (1 << 2) | (1 << 3))
    x.XMapRaised(d, sentinel); x.XSync(d, False)
    time.sleep(.4)
    def pointer():
        r, child = C.c_ulong(), C.c_ulong()
        rx, ry, wx, wy = [C.c_int() for _ in range(4)]
        mask = C.c_uint()
        x.XQueryPointer(d, root, C.byref(r), C.byref(child), C.byref(rx), C.byref(ry),
                        C.byref(wx), C.byref(wy), C.byref(mask))
        return {'point': [rx.value, ry.value], 'child': child.value}
    try:
        with recording(qa, env, name, interactive=True) as capture, (qa / (name + '.log')).open('w') as log:
            for mode in ('0', '20', '80020'):
                x.XFlush(d)
                app = subprocess.Popen([str(qa / 'wine/bin/wine'), str(qa / 'popup-input.exe'), mode],
                                       env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=log, text=True, bufsize=1)
                events = []; lines = queue.Queue()
                def read():
                    for line in app.stdout: lines.put(json.loads(line))
                reader = threading.Thread(target=read, daemon=True); reader.start()
                try:
                    ready = lines.get(timeout=15); assert ready['event'] == 'ready'
                    time.sleep(.8)
                    deadline = time.monotonic() + 3
                    while True:
                        capture.pointer(500, 400); time.sleep(.1)
                        if pointer()['point'] == [500, 400]: break
                        assert time.monotonic() < deadline, pointer()
                    case = {'extra_ex_style': mode, 'ready': ready, 'before': pointer(),
                            'sentinel_events': [], 'events': events}
                    report['cases'].append(case)
                    for _ in range(3):
                        capture.button(True)
                        time.sleep(.1)
                        capture.button(False)
                        time.sleep(.25)
                    app.stdin.write('state\n'); app.stdin.flush(); time.sleep(.2)
                    while not lines.empty(): events.append(lines.get_nowait())
                    native_event = (C.c_long * 24)()
                    while x.XPending(d):
                        x.XNextEvent(d, C.byref(native_event))
                        kind = C.cast(C.byref(native_event), C.POINTER(C.c_int))[0]
                        if kind in (4, 5): case['sentinel_events'].append(kind)
                    case['after'] = pointer()
                    case['down'] = sum(e['event'] == 'down' for e in events)
                    case['up'] = sum(e['event'] == 'up' for e in events)
                    final = next(e for e in events if e['event'] == 'state')
                    case['native_role_stable'] = (final['body'], final['frame']) == (ready['body'], ready['frame'])
                    case['passed'] = ((case['down'], case['up'], len(case['sentinel_events'])) ==
                                      ((0, 0, 6) if mode == '80020' else (3, 3, 0)) and case['native_role_stable'])
                    capture(qa / f'{name}-{mode}.png')
                    if mode == '0':
                        app.stdin.write('preview\n'); app.stdin.flush()
                        preview = lines.get(timeout=5); assert preview['event'] == 'preview', preview
                        target = qa / f'{name}-preview.png'
                        deadline = time.monotonic() + 1.5
                        while True:
                            capture(target)
                            pixel = Image.open(target).convert('RGB').getpixel((550, 400))
                            if pixel == (0, 0, 255) or time.monotonic() > deadline: break
                            time.sleep(.04)
                        case['owned_preview'] = dict(pixel=pixel, above_owner=pixel==(0, 0, 255), native=preview)
                        case['passed'] &= case['owned_preview']['above_owner']
                        case['sibling_stack'] = []
                        for command, expected in [('red', (255, 0, 0)), ('blue', (0, 0, 255)),
                                                  ('top-red', (255, 0, 0)), ('blue', (0, 0, 255))]:
                            app.stdin.write(command + '\n'); app.stdin.flush()
                            response = lines.get(timeout=5)
                            logical = None
                            if command == 'red':
                                # Mapping can activate another existing tool; compare with settled Win32 order.
                                time.sleep(.8)
                                app.stdin.write('state\n'); app.stdin.flush()
                                logical = lines.get(timeout=5)
                                assert logical['event'] == 'state' and logical['top_preview'] in (0, 1)
                                expected = (255, 0, 0) if logical['top_preview'] else (0, 0, 255)
                            deadline = time.monotonic() + 1.5
                            while True:
                                capture(target)
                                pixel = Image.open(target).convert('RGB').getpixel((550, 400))
                                if pixel == expected or time.monotonic() > deadline: break
                                time.sleep(.04)
                            sample = dict(command=command, response=response, pixel=pixel,
                                          logical=logical, expected=expected, passed=pixel==expected)
                            case['sibling_stack'].append(sample)
                            case['passed'] &= sample['passed']
                finally:
                    if app.poll() is None:
                        app.stdin.write('quit\n'); app.stdin.flush(); app.wait(timeout=8)
                    subprocess.run([env['WINESERVER'], '-k'], env=env, check=True)
                    subprocess.run([env['WINESERVER'], '-w'], env=env, check=True, timeout=8)
    finally:
        x.XDestroyWindow(d, sentinel); x.XCloseDisplay(d)
report['passed'] = all(c['passed'] for c in report['cases'])
path = qa / (name + '.json'); path.write_text(json.dumps(report, indent=2) + '\n')
print(path); print(json.dumps(report))
raise SystemExit(0 if report['passed'] else 1)
