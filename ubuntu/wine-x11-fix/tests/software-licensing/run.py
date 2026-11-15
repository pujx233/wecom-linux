#!/usr/bin/env python3
"""Check both slwga architectures in a disposable, account-free Wine prefix."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--module-dir', type=Path, help='Optional build directory containing both architecture directories')
args = parser.parse_args()
runtime, output = args.runtime.resolve(), args.output.resolve()
modules = args.module_dir.resolve() if args.module_dir else runtime / 'lib/wine'
output.mkdir(parents=True, exist_ok=False)
prefix = output / 'prefix'
(output / 'runtime').mkdir(mode=0o700)
env = os.environ.copy()
for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS', 'WINEARCH', 'WINEDLLPATH', 'LD_PRELOAD',
            'WINELOADER', 'WINELOADERNOEXEC', 'WINESERVERSOCKET'):
    env.pop(key, None)
env.update(WINEPREFIX=str(prefix), WINESERVER=str(runtime / 'bin/wineserver'), WINEDEBUG='-all',
           XDG_RUNTIME_DIR=str(output / 'runtime'),
           WINEDLLOVERRIDES='winewayland.drv=d;mscoree,mshtml,winemenubuilder=')
report = {'account_used': False, 'host_desktop_used': False, 'cases': [], 'module_sha256': {}, 'passed': False}
wine = runtime / 'bin/wine'
try:
    with (output / 'wineboot.log').open('w') as log:
        subprocess.run([str(wine), 'wineboot', '-u'], env=env, stdout=log, stderr=log, check=True, timeout=90)
    for bits, architecture, windows in [('32', 'i386-windows', 'syswow64'), ('64', 'x86_64-windows', 'system32')]:
        module = modules / architecture / 'slwga.dll'
        report['module_sha256'][architecture] = hashlib.sha256(module.read_bytes()).hexdigest()
        target = prefix / 'drive_c/windows' / windows / 'slwga.dll'
        target.unlink(missing_ok=True)
        shutil.copy2(module, target)
        executable = output / ('slwga-' + bits + '.exe')
        compiler = 'i686-w64-mingw32-gcc' if bits == '32' else 'x86_64-w64-mingw32-gcc'
        subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2',
                        str(Path(__file__).with_name('slwga.c')), '-o', str(executable)], check=True)
        result = subprocess.run([str(wine), str(executable)], env=env, capture_output=True, text=True, timeout=30)
        (output / ('slwga-' + bits + '.log')).write_text(result.stdout + result.stderr)
        report['cases'].append({'bits': bits, 'passed': result.returncode == 0,
                                'exit_code': result.returncode, 'stdout': result.stdout})
    report['passed'] = all(case['passed'] for case in report['cases'])
except Exception as error:
    report['error'] = repr(error)
finally:
    subprocess.run([str(runtime / 'bin/wineserver'), '-k'], env=env, capture_output=True, timeout=10)
    subprocess.run([str(runtime / 'bin/wineserver'), '-w'], env=env, capture_output=True, timeout=10)
    (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
raise SystemExit(0 if report['passed'] else 1)
