#!/usr/bin/env python3
"""Execute actual PnP source functions with deterministic API stand-ins; no Wine or host D-Bus."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
source_path = args.source / 'dlls/ntoskrnl.exe/pnp.c'
source = source_path.read_text()
here = Path(__file__).resolve().parent


def extract(signature):
    start = source.index(signature)
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


start = source.index('DECLARE_CRITICAL_SECTION(invalidated_devices_cs);')
end = source.index('static inline const char *debugstr_propkey', start)
parts = [source[start:end]]
for signature in ('static void send_remove_device_irp(', 'static void remove_device(',
                  'static BOOL device_in_list(', 'static void handle_bus_relations(',
                  'void WINAPI IoInvalidateDeviceRelations(', 'static DWORD CALLBACK device_enum_thread_proc('):
    parts.append(extract(signature))
include = args.output / 'production.inc'
include.write_text('\n\n'.join(parts) + '\n')
executable = args.output / 'queue-harness'
command = ['cc', '-std=c11', '-O1', '-g', '-pthread', '-Wall', '-Wextra',
           '-Wno-unused-parameter', '-Wno-missing-field-initializers',
           '-I', str(args.output), str(here / 'queue-harness.c'), '-o', str(executable)]
build = subprocess.run(command, text=True, capture_output=True)
(args.output / 'build.log').write_text(build.stdout + build.stderr)
build.check_returncode()
report = {'source': str(source_path), 'source_sha256': hashlib.sha256(source_path.read_bytes()).hexdigest(),
          'harness_sha256': hashlib.sha256((here / 'queue-harness.c').read_bytes()).hexdigest(),
          'extracted_sha256': hashlib.sha256(include.read_bytes()).hexdigest(),
          'real_wine_started': False, 'host_dbus_used': False, 'cases': []}
for case in ('queue', 'relations'):
    result = subprocess.run([str(executable), case], text=True, capture_output=True, timeout=20)
    report['cases'].append({'name': case, 'passed': result.returncode == 0,
                            'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
report['passed'] = all(case['passed'] for case in report['cases'])
(args.output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'report': str(args.output / 'result.json'), 'passed': report['passed']}))
raise SystemExit(0 if report['passed'] else 1)
