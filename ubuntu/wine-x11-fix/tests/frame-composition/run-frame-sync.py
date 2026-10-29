#!/usr/bin/env python3
"""Require frame-sync completion to follow the final shared-frame copy."""
import argparse
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
from PIL import Image
from isolated import desktop
from screencast import recording

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
qa = args.output.resolve()
qa.mkdir(parents=True, exist_ok=False)
(qa / '.wecom-frame-qa').touch()
(qa / 'wine').symlink_to(args.runtime.resolve(), target_is_directory=True)
os.environ['WECOM_QA_ROOT'] = str(qa)
source = Path(__file__).with_name('frame-sync.c')
fixture = qa / 'frame-sync.exe'
subprocess.run(['x86_64-w64-mingw32-gcc', '-O2', '-Wall', '-Wextra', '-Werror', str(source),
                '-o', str(fixture), '-lgdi32', '-luser32'], check=True)
report = {'host_desktop_used': False, 'account_data_used': False, 'phases': [], 'runtime_sha256': {}}
for name in ('win32u.so', 'winex11.so'):
    report['runtime_sha256'][name] = hashlib.sha256(
        (qa / 'wine/lib/wine/x86_64-unix' / name).read_bytes()).hexdigest()
report['test_sha256'] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in (source, Path(__file__))}

class SyncValue(C.Structure):
    _fields_ = [('hi', C.c_int), ('lo', C.c_uint)]

with desktop(qa) as env:
    env.update(WINEPREFIX=str(qa / 'prefix'), WINESERVER=str(qa / 'wine/bin/wineserver'),
               WINEDEBUG='-all,+x11drv,+win', WINE_X11_OWNED_FRAME='1', WECOM_FRAME_SYNC_FIXTURE='1',
               WINE_X11_FRAME_ATTACHED_CLASSES='FrameSyncCompletion',
               WINE_X11_FRAME_DECORATION_CLASSES='FrameSyncCompletion',
               WINEDLLOVERRIDES='winewayland.drv=d;mscoree,mshtml,winemenubuilder=')
    with (qa / 'wine.log').open('w') as log, recording(qa, env, 'frame-sync') as capture:
        app = subprocess.Popen([str(qa / 'wine/bin/wine'), str(fixture)], env=env, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=log, text=True, bufsize=1)
        messages = queue.Queue()
        def read():
            for line in app.stdout:
                messages.put(json.loads(line))
        threading.Thread(target=read, daemon=True).start()
        def command(value):
            app.stdin.write(value + '\n')
            app.stdin.flush()
            reply = messages.get(timeout=15)
            assert reply['phase'] == value, reply
        display = None
        try:
            ready = messages.get(timeout=15)
            assert ready['phase'] == 'ready', ready
            assert ready['frame'] == ready['decoration_frame'], ready
            props = subprocess.run(['xprop', '-id', str(ready['frame']), '_NET_WM_SYNC_REQUEST_COUNTER'],
                                   env=env, capture_output=True, text=True, check=True).stdout
            counters = [int(value) for value in re.findall(r'\d+', props.split('=')[1])]
            assert len(counters) == 2, props
            x = C.CDLL('libX11.so.6')
            ext = C.CDLL('libXext.so.6')
            x.XOpenDisplay.argtypes = [C.c_char_p]
            x.XOpenDisplay.restype = C.c_void_p
            x.XCloseDisplay.argtypes = [C.c_void_p]
            ext.XSyncQueryCounter.argtypes = [C.c_void_p, C.c_ulong, C.POINTER(SyncValue)]
            saved = os.environ.get('XAUTHORITY')
            os.environ['XAUTHORITY'] = env['XAUTHORITY']
            display = x.XOpenDisplay(env['DISPLAY'].encode())
            if saved is None: os.environ.pop('XAUTHORITY')
            else: os.environ['XAUTHORITY'] = saved
            assert display
            for phase in ('ready', 'paint', 'dispatch'):
                if phase != 'ready': command(phase)
                value = SyncValue()
                assert ext.XSyncQueryCounter(display, counters[1], C.byref(value))
                counter = (value.hi << 32) | value.lo
                path = qa / (phase + '.png')
                time.sleep(.15)
                capture(path)
                pixel = Image.open(path).convert('RGB').getpixel(tuple(ready['point']))
                expected = (64, 96, 192) if phase == 'dispatch' else (48, 176, 96)
                passed = (counter & 1) == (phase == 'paint') and pixel == expected
                report['phases'].append(dict(name=phase, counter=counter, pixel=pixel,
                                             expected=expected, passed=passed))
            resize_log = (qa / 'wine.log').read_text().split('FRAME_SYNC_RESIZE_BEGIN\n')[1]
            resize_log = resize_log.split('FRAME_SYNC_RESIZE_END\n')[0]
            report['surface_reused'] = 'trying to reuse previous surface' in resize_log
        except Exception as error:
            report['error'] = str(error) or type(error).__name__
        finally:
            if display: x.XCloseDisplay(display)
            if app.poll() is None:
                app.stdin.write('quit\n')
                app.stdin.flush()
                app.wait(timeout=10)
            subprocess.run([env['WINESERVER'], '-k'], env=env, check=True)
            subprocess.run([env['WINESERVER'], '-w'], env=env, check=True, timeout=10)
report['passed'] = ('error' not in report and len(report['phases']) == 3 and
                    report.get('surface_reused', False) and all(phase['passed'] for phase in report['phases']))
(qa / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(qa / 'result.json')
print(json.dumps(report))
raise SystemExit(0 if report['passed'] else 1)
