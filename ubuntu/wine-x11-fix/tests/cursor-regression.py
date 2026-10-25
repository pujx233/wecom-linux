import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import time

work = Path('/work/r3')
runtime = Path('/work/probe-runtime')
variant = os.environ['CURSOR_VARIANT']
assert variant in ('baseline', 'candidate')
prefix = Path('/work/qa-prefix-' + variant)
for source, relative in [('wineserver-' + variant, 'bin/wineserver'),
                          ('winex11-cursor-' + variant + '.so', 'lib/wine/x86_64-unix/winex11.so')]:
    shutil.copyfile(work / source, runtime / relative)
env = os.environ.copy()
env.update(DISPLAY=':86', WINEPREFIX=str(prefix), WINEDEBUG='+cursor',
           WINESERVER=str(runtime / 'bin/wineserver'), XMODIFIERS='@im=none')
for name in ('WAYLAND_DISPLAY', 'XAUTHORITY', 'LD_PRELOAD', 'WINEDLLPATH'):
    env.pop(name, None)
log = (work / ('cursor-' + variant + '.log')).open('wb')
xvfb = subprocess.Popen(['Xvfb', ':86', '-screen', '0', '800x600x24', '-nolisten', 'tcp', '-ac'],
                        stdout=log, stderr=log)
app = None


class Cursor(C.Structure):
    _fields_ = [('x', C.c_short), ('y', C.c_short), ('width', C.c_ushort), ('height', C.c_ushort),
                ('xhot', C.c_ushort), ('yhot', C.c_ushort), ('serial', C.c_ulong),
                ('pixels', C.POINTER(C.c_ulong)), ('atom', C.c_ulong), ('name', C.c_char_p)]


try:
    time.sleep(0.4)
    x, fixes = C.CDLL('libX11.so.6'), C.CDLL('libXfixes.so.3')
    x.XOpenDisplay.argtypes, x.XOpenDisplay.restype = [C.c_char_p], C.c_void_p
    x.XDefaultRootWindow.argtypes, x.XDefaultRootWindow.restype = [C.c_void_p], C.c_ulong
    x.XWarpPointer.argtypes = [C.c_void_p, C.c_ulong, C.c_ulong, C.c_int, C.c_int,
                              C.c_uint, C.c_uint, C.c_int, C.c_int]
    x.XSync.argtypes = [C.c_void_p, C.c_int]
    x.XFree.argtypes = [C.c_void_p]
    x.XCloseDisplay.argtypes = [C.c_void_p]
    fixes.XFixesGetCursorImage.argtypes = [C.c_void_p]
    fixes.XFixesGetCursorImage.restype = C.POINTER(Cursor)
    display = x.XOpenDisplay(b':86')
    assert display
    app = subprocess.Popen([str(runtime / 'bin/wine'), str(work / 'foreign-cursor-test.exe')],
                           env=env, stdout=subprocess.PIPE, stderr=log, text=True)
    reader = selectors.DefaultSelector()
    reader.register(app.stdout, selectors.EVENT_READ)
    assert reader.select(15), 'Cursor fixture did not start'
    window = json.loads(app.stdout.readline())
    time.sleep(1)
    results = []
    for label, px, py in [('parent', 350, 250), ('text', 60, 60), ('link', 160, 60),
                          ('parent', 350, 250), ('text', 60, 60), ('link', 160, 60)]:
        x.XWarpPointer(display, 0, x.XDefaultRootWindow(display), 0, 0, 0, 0, px, py)
        x.XSync(display, 0)
        time.sleep(0.4)
        pointer = fixes.XFixesGetCursorImage(display)
        assert pointer
        cursor = pointer.contents
        pixels = b''.join((int(pixel) & 0xffffffff).to_bytes(4, 'little')
                          for pixel in cursor.pixels[:cursor.width * cursor.height])
        results.append({'region': label, 'position': [cursor.x, cursor.y],
                        'size': [cursor.width, cursor.height], 'hotspot': [cursor.xhot, cursor.yhot],
                        'name': cursor.name.decode() if cursor.name else None,
                        'pixels_sha256': hashlib.sha256(pixels).hexdigest()})
        x.XFree(pointer)
    unique = {label: {r['pixels_sha256'] for r in results if r['region'] == label}
              for label in ('parent', 'text', 'link')}
    passed = all(len(values) == 1 for values in unique.values()) and \
             len(set.union(*unique.values())) == 3
    report = {'variant': variant, 'passed': passed, 'host_desktop_used': False,
              'account_data_used': False, 'window': window, 'stages': results}
    (work / ('cursor-result-' + variant + '.json')).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    x.XCloseDisplay(display)
finally:
    subprocess.run([str(runtime / 'bin/wineserver'), '-k'], env=env, stdout=log, stderr=log)
    subprocess.run([str(runtime / 'bin/wineserver'), '-w'], env=env, stdout=log, stderr=log)
    if app:
        app.wait(timeout=5)
    xvfb.terminate()
    xvfb.wait(timeout=5)
    log.close()
raise SystemExit(0 if passed else 1)
