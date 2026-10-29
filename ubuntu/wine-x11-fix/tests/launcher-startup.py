#!/usr/bin/env python3
"""Exercise launcher ordering and environment isolation without a desktop or user prefix."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[3])
parser.add_argument('--clean-env', action='store_true', help='Isolate launch ordering from environment sanitation')
args = parser.parse_args()
repo = args.repo.resolve(strict=True)
blocked = ('WINEARCH', 'WINELOADER', 'WINELOADERNOEXEC', 'WINEDLLPATH', 'WINESERVERSOCKET')
report = []

with tempfile.TemporaryDirectory(prefix='wecom-launcher-test-') as temporary:
    root = Path(temporary)
    files = root / 'package'
    scripts = files / 'template/wecom-compat/scripts'
    scripts.mkdir(parents=True)
    for name in ('launch-wecom.sh', 'prepare-startup.py'):
        shutil.copy2(repo / 'scripts' / name, scripts / name)
    (scripts.parent / 'configs').mkdir()
    (scripts.parent / 'configs/dll-overrides.txt').write_text('')
    shutil.copy2(repo / 'ubuntu/launch.sh', files / 'launch.sh')
    shutil.copy2(repo / 'ubuntu/package-launch.sh', files / 'start.sh')
    (files / 'wine/bin').mkdir(parents=True)
    (files / 'application-version').write_text('5.0.test test-revision\n')
    app = Path('drive_c/Program Files (x86)/WXWork/WXWork.exe')
    (files / 'template' / app).parent.mkdir(parents=True)
    (files / 'template' / app).write_bytes(b'new application')
    backup = Path('AppData/Roaming/Tencent/WeMail/WeMailBak/Base')
    (files / 'template/drive_c/users/wecom' / backup).mkdir(parents=True)
    (files / 'template/drive_c/users/wecom' / backup / 'base.ini').write_text('new')
    for name in ('wine', 'wineserver'):
        executable = files / 'wine/bin' / name
        executable.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
prefix = pathlib.Path(os.environ['WINEPREFIX'])
blocked = ('WINEARCH', 'WINELOADER', 'WINELOADERNOEXEC', 'WINEDLLPATH', 'WINESERVERSOCKET')
dirty = {key: os.environ[key] for key in blocked if key in os.environ}
assert not dirty, dirty
with open(os.environ['TEST_CALLS'], 'a') as output:
    output.write(json.dumps({'program': pathlib.Path(sys.argv[0]).name, 'args': sys.argv[1:],
                            'lock_exists': (prefix / 'drive_c/ProgramData/boost_interprocess/test/'
                                            'WXWORK-TBS-HELPER-LOCK').exists()}) + '\\n')
if pathlib.Path(sys.argv[0]).name == 'wineserver' and os.environ.get('TEST_BUSY') == '1':
    sys.exit(124)
if (sys.argv[1:3] == ['reg', 'add'] and os.environ.get('TEST_REG_FAIL_IMAGE') and
        sys.argv[3].endswith('\\\\' + os.environ['TEST_REG_FAIL_IMAGE'])):
    sys.exit(37)
''')
        executable.chmod(0o755)

    # prepare-startup intentionally recognizes executable identity, not argv alone.
    server = root / 'busy-server/wineserver'
    server.parent.mkdir()
    subprocess.run(['cc', '-x', 'c', '-', '-o', str(server)],
                   input='#include <unistd.h>\nint main(void) { sleep(30); }\n', text=True, check=True)

    def run_case(name, mode, busy=False, failed_image=None):
        data = root / name
        prefix = data / 'wecom/prefix'
        (prefix / app).parent.mkdir(parents=True)
        (prefix / app).write_bytes(b'old application')
        (prefix / 'system.reg').touch()
        (prefix / 'wecom-compat').mkdir()
        (prefix / 'drive_c/users' / os.environ['USER'] / backup).mkdir(parents=True)
        lock = prefix / 'drive_c/ProgramData/boost_interprocess/test/WXWORK-TBS-HELPER-LOCK'
        lock.parent.mkdir(parents=True)
        original = b'\x01' + bytes(11)
        lock.write_bytes(original)
        calls = data / 'calls.jsonl'
        env = {key: value for key, value in os.environ.items() if key not in blocked}
        if not args.clean_env:
            env.update({key: 'inherited-invalid-value' for key in blocked})
        env.update(WECOM_PREFIX=str(prefix), WINEPREFIX=str(prefix), XDG_DATA_HOME=str(data),
                   WECOM_TITLEBAR_FIX='0', WECOM_IME_FIX='0', WECOM_VPROT_FIX='0',
                   WECOM_WINE_BIN=str(files / 'wine/bin/wine'), TEST_CALLS=str(calls),
                   TEST_REG_FAIL_IMAGE=failed_image or '')
        running = None
        if busy:
            running = subprocess.Popen([str(server)], env=env)
            env['TEST_BUSY'] = '1'
        try:
            if mode == 'arch':
                env.pop('WECOM_EMBEDDED_UI_DPI_FIX', None)
                command = scripts / 'launch-wecom.sh'
            else:
                command = files / ('start.sh' if mode == 'upgrade' else 'launch.sh')
            result = subprocess.run(['bash', str(command)], env=env, capture_output=True, timeout=10)
            expected = 124 if busy and mode == 'upgrade' else 37 if failed_image else 0
            assert result.returncode == expected, (name, result.returncode, result.stderr,
                                                   (files / 'logs/launch.log').read_text()
                                                   if (files / 'logs/launch.log').exists() else '')
            events = [json.loads(line) for line in calls.read_text().splitlines()]
            wine = [event for event in events if event['program'] == 'wine']
            launches = [event for event in wine if event['args'][0] != 'reg']
            assert len(launches) == (0 if expected else 1), events
            if busy:
                assert lock.read_bytes() == original, name
                assert not list(prefix.glob('setup-backups/startup-lock-*')), name
                if mode == 'upgrade':
                    assert not wine and (prefix / app).read_bytes() == b'old application', name
            else:
                assert not lock.exists(), (name, events)
                saved = list(prefix.glob('setup-backups/startup-lock-*/WXWORK-TBS-HELPER-LOCK'))
                assert len(saved) == 1 and saved[0].read_bytes() == original, name
                assert all(not event['lock_exists'] for event in wine), (name, events)
                if mode == 'upgrade':
                    assert (prefix / app).read_bytes() == b'new application', name
                    assert (prefix / '.wecom-application').read_text().strip() == 'test-revision', name
            registry = [event for event in wine if event['args'][0] == 'reg']
            dpi_registry = [event for event in registry if 'dpiAwareness' in event['args'] or
                            'Image File Execution Options\\' in event['args'][2]]
            if mode == 'arch':
                assert not registry, events
            elif wine:
                images = ('WeMail.exe', 'FlutterPlugins.exe')
                if failed_image:
                    images = images[:images.index(failed_image) + 1]
                    assert wine == registry, events  # Failed configuration must not launch the client.
                assert [event['args'] for event in dpi_registry] == [
                    ['reg', 'add', 'HKLM\\Software\\Microsoft\\Windows NT\\CurrentVersion\\'
                     'Image File Execution Options\\' + image,
                     '/v', 'dpiAwareness', '/t', 'REG_DWORD', '/d', '1', '/f', '/reg:32'] for image in images], events
                assert wine[:len(registry)] == registry, events
                if mode != 'upgrade':
                    assert registry == dpi_registry, events
            report.append({'case': name, 'passed': True, 'wine_calls': len(wine),
                           'dpi_registry_calls': len(dpi_registry), 'exit_code': result.returncode})
        finally:
            if running:
                running.terminate()
                running.wait(timeout=5)

    run_case('ubuntu-idle', 'ubuntu')
    run_case('ubuntu-busy', 'ubuntu', busy=True)
    run_case('upgrade-idle', 'upgrade')
    run_case('upgrade-busy', 'upgrade', busy=True)
    run_case('arch-idle', 'arch')
    run_case('ubuntu-mail-dpi-failure', 'ubuntu', failed_image='WeMail.exe')
    run_case('ubuntu-flutter-dpi-failure', 'ubuntu', failed_image='FlutterPlugins.exe')

print(json.dumps({'passed': True, 'host_desktop_used': False, 'cases': report}, indent=2))
