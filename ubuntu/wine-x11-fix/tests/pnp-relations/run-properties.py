"""Run synthetic PnP property queries without access to the host system D-Bus."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--wine', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
parser.add_argument('--bits', choices=('32', '64'), default='64')
parser.add_argument('--keep-prefix', action='store_true', help='retain the private prefix for another isolated test')
parser.add_argument('--reuse-prefix', type=Path, help='reuse a marked prefix from a completed run')
args = parser.parse_args()
wine, out = args.wine.resolve(), args.out.resolve()
assert not out.is_relative_to(wine)
out.mkdir(parents=True, exist_ok=False)
(out / '.pnp-property-qa').touch()
prefix = args.reuse_prefix.resolve() if args.reuse_prefix else out / 'prefix'
if args.reuse_prefix:
    assert prefix.name == 'prefix' and (prefix.parent / '.pnp-property-qa').is_file()
    assert prefix.is_dir()
marker = b'WINEPREFIX=' + os.fsencode(prefix)
for process in Path('/proc').glob('[0-9]*'):
    try:
        assert marker not in (process / 'environ').read_bytes().split(b'\0'), 'private prefix is still active'
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        continue
source = Path(__file__).with_name('property.c').resolve()
exe = out / 'property.exe'
compiler = 'i686-w64-mingw32-gcc' if args.bits == '32' else 'x86_64-w64-mingw32-gcc'
command = [compiler, '-O2', '-Wall', '-Wextra', str(source), '-o', str(exe),
           '-lsetupapi', '-lcfgmgr32', '-ladvapi32']
subprocess.run(command, check=True)
env = {key: value for key, value in os.environ.items() if not key.startswith('WINE') and key not in
       ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'DBUS_SYSTEM_BUS_ADDRESS',
        'LD_PRELOAD', 'LD_LIBRARY_PATH')}
for directory in ('runtime', 'config', 'data', 'cache'):
    (out / directory).mkdir(mode=0o700)
env.update(WINEPREFIX=str(prefix), WINESERVER=str(wine / 'bin/wineserver'), WINEDEBUG='-all',
           WECOM_PNP_QA='1', WINEDLLOVERRIDES='mscoree,mshtml,winemenubuilder=',
           DBUS_SYSTEM_BUS_ADDRESS='unix:path=' + str(out / 'runtime/nonexistent-system-bus'),
           XDG_RUNTIME_DIR=str(out / 'runtime'), XDG_CONFIG_HOME=str(out / 'config'),
           XDG_DATA_HOME=str(out / 'data'), XDG_CACHE_HOME=str(out / 'cache'))
components = {name + '-' + arch: wine / 'lib/wine' / arch / name
              for name in ('setupapi.dll', 'cfgmgr32.dll', 'ntoskrnl.exe')
              for arch in ('i386-windows', 'x86_64-windows')}
components |= {'source': source, 'runner': Path(__file__).resolve(), 'fixture': exe}
report = {'passed': False, 'bits': args.bits, 'compile': command, 'host_desktop_used': False,
          'account_data_used': False, 'system_bus': env['DBUS_SYSTEM_BUS_ADDRESS'], 'prefix': str(prefix),
          'cases': [], 'loaded_modules': [], 'fixture_pids': []}
report['sha256_before'] = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in components.items()}
app = None
with (out / 'wine.log').open('w') as log:
    try:
        if not args.reuse_prefix:
            subprocess.run([str(wine / 'bin/wine'), 'wineboot.exe', '-u'], env=env, stdout=log, stderr=log,
                           check=True, timeout=60)
        app = subprocess.Popen([str(wine / 'bin/wine'), str(exe)], env=env, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=log, text=True)
        with selectors.DefaultSelector() as ready:
            ready.register(app.stdout, selectors.EVENT_READ)
            assert ready.select(30), 'property fixture did not become ready'
            assert json.loads(app.stdout.readline()).get('ready')
        for process in Path('/proc').glob('[0-9]*'):
            try:
                if marker not in (process / 'environ').read_bytes().split(b'\0'):
                    continue
                mappings = (process / 'maps').read_text().splitlines()
                if any(line.endswith(str(exe)) for line in mappings):
                    report['fixture_pids'].append(int(process.name))
                for line in mappings:
                    if 'r-xp' not in line or not line.endswith(('/setupapi.dll', '/cfgmgr32.dll')):
                        continue
                    module = Path(line.split()[-1])
                    digest = hashlib.sha256(module.read_bytes()).hexdigest()
                    assert digest in [report['sha256_before'][module.name + '-' + arch]
                                      for arch in ('i386-windows', 'x86_64-windows')]
                    report['loaded_modules'].append({'pid': int(process.name), 'path': str(module), 'sha256': digest})
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                continue
        arch = 'i386-windows' if args.bits == '32' else 'x86_64-windows'
        for module in ('setupapi.dll', 'cfgmgr32.dll'):
            expected = report['sha256_before'][module + '-' + arch]
            assert any(item['pid'] in report['fixture_pids'] and item['sha256'] == expected
                       for item in report['loaded_modules']), f'fixture did not map selected {module}'
        stdout, _ = app.communicate('\n', timeout=30)
        report['cases'] = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        report['exit_code'] = app.returncode
        assert report['cases'] and report['cases'][-1].get('summary'), 'fixture did not complete'
        report['passed'] = app.returncode == 0 and all(case.get('passed', True) for case in report['cases'])
    except Exception as error:
        report['error'] = f'{type(error).__name__}: {error}'
    finally:
        errors = []
        for option in ('-k', '-w'):
            try:
                result = subprocess.run([env['WINESERVER'], option], env=env, stdout=log, stderr=log, timeout=10)
                assert result.returncode in ((0, 1) if option == '-k' else (0,)), result.returncode
            except (OSError, subprocess.SubprocessError, AssertionError) as error:
                errors.append(f'wineserver {option}: {error}')
        if app and app.poll() is None:
            app.kill()
            app.wait(timeout=5)
        report['cleanup_errors'] = errors
report['sha256_after'] = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in components.items()}
report['passed'] = (report['passed'] and not report['cleanup_errors'] and
                    report['sha256_before'] == report['sha256_after'])
if not args.keep_prefix and not args.reuse_prefix and not report['cleanup_errors'] and prefix.exists():
    shutil.rmtree(prefix)
    report['prefix_removed'] = True
(out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'report': str(out / 'result.json'), 'passed': report['passed'],
                  'cases': len(report['cases']), 'error': report.get('error')}))
raise SystemExit(0 if report['passed'] else 1)
