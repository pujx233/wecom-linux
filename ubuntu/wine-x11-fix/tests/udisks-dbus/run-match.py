#!/usr/bin/env python3
"""Exercise the production UDisks rules and callback through a new private D-Bus daemon."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source', type=Path, required=True, help='Wine mountmgr.sys/dbus.c file to test')
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
source, out = args.source.resolve(), args.out.resolve()
out.mkdir(parents=True, exist_ok=False)
text = source.read_text()
rules = []
for name in ('udisks_match', 'udisks2_match_interfaces', 'udisks2_match_properties'):
    rules.append(re.search(r'static const char ' + name + r'\[\]\s*=.*?;', text, re.S).group())
(out / 'rules.inc').write_text('\n'.join(rules) + '\n')
start = text.index('static DBusHandlerResult udisks_filter(')
end = text.index('\n}', start) + 2
(out / 'filter.inc').write_text(text[start:end] + '\n')
harness = Path(__file__).with_name('match.c').resolve()
flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'dbus-1'], text=True)
command = ['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
           '-I', str(out), str(harness), '-o', str(out / 'match')] + shlex.split(flags)
build = subprocess.run(command, capture_output=True, text=True)
(out / 'build.log').write_text(build.stdout + build.stderr)
build.check_returncode()
env = {key: value for key, value in os.environ.items() if not key.startswith(('DBUS_', 'WINE')) and key not in
       ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'LD_PRELOAD', 'LD_LIBRARY_PATH')}
env['DBUS_SYSTEM_BUS_ADDRESS'] = 'unix:path=' + str(out / 'nonexistent-system-bus')
run = subprocess.run(['dbus-run-session', '--', str(out / 'match')], env=env,
                     capture_output=True, text=True, timeout=30)
inputs = {'source': source, 'runner': Path(__file__).resolve(), 'harness': harness,
          'rules': out / 'rules.inc', 'filter': out / 'filter.inc', 'executable': out / 'match'}
cases = [json.loads(line) for line in run.stdout.splitlines()]
report = {'source': str(source), 'compile': command, 'returncode': run.returncode,
          'sha256': {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in inputs.items()},
          'cases': cases, 'stderr': run.stderr, 'passed': run.returncode == 0 and len(cases) == 16,
          'host_system_bus_used': False, 'wine_started': False,
          'scope': 'Real broker routing and source callback; device operations are counted stand-ins.'}
(out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'report': str(out / 'result.json'), 'passed': report['passed'], 'cases': len(cases)}))
raise SystemExit(0 if report['passed'] else 1)
