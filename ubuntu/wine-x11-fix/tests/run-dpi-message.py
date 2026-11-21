#!/usr/bin/env python3
"""Check the input rectangle and synchronous delivery of DPI messages across Wine processes."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'frame-composition'))
from isolated import desktop

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
output = args.output.resolve()
output.mkdir(parents=True, exist_ok=False)
(output / '.wecom-frame-qa').touch()
(output / 'wine').symlink_to(args.runtime.resolve(strict=True))
os.environ['WECOM_QA_ROOT'] = str(output)
executables = []
for architecture in ('i686', 'x86_64'):
    exe = output / (architecture + '-dpi-message.exe')
    subprocess.run([architecture + '-w64-mingw32-gcc', '-O2', '-Wall', '-Wextra', '-Werror', '-municode',
                    HERE / 'dpi-message.c', '-o', exe, '-luser32'], check=True)
    executables.append(exe)
with desktop(output, bare=True) as env:
    env.update(WINEPREFIX=str(output / 'prefix'), WINESERVER=str(output / 'wine/bin/wineserver'), WINEDEBUG='-all')
    for sender in executables:
        for receiver in executables:
            subprocess.run([output / 'wine/bin/wine', sender, receiver], env=env, check=True, timeout=30)
print('PASS: DPI message input rectangle and asynchronous rejection in all four architecture combinations')
