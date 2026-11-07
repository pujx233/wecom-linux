#!/usr/bin/env python3
"""Exercise the existing GDI+ resampling fixture with both Windows architectures."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime', required=True, type=Path)
parser.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
wine, output = args.runtime.resolve(strict=True), args.output.resolve()
output.mkdir(parents=True, exist_ok=False)
(output / '.wecom-frame-qa').touch()
(output / 'wine').symlink_to(wine)
os.environ['WECOM_QA_ROOT'] = str(output)
sys.path.insert(0, str(Path(__file__).resolve().parent / 'frame-composition'))
from isolated import desktop

source = Path(__file__).with_name('gdiplus-render-check.cpp')
report = {'host_desktop_used': False, 'account_used': False, 'architectures': [],
          'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
with desktop(output, bare=True) as env:
    env.update(WINEPREFIX=str(output / 'prefix'), WINESERVER=str(wine / 'bin/wineserver'), WINEDEBUG='-all')
    try:
        for bits, compiler, architecture in [('32', 'i686-w64-mingw32-g++', 'i386-windows'),
                                             ('64', 'x86_64-w64-mingw32-g++', 'x86_64-windows')]:
            executable = output / ('gdiplus-' + bits + '.exe')
            subprocess.run([compiler, '-O2', '-static', str(source), '-o', str(executable),
                            '-lgdiplus', '-lgdi32', '-lole32', '-luuid'], check=True)
            pixels = output / ('pixels-' + bits + '.bin')
            result = subprocess.run([str(wine / 'bin/wine'), str(executable),
                                     'Z:' + str(pixels).replace('/', '\\')],
                                    env=env, capture_output=True, text=True, timeout=120)
            (output / (bits + '.log')).write_text(result.stdout + result.stderr)
            result.check_returncode()
            data = pixels.read_bytes()
            stride = 179 * 151 * 4
            point = (20 * 179 + 20) * 4
            assert 'cases=144' in result.stdout and len(data) == 144 * stride
            background = data[:4]
            assert background[3] == 0x73
            assert all(data[offset:offset + 4] == background for offset in range(0, len(data), stride))
            assert all(data[offset + point:offset + point + 4] != background
                       for offset in range(0, len(data), stride))
            module = wine / 'lib/wine' / architecture / 'gdiplus.dll'
            report['architectures'].append({'bits': bits, 'cases': 144, 'passed': True,
                                             'module_sha256': hashlib.sha256(module.read_bytes()).hexdigest(),
                                             'pixels_sha256': hashlib.sha256(data).hexdigest(),
                                             'timing': result.stdout.strip().splitlines()[-1]})
    finally:
        for option in ('-k', '-w'):
            subprocess.run([str(wine / 'bin/wineserver'), option], env=env, timeout=15, check=True)
report['passed'] = len(report['architectures']) == 2
(output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
