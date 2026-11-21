#!/usr/bin/env python3
"""Check deferred callback delivery, FIFO, reentrancy and IC destruction in the packaged Xlib."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).parent / 'frame-composition'))
from isolated import desktop

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime', type=Path, required=True)
parser.add_argument('--source', type=Path, required=True, help='Matching private libX11 source')
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
runtime, source, qa = args.runtime.resolve(), args.source.resolve(), args.output.resolve()
qa.mkdir(parents=True, exist_ok=False)
(qa / '.wecom-frame-qa').touch()
(qa / 'wine').symlink_to(runtime)
os.environ['WECOM_QA_ROOT'] = str(qa)
library = runtime / 'lib/libX11.so.6'
if source.is_file():
    with subprocess.Popen(['zstd', '-dc', str(source)], stdout=subprocess.PIPE) as process:
        with tarfile.open(mode='r|', fileobj=process.stdout) as archive:
            archive.extractall(qa / 'source', filter='data')
        assert process.wait() == 0
    source = qa / 'source/libX11-1.8.13'
executable = qa / 'xim-callbacks'
subprocess.run(['gcc', '-D_GNU_SOURCE', '-O2', '-Wall', '-Wextra', '-Werror',
                '-I' + str(source / 'src/xlibi18n'), '-I' + str(source / 'include'),
                str(Path(__file__).with_name('xim-callbacks.c')), '-o', str(executable),
                '-L' + str(library.parent), '-Wl,-rpath,' + str(library.parent), '-l:libX11.so.6', '-ldl'],
               check=True)
with desktop(qa, bare=True, boot_wine=False) as env:
    env.update(XMODIFIERS='@im=ibus', LANG='zh_CN.UTF-8', LC_CTYPE='zh_CN.UTF-8',
               IBUS_ADDRESS='unix:abstract=wecom-callbacks-' + str(os.getpid()))
    with (qa / 'ibus.log').open('w') as log:
        daemon = subprocess.Popen(['ibus-daemon', '--single', '--xim', '--emoji-extension=disable',
                                    '--cache=none', '--address=' + env['IBUS_ADDRESS']],
                                   env=env, stdout=log, stderr=log)
        try:
            result = subprocess.run([str(executable)], env=env, capture_output=True, text=True, timeout=60)
        finally:
            daemon.terminate()
            daemon.wait(timeout=8)
report = dict(account_used=False, host_desktop_used=False,
              libx11_sha256=hashlib.sha256(library.read_bytes()).hexdigest(), exit_code=result.returncode,
              stdout=result.stdout, stderr=result.stderr,
              passed=result.returncode == 0 and 'repeats=80 operations=6' in result.stdout
              and 'LIBRARY ' + str(library) in result.stdout)
(qa / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
raise SystemExit(0 if report['passed'] else 1)
