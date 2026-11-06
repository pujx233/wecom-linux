#!/usr/bin/env python3
"""Check first-frame publication against KWin's basic XSync handshake."""
import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading

from PIL import Image

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime', required=True, type=Path)
parser.add_argument('--output', required=True, type=Path)
parser.add_argument('--capture', type=Path, default=Path(__file__).with_name('kwin-capture.py'))
parser.add_argument('--logical-height', type=int, default=1108)
args = parser.parse_args()
root = args.output.resolve()
assert (root.parent / '.wecom-frame-qa').is_file(), 'Use an owned isolated KWin session'
root.mkdir(exist_ok=False)
runtime = args.runtime.resolve(strict=True)
env = os.environ | {
    'WINEPREFIX': str(root / 'prefix'), 'WINESERVER': str(runtime / 'bin/wineserver'),
    'WINEDEBUG': '-all,+timestamp,+x11drv', 'WINE_X11_OWNED_FRAME': '1',
    'WINE_X11_FIXED_TRANSIENT_ARGB': '1', 'WINE_X11_FIXED_TRANSIENT_UTILITY': '1',
    'WINE_WECOM_FIRST_PRESENT_ARGB': '1',
    'WINE_X11_FRAME_ATTACHED_CLASSES': 'FirstTransactionDecoration',
    'WINE_X11_FRAME_DECORATION_CLASSES': 'FirstTransactionDecoration',
    'WINEDLLOVERRIDES': 'winewayland.drv=d;mscoree,mshtml,winemenubuilder=',
}
fixture = root / 'first-transaction.exe'
subprocess.run(['x86_64-w64-mingw32-gcc', '-O2', '-Wall', '-Wextra', '-Werror',
                str(Path(__file__).with_name('first-transaction.c')), '-o', str(fixture),
                '-luser32', '-lgdi32'], check=True)
x = C.CDLL('libX11.so.6')
ext = C.CDLL('libXext.so.6')
x.XOpenDisplay.argtypes = [C.c_char_p]
x.XOpenDisplay.restype = C.c_void_p
x.XDefaultRootWindow.argtypes = [C.c_void_p]
x.XDefaultRootWindow.restype = C.c_ulong
x.XDisplayHeight.argtypes = [C.c_void_p, C.c_int]
x.XDisplayHeight.restype = C.c_int
x.XTranslateCoordinates.argtypes = [C.c_void_p, C.c_ulong, C.c_ulong, C.c_int, C.c_int,
                                    C.POINTER(C.c_int), C.POINTER(C.c_int), C.POINTER(C.c_ulong)]
x.XCloseDisplay.argtypes = [C.c_void_p]


class SyncValue(C.Structure):
    _fields_ = [('hi', C.c_int), ('lo', C.c_uint)]


ext.XSyncQueryCounter.argtypes = [C.c_void_p, C.c_ulong, C.POINTER(SyncValue)]
display = x.XOpenDisplay(None)
assert display
scale = x.XDisplayHeight(display, 0) / args.logical_height
report = {'account_data_used': False, 'host_desktop_used': False, 'phases': [],
          'driver_sha256': hashlib.sha256((runtime / 'lib/wine/x86_64-unix/winex11.so').read_bytes()).hexdigest(),
          'native_to_logical_scale': scale,
          'root_supported': subprocess.check_output(['xprop', '-root', '_NET_SUPPORTED'], text=True)}
assert '_NET_WM_FRAME_DRAWN' not in report['root_supported'], 'This case requires the basic protocol'
with (root / 'wine.log').open('w') as log:
    app = subprocess.Popen([str(runtime / 'bin/wine'), str(fixture), '--compact'], env=env,
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True)
    replies = queue.Queue()

    def read():
        for line in app.stdout:
            if line.startswith('{'):
                replies.put(json.loads(line))

    threading.Thread(target=read, daemon=True).start()
    try:
        for index, command in enumerate((None, 'paint', 'hide', 'show', 'paint', 'hide', 'show', 'paint')):
            if command:
                app.stdin.write(command + '\n')
                app.stdin.flush()
            state = replies.get(timeout=60)
            mappings = [line for line in Path(f'/proc/{app.pid}/maps').read_text().splitlines()
                        if '/winex11.so' in line]
            inode = (runtime / 'lib/wine/x86_64-unix/winex11.so').stat().st_ino
            assert mappings and all(int(line.split()[4]) == inode for line in mappings), mappings
            report['loaded_driver_verified'] = True
            properties = subprocess.check_output(['xprop', '-id', str(state['frame']),
                                                  '_NET_WM_SYNC_REQUEST_COUNTER',
                                                  '_XWAYLAND_ALLOW_COMMITS'], text=True)
            state['properties'] = properties
            state['allow_commits'] = next((int(line.partition('=')[2]) for line in properties.splitlines()
                                          if line.startswith('_XWAYLAND_ALLOW_COMMITS') and '=' in line), None)
            counters = next((line.partition('=')[2].strip() for line in properties.splitlines()
                             if line.startswith('_NET_WM_SYNC_REQUEST_COUNTER') and '=' in line), '')
            state['counters'] = []
            for counter in counters.split(',') if counters else ():
                value = SyncValue()
                assert ext.XSyncQueryCounter(display, int(counter), C.byref(value))
                state['counters'].append((value.hi << 32) | value.lo)
            if state['phase'] != 'hide':
                px, py, child = C.c_int(), C.c_int(), C.c_ulong()
                assert x.XTranslateCoordinates(display, state['body'], x.XDefaultRootWindow(display),
                                               120, 80, C.byref(px), C.byref(py), C.byref(child))
                state['center'] = [round(px.value / scale), round(py.value / scale)]
                image = root / f'{index}-{state["phase"]}.png'
                subprocess.run(['python3', str(args.capture), str(image)], check=True,
                                env=os.environ | {'WECOM_QA_ROOT': str(root.parent)})
                state['rgb'] = list(Image.open(image).convert('RGB').getpixel(tuple(state['center'])))
            report['phases'].append(state)
    finally:
        if app.poll() is None:
            app.stdin.write('quit\n')
            app.stdin.flush()
            app.wait(timeout=15)
        subprocess.run([env['WINESERVER'], '-k'], env=env, timeout=15)
        subprocess.run([env['WINESERVER'], '-w'], env=env, timeout=15)
        x.XCloseDisplay(display)
report['passed'] = all(len(state['counters']) == 1 and
                       (state['rgb'] == [96, 96, 96] and state['counters'][0] == 0 and
                        state['allow_commits'] == 0 if state['phase'] in ('pending', 'show') else
                        state['counters'][0] > 0 and state['allow_commits'] == 1 and
                        state.get('rgb', [0, 255, 0]) == [0, 255, 0]) for state in report['phases'])
(root / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report), flush=True)
raise SystemExit(0 if report['passed'] else 1)
