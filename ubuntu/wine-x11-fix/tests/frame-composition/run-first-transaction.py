import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
from PIL import Image, ImageChops
from isolated import desktop
from screencast import recording

qa = Path(sys.argv[1]).resolve()
runtime = Path(sys.argv[2]).resolve()
run = sys.argv[3]
commands = (None, 'hide', 'show', 'paint') if '--cancel' in sys.argv[4:] else (None, 'paint', 'hide')
odd_size = '--odd-size' in sys.argv[4:]
compact = '--compact' in sys.argv[4:]
left, top = (400 if compact else 500), 300
width, height = ((240, 160) if compact else (640, 960))
expected = (left, top, left + width + odd_size, top + height + odd_size)
qa.mkdir(exist_ok=True)
(qa / '.wecom-frame-qa').touch()
if not (qa / 'wine').exists():
    (qa / 'wine').symlink_to(runtime)
assert (qa / 'wine').resolve() == runtime
os.environ['WECOM_QA_ROOT'] = str(qa)
source = Path(__file__).with_name('first-transaction.c')
subprocess.run(['x86_64-w64-mingw32-gcc', '-O2', '-Wall', '-Wextra', '-Werror', str(source),
                '-o', str(qa / 'first-transaction.exe'), '-luser32', '-lgdi32'], check=True)
report = {'real_desktop_used': False, 'account_data_used': False, 'phases': [],
          'odd_size': odd_size,
          'driver': hashlib.sha256((runtime / 'lib/wine/x86_64-unix/winex11.so').read_bytes()).hexdigest()}

class SyncValue(C.Structure):
    _fields_ = [('hi', C.c_int), ('lo', C.c_uint)]

x11 = C.CDLL('libX11.so.6')
xext = C.CDLL('libXext.so.6')
x11.XOpenDisplay.argtypes = [C.c_char_p]
x11.XOpenDisplay.restype = C.c_void_p
x11.XCloseDisplay.argtypes = [C.c_void_p]
xext.XSyncQueryCounter.argtypes = [C.c_void_p, C.c_ulong, C.POINTER(SyncValue)]
with desktop(qa) as env:
    env.update(WINEPREFIX=str(qa / 'prefix'), WINESERVER=str(qa / 'wine/bin/wineserver'),
               WINEDEBUG='-all,+timestamp,+x11drv', WINE_X11_OWNED_FRAME='1',
               WINE_X11_FIXED_TRANSIENT_ARGB='1', WINE_X11_FIXED_TRANSIENT_UTILITY='1',
               WINE_WECOM_FIRST_PRESENT_ARGB='1',
               WINE_X11_FRAME_ATTACHED_CLASSES='FirstTransactionDecoration',
               WINE_X11_FRAME_DECORATION_CLASSES='FirstTransactionDecoration',
               WINEDLLOVERRIDES='winewayland.drv=d;mscoree,mshtml,winemenubuilder=')
    os.environ['XAUTHORITY'] = env['XAUTHORITY']
    display = x11.XOpenDisplay(env['DISPLAY'].encode())
    assert display
    with recording(qa, env, run) as capture, (qa / (run + '.log')).open('w') as log:
        app = subprocess.Popen([str(qa / 'wine/bin/wine'), str(qa / 'first-transaction.exe'),
                                *(['--odd-size'] if odd_size else []), *(['--compact'] if compact else [])],
                               env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=log, text=True, bufsize=1)
        replies = queue.Queue()
        def read():
            for line in app.stdout:
                replies.put(json.loads(line))
        threading.Thread(target=read, daemon=True).start()
        try:
            for command in commands:
                if command:
                    app.stdin.write(command + '\n')
                    app.stdin.flush()
                state = replies.get(timeout=20)
                mappings = [s for s in Path(f'/proc/{app.pid}/maps').read_text().splitlines()
                            if '/winex11.so' in s]
                expected_inode = (runtime / 'lib/wine/x86_64-unix/winex11.so').stat().st_ino
                assert mappings and all(int(s.split()[4]) == expected_inode for s in mappings), mappings
                report['loaded_driver_verified'] = True
                properties = subprocess.run(['xprop', '-id', str(state['frame']),
                                              '_NET_WM_SYNC_REQUEST_COUNTER', '_NET_WM_WINDOW_OPACITY'],
                                             env=env, capture_output=True, text=True, check=True).stdout
                state['properties'] = properties.strip()
                match = re.search(r'COUNTER\(CARDINAL\) = (\d+), (\d+)', properties)
                assert match, properties
                value = SyncValue()
                assert xext.XSyncQueryCounter(display, int(match[2]), C.byref(value))
                state['counter'] = value.hi << 32 | value.lo
                match = re.search(r'OPACITY\(CARDINAL\) = (\d+)', properties)
                state['opacity'] = int(match[1]) if match else 0xffffffff
                image = qa / (run + '-' + state['phase'] + '.png')
                capture(image)
                im = Image.open(image).convert('RGB')
                state['body_center'] = im.getpixel((left + width // 4, top + height // 4))
                r, g, b = im.split()
                mask = ImageChops.multiply(g.point(lambda v: 255 if v > 245 else 0),
                                          ImageChops.add(r, b).point(lambda v: 255 if v < 10 else 0))
                state['green_bounds'] = mask.getbbox()
                report['phases'].append(state)
        finally:
            if app.poll() is None:
                app.stdin.write('quit\n')
                app.stdin.flush()
                app.wait(timeout=10)
            subprocess.run([env['WINESERVER'], '-k'], env=env, timeout=5)
            subprocess.run([env['WINESERVER'], '-w'], env=env, timeout=10)
            x11.XCloseDisplay(display)
phases = {state['phase']: state for state in report['phases']}
pending, painted, hidden = (phases[name] for name in ('pending', 'paint', 'hide'))
rounding = 1 if odd_size and os.environ.get('WECOM_QA_SCALE') == '2' else 0
geometry_passed = (painted['green_bounds'] == tuple(painted['rect']) and
                   tuple(painted['rect'][:2]) == expected[:2] and
                   all(0 <= painted['rect'][i] - expected[i] <= rounding for i in (2, 3)))
report['passed'] = (pending['counter'] & 1 and pending['opacity'] == 0xffffffff and
                    pending['body_center'] == (96, 96, 96) and painted['counter'] % 2 == 0 and
                    painted['counter'] > pending['counter'] and painted['opacity'] == 0xffffffff and
                    geometry_passed and hidden['counter'] % 2 == 0)
if 'show' in phases:
    shown = phases['show']
    report['passed'] = (report['passed'] and shown['counter'] & 1 and shown['counter'] > hidden['counter'] and
                        painted['counter'] > shown['counter'] and shown['opacity'] == 0xffffffff and
                        shown['body_center'] == (96, 96, 96))
(qa / (run + '.json')).write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
assert report['passed'], 'first-frame transaction regression'
