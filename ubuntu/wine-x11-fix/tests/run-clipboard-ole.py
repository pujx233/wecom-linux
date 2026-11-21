#!/usr/bin/env python3
"""Check delayed bitmaps and the OLE clipboard wire data across both Windows architectures."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).parent / 'frame-composition'))
from isolated import desktop

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
qa = args.output.resolve()
qa.mkdir(parents=True, exist_ok=False)
(qa / '.wecom-frame-qa').touch()
runtime = args.runtime.resolve()
(qa / 'wine').symlink_to(runtime)
os.environ['WECOM_QA_ROOT'] = str(qa)
source = Path(__file__).with_name('clipboard-ole.c')
for bits, compiler in [('32', 'i686-w64-mingw32-gcc'), ('64', 'x86_64-w64-mingw32-gcc')]:
    subprocess.run([compiler, '-O2', '-Wall', '-Wextra', '-Werror', str(source),
                    '-o', str(qa / ('clipboard-' + bits + '.exe')), '-lole32', '-lshell32', '-luuid', '-lgdi32'],
                   check=True)
report = {'host_desktop_used': False, 'account_used': False, 'runtime': str(runtime), 'cases': [],
          'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'ole32_sha256': {}}
for bits, directory in [('32', 'i386-windows'), ('64', 'x86_64-windows')]:
    module = runtime / 'lib/wine' / directory / 'ole32.dll'
    report['ole32_sha256'][bits] = hashlib.sha256(module.read_bytes()).hexdigest()
with desktop(qa, bare=True) as env:
    env.update(WINEPREFIX=str(qa / 'prefix'), WINESERVER=str(runtime / 'bin/wineserver'), WINEDEBUG='-all')
    for writer in ('32', '64'):
        for profile in ('basic', 'target', 'flush'):
            name = writer + '-' + profile
            done = qa / (name + '.done')
            with (qa / (name + '.log')).open('w') as log:
                publisher = subprocess.Popen([str(runtime / 'bin/wine'), str(qa / ('clipboard-' + writer + '.exe')),
                    'write', 'Z:' + str(done).replace('/', '\\'), profile], env=env,
                    stdout=subprocess.PIPE, stderr=log, text=True)
                try:
                    if not select.select([publisher.stdout], [], [], 20)[0]:
                        raise TimeoutError('OLE publisher did not become ready: ' + name)
                    assert publisher.stdout.readline().strip() == 'ready', name
                    for reader in ('32', '64'):
                        for mode in ('raw', 'enum', 'ole'):
                            run = subprocess.run([str(runtime / 'bin/wine'),
                                str(qa / ('clipboard-' + reader + '.exe')), mode, profile],
                                env=env, capture_output=True, text=True, timeout=10)
                            case = dict(writer=writer, reader=reader, profile=profile, mode=mode,
                                passed=run.returncode == 0, exit_code=run.returncode,
                                stdout=run.stdout, stderr=run.stderr)
                            report['cases'].append(case)
                            (qa / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
                finally:
                    done.touch()
                    publisher.wait(timeout=5)
report['passed'] = len(report['cases']) == 36 and all(case['passed'] for case in report['cases'])
(qa / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'report': str(qa / 'result.json'), 'passed': report['passed']}))
raise SystemExit(0 if report['passed'] else 1)
