#!/usr/bin/env python3
"""Exercise mouse coalescing while an earlier message is being delivered."""
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
sys.path.insert(0, str(Path(__file__).with_name('frame-composition')))
from isolated import desktop

with desktop(output, bare=True) as env:
    env.update(WINEPREFIX=str(output / 'prefix'), WINEDEBUG='-all')
    for compiler, bits in [('i686-w64-mingw32-gcc', '32'), ('x86_64-w64-mingw32-gcc', '64')]:
        executable = output / f'mouse-queue-{bits}.exe'
        subprocess.run([compiler, '-O2', '-Wall', '-Wextra', '-Werror',
                        str(Path(__file__).with_name('mouse-queue.c')), '-o', executable, '-luser32'], check=True)
        subprocess.run([runtime / 'bin/wine', executable], env=env, check=True, timeout=75)
