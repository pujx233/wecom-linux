#!/usr/bin/env python3
"""Check that early GUI windows use the selected DPI without setting the process default."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
runtime, output = args.runtime.resolve(strict=True), args.output.resolve()
output.mkdir(parents=True, exist_ok=False)
(output / '.wecom-frame-qa').touch()
(output / 'wine').symlink_to(runtime)
os.environ['WECOM_QA_ROOT'] = str(output)
sys.path.insert(0, str(Path(__file__).resolve().parent / 'frame-composition'))
from isolated import desktop

cases = [('default', ()), ('early', ('wineInitialThreadDpiAwareness',)),
         ('legacy', ('wineInitialThreadDpiAwareness', 'dpiAwareness'))]
with desktop(output, bare=True) as env:
    env.update(WINEPREFIX=str(output / 'prefix'), WINESERVER=str(runtime / 'bin/wineserver'), WINEDEBUG='-all')
    wine = runtime / 'bin/wine'
    for compiler, bits in [('i686-w64-mingw32-gcc', '32'), ('x86_64-w64-mingw32-gcc', '64')]:
        for mode, values in cases:
            name = f'initial-thread-dpi-{bits}-{mode}.exe'
            exe = output / name
            subprocess.run([compiler, '-O2', '-Wall', '-Wextra', '-Werror',
                            str(Path(__file__).with_name('initial-thread-dpi.c')), '-o', exe, '-luser32', '-lshcore'],
                           check=True)
            key = r'HKLM\Software\Microsoft\Windows NT\CurrentVersion\Image File Execution Options' + '\\' + name
            for value in values:
                data = '0' if value == 'dpiAwareness' else '3'
                subprocess.run([wine, 'reg', 'add', key, '/v', value, '/t', 'REG_DWORD', '/d', data,
                                '/f', '/reg:' + bits], env=env, check=True, timeout=15)
            subprocess.run([wine, exe, mode], env=env, check=True, timeout=15)
print('PASS: initial thread, process default and window callback DPI in both Wine architectures')
