"""Check declared decoration roles and independent topmost semantics on a private desktop."""
from datetime import datetime, timezone
import argparse
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
parser.add_argument('--zero-size-only', action='store_true')
args = parser.parse_args()
qa = Path(os.environ['WECOM_QA_ROOT']).resolve()
assert not (qa / 'no-system-bus').exists()
name = 'frame-roles-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
subprocess.run(['x86_64-w64-mingw32-gcc', '-O2', '-Wall', '-Wextra',
                str(Path(__file__).with_name('frame-roles.c')), '-o', str(qa / 'frame-roles.exe'),
                '-lgdi32', '-luser32'], check=True)
report = {'host_desktop_used': False, 'account_data_used': False, 'cases': [], 'runtime': {}}
for module in ('winex11.so', 'win32u.so'):
    report['runtime'][module] = hashlib.sha256((qa / 'wine/lib/wine/x86_64-unix' / module).read_bytes()).hexdigest()
with desktop(qa) as env:
    env.update(WINEPREFIX=str(qa / 'prefix'), WINESERVER=str(qa / 'wine/bin/wineserver'),
               DBUS_SYSTEM_BUS_ADDRESS='unix:path=' + str(qa / 'no-system-bus'),
               WINEDEBUG='-all,+x11drv', WINE_X11_OWNED_FRAME='1',
               WINE_X11_FRAME_DECORATION_CLASSES='OtherDecoration;FrameRoleDecoration',
               WINE_WECOM_FIRST_PRESENT_ARGB='1', WINE_X11_FIXED_TRANSIENT_ARGB='1',
               WINE_X11_FIXED_TRANSIENT_UTILITY='1',
               WINEDLLOVERRIDES='winewayland.drv=d;mscoree,mshtml,winemenubuilder=')
    with recording(qa, env, name) as capture, (qa / (name + '.log')).open('w') as log:
        app = subprocess.Popen([str(qa / 'wine/bin/wine'), str(qa / 'frame-roles.exe')], env=env,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True)
        lines = queue.Queue()
        def read():
            for line in app.stdout:
                lines.put(json.loads(line))
        threading.Thread(target=read, daemon=True).start()
        def command(value):
            app.stdin.write(value + '\n'); app.stdin.flush()
        try:
            assert lines.get(timeout=15)['ready']
            time.sleep(.5)
            steps = [('content', ['content'], (0, 0, 255), True),
                     ('decoration', ['decoration'], (255, 255, 255), True),
                     ('initial-topmost', ['topmost', 'peer'], (0, 0, 255), False),
                     ('normal-content', ['plain'], (0, 0, 255), True),
                     ('promoted-topmost', ['promote', 'peer'], (0, 0, 255), False),
                     ('demoted-content', ['normal', 'peer'], (255, 0, 0), True)]
            if args.zero_size_only:
                steps = []
            for label, commands, expected, grouped in steps:
                for value in commands:
                    command(value); time.sleep(.25)
                target = qa / (name + '-' + label + '.png')
                deadline = time.monotonic() + 3
                while True:
                    command('state'); state = lines.get(timeout=5)
                    capture(target)
                    pixel = Image.open(target).convert('RGB').getpixel((500, 400))
                    passed = pixel == expected and (state['frame'] == state['owner_frame']) == grouped
                    if passed or time.monotonic() > deadline: break
                    time.sleep(.1)
                report['cases'].append(dict(name=label, expected=expected, pixel=pixel, grouped=grouped,
                                             state=state, passed=passed))
            for label, value, grouped, size in [('zero-owned', 'zero', True, 0),
                                                ('zero-promoted', 'promote', False, 0),
                                                ('zero-demoted', 'normal', True, 0),
                                                ('zero-restored', 'resize', True, 200)]:
                command(value)
                time.sleep(.25)
                command('state')
                state = lines.get(timeout=5)
                native = {}
                for role in ('frame', 'body'):
                    geometry = subprocess.run(['xwininfo', '-id', str(state[role])], env=env,
                                              text=True, capture_output=True, check=True).stdout
                    native[role] = [int(re.search(r'Width:\s+(\d+)', geometry)[1]),
                                    int(re.search(r'Height:\s+(\d+)', geometry)[1])]
                width, height = native['frame']
                passed = (state['width'] == size and state['height'] == size and
                          (state['frame'] == state['owner_frame']) == grouped and
                          1 <= width <= 65535 and 1 <= height <= 65535 and
                          native['body'] == [max(1, size), max(1, size)])
                if not grouped:
                    passed = passed and (width, height) == (1, 1)
                case = dict(name=label, state=state, native_size=native, passed=passed)
                if size:
                    target = qa / (name + '-' + label + '.png')
                    capture(target)
                    case['pixel'] = Image.open(target).convert('RGB').getpixel((500, 400))
                    case['passed'] = passed and case['pixel'] == (0, 0, 255)
                report['cases'].append(case)
        except Exception as error:
            report['error'] = str(error) or type(error).__name__
            report['app_exit_code'] = app.poll()
        finally:
            if app.poll() is None:
                command('quit'); app.wait(timeout=10)
            try:
                app.stdin.close()
            except BrokenPipeError:
                pass
            subprocess.run([env['WINESERVER'], '-k'], env=env)
            subprocess.run([env['WINESERVER'], '-w'], env=env, check=True, timeout=10)
report['passed'] = bool(report['cases']) and 'error' not in report and all(case['passed'] for case in report['cases'])
path = qa / (name + '.json')
path.write_text(json.dumps(report, indent=2) + '\n')
print(path); print(json.dumps(report))
raise SystemExit(0 if report['passed'] else 1)
