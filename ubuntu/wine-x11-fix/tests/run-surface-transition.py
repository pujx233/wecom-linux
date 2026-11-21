#!/usr/bin/env python3
"""Preserve valid pixels when foreign child reparenting changes the drawing backend."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime', required=True, type=Path)
parser.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
runtime, output = args.runtime.resolve(strict=True), args.output.resolve()
output.mkdir(parents=True, exist_ok=False)
(output / '.wecom-frame-qa').touch()
(output / 'wine').symlink_to(runtime)
os.environ['WECOM_QA_ROOT'] = str(output)
sys.path.insert(0, str(Path(__file__).resolve().parent / 'frame-composition'))
from isolated import desktop

report = dict(host_desktop_used=False, account_used=False, cases=[],
              module_sha256=hashlib.sha256((runtime / 'lib/wine/x86_64-unix/win32u.so').read_bytes()).hexdigest())
executables = {}
for bits, compiler in [('32', 'i686-w64-mingw32-gcc'), ('64', 'x86_64-w64-mingw32-gcc')]:
    executable = output / ('surface-' + bits + '.exe')
    subprocess.run([compiler, '-O2', '-Wall', '-Wextra', '-Werror',
                    str(Path(__file__).with_name('surface-transition.c')), '-o', str(executable),
                    '-lgdi32', '-luser32'], check=True)
    executables[bits] = executable

with desktop(output, bare=True) as env:
    env.update(WINEPREFIX=str(output / 'prefix'), WINESERVER=str(runtime / 'bin/wineserver'),
               WINEDEBUG='-all', WINE_X11_OWNED_FRAME='1')
    for dpi in (96, 192):
        subprocess.run([str(runtime / 'bin/wine'), 'reg', 'add', r'HKCU\Control Panel\Desktop',
                        '/v', 'LogPixels', '/t', 'REG_DWORD', '/d', str(dpi), '/f'],
                       env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        subprocess.run([env['WINESERVER'], '-k'], env=env, check=True)
        subprocess.run([env['WINESERVER'], '-w'], env=env, check=True, timeout=10)
        for bits, executable in executables.items():
            for awareness in (('aware',) if dpi == 96 else ('aware', 'unaware')):
                result = subprocess.run([str(runtime / 'bin/wine'), str(executable), awareness],
                                         env=env, capture_output=True, text=True, timeout=25)
                name = f'{bits}-{dpi}-{awareness}'
                (output / (name + '.log')).write_text(result.stdout + result.stderr)
                match = re.search(r'RESULT bits=(\d+) checks=(\d+) failures=(\d+)', result.stdout)
                passed = (result.returncode == 0 and match is not None and
                          tuple(map(int, match.groups())) == (int(bits), 162, 0))
                report['cases'].append(dict(bits=int(bits), dpi=dpi, awareness=awareness,
                                           exit_code=result.returncode, passed=passed))
report['passed'] = len(report['cases']) == 6 and all(row['passed'] for row in report['cases'])
(output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
assert report['passed'], report
print('PASS: 972 pixel checks across drawing backend transitions, shapes, 32/64-bit and DPI awareness')
