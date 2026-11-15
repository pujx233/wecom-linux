#!/usr/bin/env python3
"""Check shadow ownership and SHOW handling through real Wine windows on a private Xvfb."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime', type=Path, required=True)
parser.add_argument('--candidate', type=Path, required=True)
parser.add_argument('--baseline', type=Path)
parser.add_argument('--fixture', type=Path, help='Use an already compiled policy.c executable')
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
runtime, output = args.runtime.resolve(), args.output.resolve()
output.mkdir(parents=True, exist_ok=False)
(output / 'runtime').mkdir(mode=0o700)
(output / 'home').mkdir()
env = os.environ.copy()
for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS', 'WINEARCH', 'WINEDLLPATH', 'LD_PRELOAD',
            'WINELOADER', 'WINELOADERNOEXEC', 'WINESERVERSOCKET', 'PULSE_SERVER', 'PIPEWIRE_REMOTE'):
    env.pop(key, None)
env.update(WINEPREFIX=str(output / 'prefix'), WINESERVER=str(runtime / 'bin/wineserver'), WINEDEBUG='-all',
           XDG_RUNTIME_DIR=str(output / 'runtime'), XAUTHORITY=str(output / 'Xauthority'),
           HOME=str(output / 'home'), XDG_CONFIG_HOME=str(output / 'home/config'),
           XDG_DATA_HOME=str(output / 'home/data'), XDG_CACHE_HOME=str(output / 'home/cache'),
           WINE_X11_FRAME_ATTACHED_CLASSES='PerryShadowWnd;TitleBarWindow',
           WINE_X11_FRAME_DECORATION_CLASSES='PerryShadowWnd', WINE_WECOM_SHADOW_STACK='1',
           WINE_WECOM_FIRST_PRESENT_ARGB='1', WINE_X11_FIXED_TRANSIENT_ARGB='1',
           WINE_X11_FIXED_TRANSIENT_UTILITY='1',
           WINEDLLOVERRIDES='winewayland.drv=d;mscoree,mshtml,winemenubuilder=')
wine = str(runtime / 'bin/wine')
fixture = output / 'policy.exe'
if args.fixture:
    shutil.copy2(args.fixture, fixture)
else:
    subprocess.run(['i686-w64-mingw32-gcc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2',
                    str(Path(__file__).with_name('policy.c')), '-o', str(fixture), '-luser32'], check=True)
report = {'host_desktop_used': False, 'account_used': False, 'mock_wine_apis': False, 'cases': [], 'passed': False}
report['runtime_sha256'] = {name: hashlib.sha256((runtime / path).read_bytes()).hexdigest() for name, path in (
    ('wineserver', 'bin/wineserver'), ('win32u.so', 'lib/wine/x86_64-unix/win32u.so'),
    ('winex11.so', 'lib/wine/x86_64-unix/winex11.so'))}
report['fixture_sha256'] = hashlib.sha256(fixture.read_bytes()).hexdigest()
server = None
try:
    number = next(i for i in range(80, 200) if not Path(f'/tmp/.X11-unix/X{i}').exists()
                  and not Path(f'/tmp/.X{i}-lock').exists())
    env['DISPLAY'] = f':{number}'
    Path(env['XAUTHORITY']).touch(mode=0o600)
    subprocess.run(['xauth', '-f', env['XAUTHORITY'], 'add', env['DISPLAY'], '.', secrets.token_hex(16)],
                   check=True, capture_output=True)
    with (output / 'Xvfb.log').open('w') as log:
        server = subprocess.Popen(['Xvfb', env['DISPLAY'], '-screen', '0', '1280x800x24', '-nolisten', 'tcp',
                                   '-auth', env['XAUTHORITY']], env=env, stdout=log, stderr=log)
    deadline = time.monotonic() + 10
    while subprocess.run(['xwininfo', '-root'], env=env, capture_output=True).returncode:
        assert server.poll() is None
        assert time.monotonic() < deadline, 'Private Xvfb startup timed out'
        time.sleep(.05)
    with (output / 'wineboot.log').open('w') as log:
        subprocess.run([wine, 'wineboot', '-u'], env=env, stdout=log, stderr=log, check=True, timeout=90)
    versions = [('candidate', args.candidate.resolve(), 'fixed')]
    if args.baseline:
        versions.insert(0, ('baseline', args.baseline.resolve(), 'baseline'))
    for name, helper, expectation in versions:
        helper_path = subprocess.check_output([wine, 'winepath', '-w', str(helper)], env=env, text=True).strip()
        for native in ('0', '1'):
            result = subprocess.run([wine, str(fixture), helper_path, expectation],
                                    env=env | {'WINE_X11_OWNED_FRAME': native},
                                    capture_output=True, text=True, timeout=40)
            log_name = name + '-frame-' + native + '.log'
            (output / log_name).write_text(result.stdout + result.stderr)
            events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
            report['cases'].append({'helper': name, 'sha256': hashlib.sha256(helper.read_bytes()).hexdigest(),
                                    'native_frames': native, 'events': events, 'log': log_name,
                                    'exit_code': result.returncode, 'passed': result.returncode == 0})
    report['passed'] = bool(report['cases']) and all(case['passed'] for case in report['cases'])
except Exception as error:
    report['error'] = type(error).__name__ + ': ' + str(error)
finally:
    subprocess.run([env['WINESERVER'], '-k'], env=env, capture_output=True, timeout=10)
    subprocess.run([env['WINESERVER'], '-w'], env=env, capture_output=True, timeout=10)
    if server and server.poll() is None:
        server.terminate()
        server.wait(timeout=10)
    (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
raise SystemExit(0 if report['passed'] else 1)
