#!/usr/bin/env python3
"""Test fresh startup, deferred upgrades and the next launch without an account."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--files', required=True, type=Path, help='Prepared package files directory')
previous = parser.add_mutually_exclusive_group(required=True)
previous.add_argument('--old-template', type=Path, help='Previous, never-logged-in template')
previous.add_argument('--old-files', type=Path, help='Previous package files, including its Wine runtime')
parser.add_argument('--qa', required=True, type=Path, help='New disposable directory, preferably on a build volume')
args = parser.parse_args()
files = args.files.resolve(strict=True)
old_files = args.old_files.resolve(strict=True) if args.old_files else files
old_template = old_files / 'template' if args.old_files else args.old_template.resolve(strict=True)
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


def applications(prefix):
    apps = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / 'cmdline').read_bytes().split(b'\0')
            if not command[0].endswith(b'WXWork.exe'):
                continue
            variables = (entry / 'environ').read_bytes().split(b'\0')
            if os.fsencode('WINEPREFIX=' + str(prefix)) in variables:
                apps.append(entry)
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    return apps


version, revision = (files / 'application-version').read_text().split()
app = Path('drive_c/Program Files (x86)/WXWork/WXWork.exe')
expected = digest(files / 'template' / app)
original = {name: digest(files / 'template' / name) for name in ('user.reg', 'system.reg', str(app))}
report = {'application_version': version, 'account_used': False, 'main_desktop_used': False, 'phases': []}
commands = qa / 'commands-without-archiver'
commands.mkdir()
for directory in os.get_exec_path():
    path = Path(directory)
    if not path.is_dir():
        continue
    for program in path.iterdir():
        target = commands / program.name
        if program.name not in ('7z', '7zz', '7za') and program.is_file() and not target.exists():
            target.symlink_to(program.resolve())
assert all(shutil.which(name, path=str(commands)) is None for name in ('7z', '7zz', '7za'))

with desktop(qa, '3200x2000') as desktop_env:
    def environment(data, payload=files):
        return desktop_env | {'XDG_DATA_HOME': str(data), 'WINEPREFIX': str(data / 'wecom/prefix'),
                              'WECOM_PREFIX': str(data / 'wecom/prefix'),
                              'PATH': str(commands),
                              'WINESERVER': str(payload / 'wine/bin/wineserver'), 'WINEDEBUG': '-all'}

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
                apps = applications(prefix)
                if apps and '企业微信' in tree:
                    break
                assert process.poll() in (None, 0), (phase, process.returncode)
                assert time.monotonic() < deadline, (phase, tree)
                time.sleep(0.2)
            assert digest(prefix / app) == expected
            assert (prefix / '.wecom-application').read_text().strip() == revision
            mappings = (apps[0] / 'maps').read_text()
            assert str(prefix / app) in mappings
            driver = (files / 'wine/lib/wine/x86_64-unix/winex11.so').resolve(strict=True)
            assert str(driver) in mappings
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
    subprocess.run(['cp', '-a', '--reflink=auto', '--no-preserve=links', str(old_template), str(prefix)],
                   check=True)
    subprocess.run(['python3', str(files / 'relocate-prefix.py'), str(prefix), os.environ['USER']], check=True)
    marker = prefix / '.wecom-application'
    old_revision = marker.read_text() if marker.exists() else None
    assert old_revision is None or old_revision.strip() != revision
    old_executable = digest(prefix / app)
    private = prefix / 'drive_c/users' / os.environ['USER'] / 'Documents/UpgradeCheck/private-data.bin'
    private.parent.mkdir(parents=True, exist_ok=True)
    private.write_bytes(b'account-data-preservation-check\0\xff\x01')
    private_digest = digest(private)
    env = environment(upgraded)
    old_env = environment(upgraded, old_files) | {'WECOM_LOG_DIR': str(qa / 'previous-launch')}
    with (qa / 'busy-client.log').open('w') as log:
        old_client = subprocess.Popen(['bash', str(old_files / 'launch.sh')], env=old_env, stdout=log, stderr=log)
    try:
        deadline = time.monotonic() + 60
        while '企业微信' not in subprocess.check_output(['xwininfo', '-root', '-tree'], env=env, text=True):
            assert time.monotonic() < deadline
            time.sleep(0.2)
        assert old_client.poll() is None
        driver = str((old_files / 'wine/lib/wine/x86_64-unix/winex11.so').resolve(strict=True))
        old_app = next(entry for entry in applications(prefix) if driver in (entry / 'maps').read_text())
        old_mappings = (old_app / 'maps').read_text()
        busy = subprocess.run([str(files / 'start.sh')], env=env, capture_output=True, timeout=12)
        assert busy.returncode == 0, (busy.returncode, busy.stderr)
        assert old_client.poll() is None, 'The running client was interrupted'
        current_mappings = (old_app / 'maps').read_text()
        assert [line for line in current_mappings.splitlines() if driver in line] == [
            line for line in old_mappings.splitlines() if driver in line]
        assert digest(prefix / app) == old_executable
        assert digest(private) == private_digest
        assert (marker.read_text() if marker.exists() else None) == old_revision
        report['busy_prefix_unchanged'] = True
        report['running_client_continued'] = True
        subprocess.run([str(old_files / 'wine/bin/wine'), 'taskkill.exe', '/im', 'WXWork.exe'],
                       env=old_env, check=True, stdout=subprocess.DEVNULL, timeout=15)
        deadline = time.monotonic() + 15
        while applications(prefix):
            assert time.monotonic() < deadline, 'The normal close request did not end WeCom'
            time.sleep(.1)
        background = subprocess.run(['timeout', '3', str(old_files / 'wine/bin/wineserver'), '-w'], env=old_env)
        assert background.returncode == 124, 'The regression requires the remaining Wine desktop'
        report['normal_exit_left_background'] = True
    finally:
        if not report.get('normal_exit_left_background'):
            stop(upgraded)
            old_client.wait(timeout=15)

    obsolete = prefix / 'wecom-compat/scripts/launch-wecom.sh'
    obsolete.write_text('#!/bin/sh\nexit 99\n')
    launch('upgrade', upgraded)
    old_client.wait(timeout=15)
    assert digest(private) == private_digest
    # A second start must keep the already deployed application rather than copy it again.
    os.utime(prefix / app, ns=(1600000000000000000, 1600000000000000000))
    launch('same-version', upgraded)
    assert (prefix / app).stat().st_mtime_ns == 1600000000000000000
    assert digest(private) == private_digest
    report['private_data_preserved'] = True
    report['same_version_not_recopied'] = True
    report['first_start_without_7z_7zz_7za'] = True

assert all(digest(files / 'template' / name) == value for name, value in original.items())
report['template_unchanged'] = True
report['passed'] = True
(qa / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(report, ensure_ascii=False))
