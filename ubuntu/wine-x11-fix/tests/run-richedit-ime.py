#!/usr/bin/env python3
"""Exercise the packaged RichEdit adapter's ABI, COM identity, lifetime and opt-in scope."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).parent / 'frame-composition'))
from isolated import desktop

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
runtime = args.runtime.resolve()
qa = args.output.resolve()
qa.mkdir(parents=True, exist_ok=False)
(qa / '.wecom-frame-qa').touch()
(qa / 'wine').symlink_to(runtime)
os.environ['WECOM_QA_ROOT'] = str(qa)
source = Path(__file__).with_name('richedit-ime')
report = {'account_used': False, 'host_desktop_used': False, 'cases': [], 'msftedit_sha256': {}}
for bits, directory in [('32', 'i386-windows'), ('64', 'x86_64-windows')]:
    folder = qa / bits
    folder.mkdir()
    compiler = ('i686' if bits == '32' else 'x86_64') + '-w64-mingw32-'
    common = ['-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', '-fno-exceptions',
              '-fno-rtti', '-static-libgcc', '-static-libstdc++']
    for name, output, extra in [('backend.cpp', 'riched20.dll', ['-shared', '-Wl,--kill-at']),
                                ('probe.cpp', 'probe' + bits + '.exe', [])]:
        subprocess.run([compiler + 'g++', *common, str(source / name), '-o', str(folder / output),
                        *extra, '-luuid'], check=True)
    subprocess.run([compiler + 'gcc', '-Wall', '-Wextra', '-Werror', '-shared', str(source / 'duilib.c'),
                    str(source / 'duilib.def'), '-o', str(folder / 'DuiLib.dll')], check=True)
    module = runtime / 'lib/wine' / directory / 'msftedit.dll'
    report['msftedit_sha256'][bits] = hashlib.sha256(module.read_bytes()).hexdigest()

with desktop(qa, bare=True) as env:
    env.update(WINEPREFIX=str(qa / 'prefix'), WINESERVER=str(runtime / 'bin/wineserver'),
               WINEDEBUG='-all', WINEDLLOVERRIDES='riched20=n,b;msftedit=b;winemenubuilder=')
    wine = str(runtime / 'bin/wine')
    for bits in ('32', '64'):
        executable = qa / bits / ('probe' + bits + '.exe')
        key = rf'HKCU\Software\Wine\AppDefaults\{executable.name}\RichEdit'
        for profile in ('disabled', 'enabled', 'missing'):
            subprocess.run([wine, 'reg', 'add', key, '/v', 'DuiLibIMEContext', '/t', 'REG_DWORD',
                            '/d', '0' if profile == 'disabled' else '1', '/f'],
                           env=env, capture_output=True, check=True, timeout=20)
            result = subprocess.run([wine, str(executable), profile], cwd=executable.parent,
                                    env=env, capture_output=True, text=True, timeout=30)
            passed = result.returncode == 0 and 'PASS checks=2907 repeats=100 methods=18' in result.stdout
            report['cases'].append({'bits': bits, 'profile': profile, 'exit_code': result.returncode,
                                    'passed': passed, 'stdout': result.stdout, 'stderr': result.stderr})
            (qa / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
report['passed'] = len(report['cases']) == 6 and all(case['passed'] for case in report['cases'])
(qa / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'report': str(qa / 'result.json'), 'passed': report['passed']}))
raise SystemExit(0 if report['passed'] else 1)
