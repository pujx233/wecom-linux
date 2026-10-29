#!/usr/bin/env python3
"""Test fresh startup, busy-prefix refusal and application upgrades without an account."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--files', required=True, type=Path, help='Prepared package files directory')
parser.add_argument('--old-template', required=True, type=Path, help='Previous, never-logged-in template')
parser.add_argument('--qa', required=True, type=Path, help='New disposable directory, preferably on a build volume')
args = parser.parse_args()
files = args.files.resolve(strict=True)
qa = args.qa.resolve()
assert not qa.exists(), 'Use a new disposable QA directory'
qa.mkdir(parents=True)
(qa / '.wecom-frame-qa').touch()
(qa / 'wine').symlink_to(files / 'wine', target_is_directory=True)
os.environ['WECOM_QA_ROOT'] = str(qa)
sys.path.insert(0, str(Path(__file__).resolve().parent / 'frame-composition'))
from isolated import desktop
from screencast import recording


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


version, revision = (files / 'application-version').read_text().split()
app = Path('drive_c/Program Files (x86)/WXWork/WXWork.exe')
expected = digest(files / 'template' / app)
original = {name: digest(files / 'template' / name) for name in ('user.reg', 'system.reg', str(app))}
report = {'application_version': version, 'account_used': False, 'main_desktop_used': False, 'phases': []}

with desktop(qa, '3200x2000') as desktop_env:
    def environment(data):
        return desktop_env | {'XDG_DATA_HOME': str(data), 'WINEPREFIX': str(data / 'wecom/prefix'),
                              'WINESERVER': str(files / 'wine/bin/wineserver'), 'WINEDEBUG': '-all'}

    def stop(data):
        for option in ('-k', '-w'):
            subprocess.run([str(files / 'wine/bin/wineserver'), option], env=environment(data),
                           check=True, timeout=15)

    def launch(phase, data):
        env = environment(data)
        prefix = data / 'wecom/prefix'
        with (qa / (phase + '.log')).open('w') as log:
            process = subprocess.Popen([str(files / 'start.sh')], env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 60
            while True:
                tree = subprocess.check_output(['xwininfo', '-root', '-tree'], env=env, text=True)
                apps = []
                for entry in Path('/proc').iterdir():
                    if not entry.name.isdigit():
                        continue
                    try:
                        variables = (entry / 'environ').read_bytes().split(b'\0')
                        command = (entry / 'cmdline').read_bytes().split(b'\0')
                        if os.fsencode('WINEPREFIX=' + str(prefix)) in variables and command[0].endswith(b'WXWork.exe'):
                            apps.append(entry)
                    except (FileNotFoundError, ProcessLookupError, PermissionError):
                        continue
                if apps and '企业微信' in tree:
                    break
                assert process.poll() in (None, 0), (phase, process.returncode)
                assert time.monotonic() < deadline, (phase, tree)
                time.sleep(0.2)
            assert digest(prefix / app) == expected
            assert (prefix / '.wecom-application').read_text().strip() == revision
            mappings = (apps[0] / 'maps').read_text()
            assert str(prefix / app) in mappings
            assert str(files / 'wine/lib/wine/x86_64-unix/winex11.so') in mappings
            query = subprocess.check_output([str(files / 'wine/bin/wine'), 'reg', 'query',
                                             r'HKCU\Software\Tencent\WXWork', '/v', 'Version', '/reg:32'],
                                            env=env, text=True, timeout=15)
            assert version in query
            with recording(qa, desktop_env, phase) as capture:
                time.sleep(3)
                capture(qa / (phase + '.png'))
            report['phases'].append({'phase': phase, 'new_executable_loaded': True,
                                     'registry_version': version, 'screenshot': str(qa / (phase + '.png'))})
        finally:
            stop(data)
            process.wait(timeout=15)

    fresh = qa / 'fresh-data'
    launch('fresh', fresh)
    assert not os.path.samefile(fresh / 'wecom/prefix/user.reg', files / 'template/user.reg')

    upgraded = qa / 'upgrade-data'
    prefix = upgraded / 'wecom/prefix'
    prefix.parent.mkdir(parents=True)
    subprocess.run(['cp', '-a', '--reflink=auto', '--no-preserve=links', str(args.old_template), str(prefix)],
                   check=True)
    subprocess.run(['python3', str(files / 'relocate-prefix.py'), str(prefix), os.environ['USER']], check=True)
    assert not (prefix / '.wecom-application').exists()
    old_executable = digest(prefix / app)
    assert old_executable != expected, 'The old template must contain a different application version'
    private = prefix / 'drive_c/users' / os.environ['USER'] / 'Documents/UpgradeCheck/private-data.bin'
    private.parent.mkdir(parents=True, exist_ok=True)
    private.write_bytes(b'account-data-preservation-check\0\xff\x01')
    private_digest = digest(private)
    env = environment(upgraded)
    with (qa / 'busy-notepad.log').open('w') as log:
        note = subprocess.Popen([str(files / 'wine/bin/wine'), 'notepad.exe'], env=env, stdout=log, stderr=log)
    try:
        deadline = time.monotonic() + 20
        while 'Notepad' not in subprocess.check_output(['xwininfo', '-root', '-tree'], env=env, text=True):
            assert time.monotonic() < deadline
            time.sleep(0.2)
        busy = subprocess.run([str(files / 'start.sh')], env=env, capture_output=True, timeout=12)
        assert busy.returncode == 124, (busy.returncode, busy.stderr)
        assert digest(prefix / app) == old_executable
        assert digest(private) == private_digest
        assert not (prefix / '.wecom-application').exists()
        report['busy_prefix_unchanged'] = True
    finally:
        stop(upgraded)
        note.wait(timeout=15)

    obsolete = prefix / 'wecom-compat/scripts/launch-wecom.sh'
    obsolete.write_text('#!/bin/sh\nexit 99\n')
    launch('upgrade', upgraded)
    assert digest(private) == private_digest
    # A second start must keep the already deployed application rather than copy it again.
    os.utime(prefix / app, ns=(1600000000000000000, 1600000000000000000))
    launch('same-version', upgraded)
    assert (prefix / app).stat().st_mtime_ns == 1600000000000000000
    assert digest(private) == private_digest
    report['private_data_preserved'] = True
    report['same_version_not_recopied'] = True

assert all(digest(files / 'template' / name) == value for name, value in original.items())
report['template_unchanged'] = True
report['passed'] = True
(qa / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(report, ensure_ascii=False))
