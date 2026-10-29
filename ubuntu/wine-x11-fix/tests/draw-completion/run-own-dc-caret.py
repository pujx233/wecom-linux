#!/usr/bin/env python3
"""Observe pending and completed frames around nested CS_OWNDC caret and erase operations."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from PIL import Image

GREEN, BLUE, ERASE_RED = (48, 176, 96), (64, 96, 192), (192, 64, 48)

here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parent / 'frame-composition'))
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
fixture = qa / 'own-dc-caret.exe'
subprocess.run(['x86_64-w64-mingw32-gcc', '-O2', '-Wall', '-Wextra', str(here / 'own-dc-caret.c'),
                '-o', str(fixture), '-lgdi32', '-luser32'], check=True)
report = {'host_desktop_used': False, 'account_data_used': False, 'cases': [],
          'dc_release_checks': [], 'runtime_sha256': {}}
report['test_sha256'] = {name: hashlib.sha256((here / name).read_bytes()).hexdigest()
                         for name in ('own-dc-caret.c', 'run-own-dc-caret.py')}
for name in ('win32u.so', 'winex11.so'):
    report['runtime_sha256'][name] = hashlib.sha256(
        (qa / 'wine/lib/wine/x86_64-unix' / name).read_bytes()).hexdigest()
with desktop(qa) as env:
    env.update(WINEPREFIX=str(qa / 'prefix'), WINESERVER=str(qa / 'wine/bin/wineserver'),
               WINEDEBUG='-all,+x11drv', WECOM_DC_FIXTURE='1', WINE_X11_OWNED_FRAME='1',
               WINE_WECOM_FIRST_PRESENT_ARGB='1', WINE_X11_FIXED_TRANSIENT_ARGB='1',
               WINE_X11_FIXED_TRANSIENT_UTILITY='1',
               WINEDLLOVERRIDES='winewayland.drv=d;mscoree,mshtml,winemenubuilder=')
    with (qa / 'wine.log').open('w') as log, recording(qa, env, 'own-dc') as capture:
        app = subprocess.Popen([str(qa / 'wine/bin/wine'), str(fixture)], env=env,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True, bufsize=1)
        messages = queue.Queue()
        def read():
            for line in app.stdout:
                messages.put(json.loads(line))
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        def command(value):
            app.stdin.write(value + '\n')
            app.stdin.flush()
            result = messages.get(timeout=15)
            assert result['phase'] == value, result
            return result
        def sample(case, phase, point, expected):
            pixels = []
            # A held DC has no general Win32 presentation boundary; None records observations only.
            for index in range(3):
                time.sleep(.15)
                path = qa / f'{case}-{phase}-{index}.png'
                capture(path)
                pixels.append(Image.open(path).convert('RGB').getpixel(tuple(point)))
            return {'phase': phase, 'point': point, 'pixels': pixels, 'expected': expected,
                    'passed': None if expected is None else all(pixel == expected for pixel in pixels)}
        try:
            for case in ('precreated', 'created-during', 'caret-only', 'readback-only',
                         'erase-now', 'erase-now-only', 'erase-paint', 'erase-paint-only',
                         'erase-rebind-cache', 'erase-rebind-class'):
                reset = ('reset-class' if case.endswith('-class') else
                         'reset-cache' if case.endswith('-cache') else 'reset')
                ready = command(reset)
                path = qa / f'{case}-initial.png'
                time.sleep(.25)
                capture(path)
                initial = Image.open(path).convert('RGB').getpixel(tuple(ready['point']))
                assert initial == GREEN, (case, initial)
                checks = []
                if case.startswith('erase-rebind-'):
                    prepared = command(case.replace('erase-', 'prepare-', 1))
                    checks.append(sample(case, 'prepared', prepared['point'], GREEN))
                staged = command(case)
                if case.startswith('erase-'):
                    assert staged['erase_calls'] == 1 and staged['erase_dc_matches'], staged
                    assert staged['erase_drawn'] == case.startswith('erase-paint'), staged
                if case.endswith(('-cache', '-class')):
                    assert staged['same_dc_reused'], staged
                checks.append(sample(case, 'held', staged['point'], None))
                released = command('release')
                draws = case in ('precreated', 'created-during', 'erase-now', 'erase-paint',
                                 'erase-rebind-cache', 'erase-rebind-class')
                if case == 'erase-paint-only':
                    checks.append(sample(case, 'released', released['erase_point'], ERASE_RED))
                else:
                    checks.append(sample(case, 'released', released['point'], BLUE if draws else GREEN))
                completed = command('complete')
                checks.append(sample(case, 'completed', completed['point'], BLUE))
                passed = all(check['passed'] for check in checks if check['expected'] is not None)
                report['cases'].append({'name': case, 'erase_calls': staged['erase_calls'],
                                        'erase_dc_matches': staged['erase_dc_matches'],
                                        'erase_drawn': staged['erase_drawn'],
                                        'same_dc_reused': staged['same_dc_reused'], 'checks': checks,
                                        'passed': passed})
            for case in ('update-rect-full', 'update-rect-short', 'update-rgn-full', 'update-rgn-short'):
                command('reset-cache')
                result = command(case)
                report['dc_release_checks'].append({'name': case, 'erase_calls': result['erase_calls'],
                    'erase_dc_released': result['erase_dc_released'],
                    'passed': result['erase_calls'] == 1 and result['erase_dc_released']})
        finally:
            if app.poll() is None:
                app.stdin.write('quit\n')
                app.stdin.flush()
                app.wait(timeout=10)
            subprocess.run([env['WINESERVER'], '-k'], env=env, check=True)
            subprocess.run([env['WINESERVER'], '-w'], env=env, check=True, timeout=10)
report['passed'] = all(case['passed'] for case in report['cases'] + report['dc_release_checks'])
path = qa / 'result.json'
path.write_text(json.dumps(report, indent=2) + '\n')
print(path)
print(json.dumps(report))
raise SystemExit(0 if report['passed'] else 1)
