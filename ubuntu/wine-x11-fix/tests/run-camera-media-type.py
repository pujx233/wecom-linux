#!/usr/bin/env python3
"""Exercise DirectShow format enumeration on available cameras in both Windows architectures."""
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

source = Path(__file__).with_name('camera-media-type.c')
report = dict(host_desktop_used=False, account_used=False, frames_recorded=False, architectures=[],
              module_sha256=hashlib.sha256((runtime / 'lib/wine/x86_64-unix/qcap.so').read_bytes()).hexdigest())
with desktop(output, bare=True) as env:
    env.update(WINEPREFIX=str(output / 'prefix'), WINESERVER=str(runtime / 'bin/wineserver'), WINEDEBUG='-all')
    for bits, compiler in [('32', 'i686-w64-mingw32-gcc'), ('64', 'x86_64-w64-mingw32-gcc')]:
        executable = output / ('camera-' + bits + '.exe')
        subprocess.run([compiler, '-O2', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(executable),
                        '-lole32', '-lstrmiids', '-luuid'], check=True)
        try:
            result = subprocess.run([str(runtime / 'bin/wine'), str(executable)], env=env,
                                     capture_output=True, text=True, timeout=45)
            (output / (bits + '.log')).write_text(result.stdout + result.stderr)
            match = re.search(r'RESULT bits=(\d+) opened=(\d+) formats=(\d+) failures=(\d+)', result.stdout)
            row = dict(bits=int(bits), exit_code=result.returncode, passed=False)
            if match:
                actual_bits, opened, formats, failures = map(int, match.groups())
                row.update(opened=opened, formats=formats, failures=failures,
                           passed=result.returncode == 0 and actual_bits == int(bits) and opened > 0 and formats > 0
                           and failures == 0)
        except subprocess.TimeoutExpired as error:
            (output / (bits + '.log')).write_bytes((error.stdout or b'') + (error.stderr or b''))
            row = dict(bits=int(bits), passed=False, timeout=True)
        report['architectures'].append(row)
report['passed'] = all(row['passed'] for row in report['architectures'])
(output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
assert report['passed'], report
print('PASS: 32/64-bit DirectShow GetFormat, GetStreamCaps and EnumMediaTypes')
