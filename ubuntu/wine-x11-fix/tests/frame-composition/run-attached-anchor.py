#!/usr/bin/env python3
"""Compare attached layer updates before and after the owner's Win32 position commit."""
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

tests = Path(__file__).resolve().parent
from isolated import desktop

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
qa = args.output.resolve()
qa.mkdir(parents=True, exist_ok=False)
(qa / '.wecom-frame-qa').touch()
(qa / 'wine').symlink_to(args.runtime.resolve(), target_is_directory=True)
os.environ['WECOM_QA_ROOT'] = str(qa)
source = Path(__file__).with_name('attached-anchor.c')
fixture = qa / 'attached-anchor.exe'
subprocess.run(['x86_64-w64-mingw32-gcc', '-O2', '-Wall', '-Wextra', '-Werror', str(source),
                '-o', str(fixture), '-lgdi32', '-luser32'], check=True)
report = {'host_desktop_used': False, 'account_data_used': False, 'cases': {}, 'passed': False,
          'runtime_sha256': {name: hashlib.sha256((qa / 'wine/lib/wine/x86_64-unix' / name).read_bytes()).hexdigest()
                             for name in ('win32u.so', 'winex11.so')},
          'test_sha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in (source, Path(__file__), tests / 'isolated.py')}}

with desktop(qa) as env:
    env.update(WINEPREFIX=str(qa / 'prefix'), WINESERVER=str(qa / 'wine/bin/wineserver'),
               WINEDEBUG='-all,+x11drv', WINE_X11_OWNED_FRAME='1', WECOM_ANCHOR_ORDER_FIXTURE='1',
               WINE_X11_FRAME_ATTACHED_CLASSES='AnchorOrderShadow;AnchorOrderTitle',
               WINE_X11_FRAME_DECORATION_CLASSES='AnchorOrderShadow',
               WINEDLLOVERRIDES='winewayland.drv=d;mscoree,mshtml,winemenubuilder=')

    def geometry(xid):
        output = subprocess.run(['xwininfo', '-stats', '-id', str(xid)], env=env,
                                capture_output=True, text=True, check=True, timeout=2).stdout
        values = [int(re.search(pattern, output)[1]) for pattern in
                  (r'Absolute upper-left X:\s+(-?\d+)', r'Absolute upper-left Y:\s+(-?\d+)',
                   r'Relative upper-left X:\s+(-?\d+)', r'Relative upper-left Y:\s+(-?\d+)',
                   r'Width:\s+(\d+)', r'Height:\s+(\d+)')]
        return {'absolute': values[:2], 'relative': values[2:4], 'size': values[4:]}

    def snapshot(state):
        return {role: geometry(state[role]) for role in ('frame', 'body', 'shadow', 'title', 'popup')
                if state.get(role)}

    x = C.CDLL('libX11.so.6')
    x.XOpenDisplay.argtypes = [C.c_char_p]
    x.XOpenDisplay.restype = C.c_void_p
    x.XCloseDisplay.argtypes = [C.c_void_p]
    x.XMoveWindow.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.c_int]
    x.XDefaultRootWindow.argtypes = [C.c_void_p]
    x.XDefaultRootWindow.restype = C.c_ulong
    x.XWarpPointer.argtypes = [C.c_void_p, C.c_ulong, C.c_ulong, C.c_int, C.c_int,
                              C.c_uint, C.c_uint, C.c_int, C.c_int]
    x.XSync.argtypes = [C.c_void_p, C.c_int]
    saved = os.environ.get('XAUTHORITY')
    os.environ['XAUTHORITY'] = env['XAUTHORITY']
    display = x.XOpenDisplay(env['DISPLAY'].encode())
    if saved is None:
        os.environ.pop('XAUTHORITY')
    else:
        os.environ['XAUTHORITY'] = saved
    assert display

    for mode in ('before', 'after', 'native', 'popup'):
        case = report['cases'][mode] = {'events': [], 'passed': False}
        with (qa / (mode + '.log')).open('w') as log:
            app = subprocess.Popen([str(qa / 'wine/bin/wine'), str(fixture), mode], env=env,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                                   text=True, bufsize=1)
            replies = queue.Queue()

            def read(process=app, target=replies):
                for line in process.stdout:
                    target.put(json.loads(line))
                target.put(None)

            threading.Thread(target=read, daemon=True).start()

            def send(value):
                app.stdin.write(value + '\n')
                app.stdin.flush()

            def wait(phase):
                event = replies.get(timeout=10)
                assert event and event['phase'] == phase, event
                case['events'].append(event)
                return event

            try:
                state = wait('ready')
                assert state['frame'] == state['shadow_frame'] == state['title_frame'], state
                case['initial'] = snapshot(state)
                assert case['initial']['frame']['size'] == [392, 312], case['initial']
                assert case['initial']['body']['relative'] == [36, 36], case['initial']
                if mode in ('before', 'after'):
                    send('move')
                    state = wait('callback')
                    case['inside_callback'] = snapshot(state)
                    send('continue')
                    state = wait('move')
                    case['after_commit'] = snapshot(state)
                    expected_owner = [500, 300, 820, 540]
                else:
                    send('move-owner')
                    state = wait('move-owner')
                    assert state['owner_rect'] == [500, 300, 820, 540], state
                    previous = geometry(state['frame'])
                    target = [previous['absolute'][0] + 200, previous['absolute'][1] + 100]
                    x.XMoveWindow(display, state['frame'], *target)
                    x.XSync(display, 0)
                    deadline = time.monotonic() + 3
                    while geometry(state['frame'])['absolute'] != target:
                        assert time.monotonic() < deadline, 'private WM did not apply external move'
                        time.sleep(.01)
                    case['native_ahead'] = snapshot(state)
                    if mode == 'native':
                        send('native-follow')
                        state = wait('native-follow')
                        assert state['owner_rect'] == [500, 300, 820, 540], state
                        case['staged'] = snapshot(state)
                    else:
                        x.XWarpPointer(display, 0, x.XDefaultRootWindow(display), 0, 0, 0, 0, 900, 700)
                        x.XSync(display, 0)
                        send('popup')
                        state = wait('popup')
                        assert state['cursor'] == [900, 700], state
                        assert state['popup_frame'] != state['frame'], state
                    expected_owner = [700, 400, 1020, 640]
                send('dispatch')
                state = wait('dispatch')
                case['settled'] = snapshot(state)
                final = case['settled']
                body_position = expected_owner[:2]
                case['passed'] = (state['owner_rect'] == expected_owner and
                                  final['frame']['size'] == [392, 312] and
                                  final['body']['relative'] == [36, 36] and
                                  final['body']['absolute'] == body_position and
                                  final['shadow']['absolute'] == [body_position[0] - 36, body_position[1] - 36] and
                                  final['title']['absolute'] == body_position)
                if mode == 'popup':
                    case['passed'] &= final['popup']['absolute'] == [900, 700]
            except Exception as error:
                case['error'] = str(error) or type(error).__name__
            finally:
                if app.poll() is None:
                    try:
                        send('quit')
                        app.wait(timeout=3)
                    except (BrokenPipeError, subprocess.TimeoutExpired):
                        app.kill()
                        app.wait(timeout=3)
                case['exit_code'] = app.returncode
                case['passed'] &= app.returncode == 0
        (qa / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    x.XCloseDisplay(display)
    subprocess.run([env['WINESERVER'], '-k'], env=env, check=True, timeout=10)
    subprocess.run([env['WINESERVER'], '-w'], env=env, check=True, timeout=10)
report['passed'] = all(case['passed'] for case in report['cases'].values())
(qa / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'report': str(qa / 'result.json'), 'passed': report['passed'],
                  'cases': {mode: {'passed': case['passed'], 'error': case.get('error'),
                                   'settled': case.get('settled')} for mode, case in report['cases'].items()}}))
raise SystemExit(0 if report['passed'] else 1)
