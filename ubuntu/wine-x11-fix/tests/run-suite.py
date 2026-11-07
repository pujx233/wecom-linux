#!/usr/bin/env python3
"""Run the Wine and launcher regression groups in separate, account-free directories."""
import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--files', required=True, type=Path, help='Prepared package files directory')
    parser.add_argument('--source', required=True, type=Path, help='Patched Wine source tree')
    parser.add_argument('--output', required=True, type=Path, help='New result directory')
    parser.add_argument('--previous-files', type=Path, help='Previous package files for the upgrade test')
    parser.add_argument('--case', action='append', help='Run only the named groups; may be repeated')
    parser.add_argument('--keep-prefixes', action='store_true', help="Keep successful groups' disposable Wine prefixes")
    args = parser.parse_args()
    files, source, output = args.files.resolve(), args.source.resolve(), args.output.resolve()
    wine = files / 'wine'
    cases = {}

    def add(name, script, arguments=(), env=None, prepare=False):
        cases[name] = (script, [str(a) for a in arguments], env or {}, prepare)

    add('launcher', 'launcher-startup.py')
    add('launcher-clean', 'launcher-startup.py', ['--clean-env'])
    add('native-size', 'frame-composition/run-native-size.py', ['--source', source, '--out', output / 'native-size'])
    add('surface-lock', 'draw-completion/run-surface-region-lock.py',
        [source / 'dlls/win32u/window.c', output / 'surface-lock/result.json'])
    add('pnp-queue', 'pnp-relations/run-queue.py', ['--source', source, '--output', output / 'pnp-queue'])
    add('bluetooth-names', 'bluetooth-names.py', ['--source', source, '--output', output / 'bluetooth-names'])
    add('udisks', 'udisks-dbus/run-match.py',
        ['--source', source / 'dlls/mountmgr.sys/dbus.c', '--out', output / 'udisks'])
    for bits in ('32', '64'):
        name = 'pnp-' + bits
        add(name, 'pnp-relations/run-properties.py', ['--wine', wine, '--out', output / name, '--bits', bits])
    for name, script in [('popup', 'run-regression.py'), ('foreign-dc', 'dc-regression.py')]:
        add(name, script, ['--runtime', wine, '--output', output / name])
    for bits in ('32', '64'):
        name = 'cursor-' + bits
        add(name, 'cursor-regression.py', ['--wine', wine, '--manifest', HERE.parent.parent / 'validation.json',
                                         '--exe', output / ('cursor-' + bits + '.exe'), '--out', output / name])
    add('gdiplus', 'run-gdiplus.py', ['--runtime', wine, '--output', output / 'gdiplus'])
    add('foreground-policy', None)
    for name, extra in [('first', []), ('cancel', ['--cancel'])]:
        add(name, 'frame-composition/run-first-transaction.py', [output / name, wine, name, *extra],
            {'WECOM_QA_SCALE': '2'})
    for name, scale, extra in [('first-odd-1', '1', []), ('first-odd-2', '2', []),
                                ('cancel-odd-2', '2', ['--cancel'])]:
        add(name, 'frame-composition/run-first-transaction.py',
            [output / name, wine, name, '--odd-size', '--compact', *extra], {'WECOM_QA_SCALE': scale})
    for name, script in [('anchor', 'attached-anchor'), ('frame-sync', 'frame-sync'),
                         ('frame-reuse', 'frame-sync-reuse'), ('shape', 'shape-clip')]:
        add(name, 'frame-composition/run-' + script + '.py', ['--runtime', wine, '--output', output / name])
    add('own-dc', 'draw-completion/run-own-dc-caret.py', ['--runtime', wine, '--output', output / 'own-dc'])
    for name, script, env in [
        ('resize', 'resize-drawable', {}), ('extents-move', 'resize-extents', {}),
        ('extents-no-ack', 'resize-extents', {'WECOM_QA_NO_EXTENDED_SYNC': '1'}),
        ('extents-still', 'resize-extents', {'WECOM_QA_STATIONARY': '1'}),
        ('extents-direct', 'resize-extents', {'WECOM_QA_DELAY_WM': '0'}),
        ('foreign', 'foreign-frame', {}), ('roles', 'frame-roles', {}),
        ('input', 'popup-input', {}), ('create', 'create-reparent', {}),
        ('cards', 'card-stack', {}), ('display-removal', 'display-removal', {})]:
        add(name, 'frame-composition/run-' + script + '.py', env=env, prepare=True)
    for scale in ('1', '2'):
        add('maximize-' + scale, 'frame-composition/run-maximize.py', ['--scale', scale], prepare=True)
        add('workarea-' + scale, 'frame-composition/run-maximize.py',
            ['--scale', scale, '--workarea-cycle'], prepare=True)
        add('fullscreen-' + scale, 'frame-composition/run-maximize.py',
            ['--scale', scale, '--workarea-cycle', '--fullscreen'], prepare=True)
    for name, extra in [
        ('ime-96', ['--dpi', '96']), ('ime-192', ['--dpi', '192']),
        ('ime-unaware', ['--dpi', '192', '--awareness', 'unaware']),
        ('ime-32', ['--dpi', '192', '--bits', '32']), ('ime-plain', ['--dpi', '192', '--frame', '0']),
        ('ime-position', ['--dpi', '192', '--preedit', 'position']),
        ('ime-mixed', ['--mixed-scale']), ('ime-candidate', ['--candidate'])]:
        add(name, 'ime-position/run-isolated.py',
            ['--runtime', wine, '--output', output / name, '--name', 'run', *extra])
    add('pending-native-minimize', 'frame-composition/run-maximize.py',
        ['--scale', '1', '--case', 'negative-secondary-shadow', '--pending-native-minimize'], prepare=True)
    add('reentrant-fullscreen', 'frame-composition/run-maximize.py',
        ['--scale', '1', '--case', 'negative-secondary-shadow', '--reentrant-fullscreen'], prepare=True)
    add('clipboard', 'run-clipboard-files.py', ['--runtime', wine, '--qa', output / 'clipboard'])
    add('prefix-settings', 'prefix-settings.py', ['--files', files, '--qa', output / 'prefix-settings'])
    add('upgrade', 'package-upgrade.py',
        ['--files', files, '--old-files', args.previous_files, '--qa', output / 'upgrade'])
    add('native-dialogs', 'run-native-file-dialogs.py', ['--runtime', wine, '--output', output / 'native-dialogs'])
    selected = args.case or list(cases)
    if unknown := set(selected) - cases.keys():
        parser.error('Unknown groups: ' + ', '.join(sorted(unknown)))
    if 'upgrade' in selected and args.previous_files is None:
        parser.error('The upgrade group requires --previous-files')
    output.mkdir(parents=True, exist_ok=False)
    report = {'runtime': str(wine), 'source': str(source), 'selected': selected, 'groups': [],
              'runtime_sha256': {}, 'host_desktop_used': False, 'account_used': False}
    for module in ('winex11.so', 'win32u.so'):
        path = wine / 'lib/wine/x86_64-unix' / module
        report['runtime_sha256'][module] = hashlib.sha256(path.read_bytes()).hexdigest()
    for name in selected:
        script, arguments, extra, prepare = cases[name]
        directory = output / name
        if prepare:
            directory.mkdir()
            (directory / '.wecom-frame-qa').touch()
            (directory / 'wine').symlink_to(wine)
        elif name == 'surface-lock':
            directory.mkdir()
        env = os.environ.copy()
        for key in ('WECOM_QA_SCALE', 'WECOM_QA_NO_EXTENDED_SYNC', 'WECOM_QA_STATIONARY', 'WECOM_QA_DELAY_WM'):
            env.pop(key, None)
        env.update(extra, WECOM_QA_ROOT=str(directory))
        started = time.monotonic()
        print('START ' + name, flush=True)
        log_path = output / (name + '.log')
        with log_path.open('w') as log:
            if name.startswith('cursor-'):
                compiler = 'i686-w64-mingw32-gcc' if name.endswith('32') else 'x86_64-w64-mingw32-gcc'
                subprocess.run([compiler, '-O2', '-Wall', '-Wextra', str(HERE / 'foreign-cursor-test.c'),
                                '-o', str(output / (name + '.exe')), '-lgdi32', '-luser32'],
                               stdout=log, stderr=log, check=True)
            if name == 'foreground-policy':
                executable = output / name
                subprocess.run(['cc', '-O2', '-ffunction-sections', '-Wl,--gc-sections',
                                str(HERE / 'foreground-restore.c'), '-o', str(executable)],
                               stdout=log, stderr=log, check=True)
                result = subprocess.run([str(executable)], stdout=log, stderr=log)
            else:
                result = subprocess.run([sys.executable, str(HERE / script), *arguments],
                                        env=env, stdout=log, stderr=log)
        removed_prefixes = 0
        if result.returncode == 0 and not args.keep_prefixes:
            prefixes = []
            for root, directories, names in os.walk(directory, followlinks=False):
                # Runtime directories may contain the document portal's FUSE mount.
                directories[:] = [d for d in directories if d not in ('runtime', 'wine', 'template')]
                if {'system.reg', 'user.reg'}.issubset(names) and 'drive_c' in directories:
                    prefixes.append(Path(root))
                    directories.clear()
            for prefix in prefixes:
                private_env = env | {'WINEPREFIX': str(prefix)}
                with log_path.open('a') as log:
                    stopped = subprocess.run([str(wine / 'bin/wineserver'), '-k'], env=private_env,
                                             stdout=log, stderr=log, timeout=5)
                    if stopped.returncode not in (0, 1):
                        raise subprocess.CalledProcessError(stopped.returncode, stopped.args)
                    subprocess.run([str(wine / 'bin/wineserver'), '-w'], env=private_env,
                                   stdout=log, stderr=log, check=True, timeout=10)
                shutil.rmtree(prefix)
                removed_prefixes += 1
        report['groups'].append({'name': name, 'exit_code': result.returncode, 'passed': result.returncode == 0,
                                'removed_prefixes': removed_prefixes,
                                 'seconds': round(time.monotonic() - started, 2), 'log': str(log_path)})
        report['complete'] = len(report['groups']) == len(selected)
        report['passed'] = report['complete'] and all(g['passed'] for g in report['groups'])
        (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        print(f'END {name}: {result.returncode}', flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
