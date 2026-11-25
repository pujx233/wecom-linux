#!/usr/bin/env python3
"""Exercise launcher ordering and environment isolation without a desktop or user prefix."""
import argparse
import json
import mmap
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[3])
parser.add_argument('--files', type=Path, help='Exercise the scripts actually shipped in this package')
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
    installed = args.files.resolve(strict=True) if args.files else None
    source_scripts = installed / 'template/wecom-compat/scripts' if installed else repo / 'scripts'
    for name in ('launch-wecom.sh', 'prepare-startup.py', 'select-locale.py'):
        shutil.copy2(source_scripts / name, scripts / name)
    (scripts / 'ibus-xim.py').write_text("import os, sys\nos.environ['TEST_XIM_LAUNCH'] = '1'\n"
                                         "os.execvp(sys.argv[1], sys.argv[1:])\n")
    subprocess.run(['cc', '-shared', '-fPIC', '-x', 'c', '-', '-o', str(scripts / 'ime-bridge.so')],
                   input='void launcher_test_bridge(void) {}\n', text=True, check=True)
    (scripts.parent / 'configs').mkdir()
    (scripts.parent / 'configs/dll-overrides.txt').write_text('')
    for name in ('fonts-install.reg', 'fonts-replacements.reg'):
        (scripts.parent / 'configs' / name).write_text('REGEDIT4\n')
    fonts = files / 'template/drive_c/windows/Fonts'
    fonts.mkdir(parents=True)
    (fonts / 'test.ttf').write_bytes(b'test font')
    for name in ('launch.sh', 'start.sh', 'configure-prefix.py', 'prefix-state.py', 'relocate-prefix.py'):
        source_name = 'package-launch.sh' if name == 'start.sh' else name
        shutil.copy2(installed / name if installed else repo / 'ubuntu' / source_name, files / name)
    for name in ('system.reg', 'user.reg', 'userdef.reg'):
        (files / 'template' / name).write_text('"USERNAME"="wecom"\n')
    (files / 'template/.wecom-application').write_text('test-revision\n')
    for architecture in ('i386-windows', 'x86_64-windows'):
        directory = files / 'wine/lib/wine' / architecture
        directory.mkdir(parents=True)
        for name in ('comdlg32.dll', 'shell32.dll', 'explorer.exe', 'slwga.dll', 'user32.dll', 'msftedit.dll'):
            (directory / name).write_bytes(b'test runtime')
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
                            'cef_cache': os.environ.get('WECOM_SHARED_CEF_IMAGE'),
                            'pe_cache': os.environ.get('WECOM_SHARED_PE_IMAGE'),
                            'ime_bridge': os.environ.get('WECOM_IME_FIX'),
                            'private_xim': os.environ.get('TEST_XIM_LAUNCH'),
                            'frame': os.environ.get('WINE_X11_OWNED_FRAME'),
                            'preload': os.environ.get('LD_PRELOAD'),
                            'locale': {key: os.environ.get(key) for key in
                                       ('LANG', 'LC_CTYPE', 'LC_MESSAGES', 'LC_ALL')},
                            'lock_exists': (prefix / 'drive_c/ProgramData/boost_interprocess/test/'
                                            'WXWORK-TBS-HELPER-LOCK').exists()}) + '\\n')
if pathlib.Path(sys.argv[0]).name == 'wineserver' and os.environ.get('TEST_SERVER_ERROR'):
    sys.exit(int(os.environ['TEST_SERVER_ERROR']))
if pathlib.Path(sys.argv[0]).name == 'wineserver' and os.environ.get('TEST_BUSY') == '1':
    stopped = prefix / '.mock-server-stopped'
    if sys.argv[1:] == ['-k']:
        import signal
        os.kill(int(os.environ['TEST_SERVICE_PID']), signal.SIGTERM)
        stopped.touch()
    elif not stopped.exists():
        sys.exit(124)
if (sys.argv[1:3] == ['reg', 'add'] and os.environ.get('TEST_REG_FAIL_IMAGE') and
        sys.argv[3].endswith('\\\\' + os.environ['TEST_REG_FAIL_IMAGE'])):
    sys.exit(37)
if sys.argv[1:3] == ['reg', 'query']:
    value = os.environ.get('TEST_MEETING_DPI')
    if not value:
        sys.exit(1)
    print('    dpiAwareness    REG_DWORD    ' + value + '\\r')
''')
        executable.chmod(0o755)

    # prepare-startup intentionally recognizes executable identity, not argv alone.
    server = root / 'busy-server/wine'
    server.parent.mkdir()
    subprocess.run(['cc', '-x', 'c', '-', '-o', str(server)],
                   input='#include <unistd.h>\nint main(void) { sleep(30); }\n', text=True, check=True)

    def run_case(name, mode, busy=False, failed_image=None, server_error=None, background=False,
                 linked_prefix=False, cef_cache=None, pe_cache=None, cef_ime=None, owned_frame=None,
                 legacy_ime=None, session='wayland', desktop='ubuntu:GNOME', xim='@im=ibus', busy_image='WXWork.exe',
                 meeting_dpi=None, incomplete=False, invalid_locale=False, missing_locale=False):
        data = root / name
        prefix = data / 'wecom/prefix'
        (prefix / app).parent.mkdir(parents=True)
        (prefix / app).write_bytes(b'old application')
        if not incomplete:
            (prefix / 'system.reg').touch()
        (prefix / 'user.reg').write_text('[Control Panel\\\\Desktop]\n"LogPixels"=dword:00000060\n\n'
                                         '[Software\\\\Wine\\\\Fonts]\n"LogPixels"=dword:00000060\n')
        for directory in ('system32', 'syswow64'):
            (prefix / 'drive_c/windows' / directory).mkdir(parents=True)
        (prefix / 'wecom-compat').mkdir()
        (prefix / 'drive_c/users' / os.environ['USER'] / backup).mkdir(parents=True)
        profile = prefix / 'drive_c/users' / os.environ['USER']
        original_user_registry = (prefix / 'user.reg').read_bytes()
        if incomplete:
            (profile / 'account-data').write_bytes(b'preserve existing files')
        lock = prefix / 'drive_c/ProgramData/boost_interprocess/test/WXWORK-TBS-HELPER-LOCK'
        lock.parent.mkdir(parents=True)
        original = b'\x01' + bytes(11)
        lock.write_bytes(original)
        if linked_prefix:
            account = data / 'account'
            prefix.rename(account)
            prefix.symlink_to(account, target_is_directory=True)
        calls = data / 'calls.jsonl'
        env = {key: value for key, value in os.environ.items() if key not in blocked}
        env.pop('WECOM_SHARED_CEF_IMAGE', None)
        env.pop('WECOM_SHARED_PE_IMAGE', None)
        for key in ('WECOM_CEF_IME_FIX', 'WECOM_IME_FIX', 'WINE_X11_OWNED_FRAME'):
            env.pop(key, None)
        env.pop('LD_PRELOAD', None)
        env.pop('WECOM_IBUS_XIM_HELPER', None)
        env.pop('WECOM_WINE_INITIAL_THREAD_DPI', None)
        env.update(DISPLAY=':100', XDG_RUNTIME_DIR=str(data), XDG_SESSION_TYPE=session,
                   XDG_CURRENT_DESKTOP=desktop, XMODIFIERS=xim)
        if invalid_locale:
            env['LC_ALL'] = 'wecom-test-unavailable.UTF-8'
        if missing_locale:
            empty = data / 'empty-locales'
            empty.mkdir()
            env['LOCPATH'] = str(empty)
        if cef_ime is not None:
            env['WECOM_CEF_IME_FIX'] = cef_ime
        if legacy_ime is not None:
            env['WECOM_IME_FIX'] = legacy_ime
        if owned_frame is not None:
            env['WINE_X11_OWNED_FRAME'] = owned_frame
        if cef_cache is not None:
            env['WECOM_SHARED_CEF_IMAGE'] = cef_cache
        if pe_cache is not None:
            env['WECOM_SHARED_PE_IMAGE'] = pe_cache
        if not args.clean_env:
            env.update({key: 'inherited-invalid-value' for key in blocked})
        env.update(WECOM_PREFIX=str(prefix), WINEPREFIX=str(prefix), XDG_DATA_HOME=str(data),
                   WECOM_TITLEBAR_FIX='0', WECOM_VPROT_FIX='0',
                   WECOM_WINE_BIN=str(files / 'wine/bin/wine'), TEST_CALLS=str(calls),
                   TEST_REG_FAIL_IMAGE=failed_image or '', TEST_MEETING_DPI=meeting_dpi or '', WECOM_DPI='96',
                   TEST_SERVER_ERROR=str(server_error) if server_error else '')
        old_file = (prefix / app).open('rb')
        old_mapping = mmap.mmap(old_file.fileno(), 0, access=mmap.ACCESS_READ)
        running = None
        if busy or background:
            image = r'C:\windows\system32\explorer.exe' if background else busy_image
            running = subprocess.Popen([image], executable=str(server), env=env)
            env['TEST_BUSY'] = '1'
            if background:
                env['TEST_SERVICE_PID'] = str(running.pid)
        try:
            if mode == 'arch':
                env.pop('WECOM_EMBEDDED_UI_DPI_FIX', None)
                command = scripts / 'launch-wecom.sh'
            else:
                command = files / ('start.sh' if mode == 'upgrade' else 'launch.sh')
            result = subprocess.run(['bash', str(command)], env=env, capture_output=True, timeout=10)
            expected = server_error or (37 if failed_image else 0)
            if incomplete and busy:
                expected = 124
            assert result.returncode == expected, (name, result.returncode, result.stderr,
                                                   (files / 'logs/launch.log').read_text()
                                                   if (files / 'logs/launch.log').exists() else '')
            events = [json.loads(line) for line in calls.read_text().splitlines()]
            if mode != 'arch':
                assert all(event['cef_cache'] == (cef_cache or '1') for event in events), events
                assert all(event['pe_cache'] == (pe_cache or '1') for event in events), events
            wine = [event for event in events if event['program'] == 'wine']
            launches = [event for event in wine if event['args'][0] != 'reg']
            assert len(launches) == (0 if expected else 1), events
            if launches:
                launch = launches[0]
                language = launch['locale']
                assert language['LANG'] == language['LC_CTYPE'] == language['LC_MESSAGES'], language
                assert language['LC_ALL'] is None, language
                if missing_locale:
                    assert language['LC_CTYPE'] == 'C.UTF-8', language
                assert all(event['locale'] == language for event in wine), events
                locale_env = env.copy()
                locale_env.pop('LC_ALL', None)
                locale_env.update({key: value for key, value in language.items() if value is not None})
                assert subprocess.check_output(['locale', 'charmap'], env=locale_env).strip() == b'UTF-8', language
                if mode == 'upgrade' and not busy:
                    stamp = json.loads((prefix / '.wecom-display-fonts.json').read_text())
                    assert stamp['locale'] == language['LC_CTYPE'], stamp
                named = (mode != 'arch' and session == 'wayland' and 'GNOME' in desktop.split(':')
                         and xim == '@im=ibus' and os.access('/usr/libexec/ibus-x11', os.X_OK))
                assert bool(launch['private_xim']) == named, (name, launch)
                assert all(not event['private_xim'] for event in events if event is not launch), (name, events)
                native_ime = (cef_ime if cef_ime is not None else '0' if mode == 'arch' else '1') == '1'
                feature = '--disable-features=TSFImeSupport'
                assert (feature in launch['args']) == native_ime, (name, launch)
                reuse_desktop = mode == 'upgrade' and busy and busy_image == 'WXWork.exe'
                use_explorer = (mode != 'arch' or owned_frame == '1') and not reuse_desktop
                if mode != 'arch':
                    assert launch['frame'] == '1', (name, launch)
                if use_explorer:
                    assert launch['args'][:2] == ['explorer.exe', '/desktop'], (name, launch)
                else:
                    assert launch['args'][0] == str(prefix.resolve() / app), (name, launch)
                assert launch['args'].count(feature) == int(native_ime), (name, launch)
                if native_ime:
                    assert launch['args'][-1] == feature, (name, launch)
                bridge = (legacy_ime if legacy_ime is not None else '1' if mode == 'arch' else '0') != '0'
                assert bool(launch['preload']) == (bridge and not native_ime), (name, launch)
                if launch['preload']:
                    assert launch['preload'] == str(scripts / 'ime-bridge.so'), (name, launch)
                if mode != 'arch' and legacy_ime is None:
                    assert launch['ime_bridge'] == '0', (name, launch)
            assert old_mapping[:] == b'old application', (name, 'updated an existing file mapping')
            if incomplete:
                assert (prefix / 'user.reg').read_bytes() == original_user_registry
                assert (profile / 'account-data').read_bytes() == b'preserve existing files'
                assert not (prefix / 'prefix').exists()
                if busy:
                    assert not wine and not (prefix / 'system.reg').exists()
                    report.append({'case': name, 'passed': True, 'exit_code': result.returncode})
                    return
                assert (prefix / 'system.reg').read_text() == f'"USERNAME"="{os.environ["USER"]}"\n'
                assert (prefix / 'userdef.reg').is_file()
            if server_error:
                assert not wine and (prefix / app).read_bytes() == b'old application', name
                report.append({'case': name, 'passed': True, 'exit_code': result.returncode})
                return
            if busy:
                assert lock.read_bytes() == original, name
                assert not list(prefix.glob('setup-backups/startup-lock-*')), name
                if mode == 'upgrade':
                    assert len(wine) == 1 and (prefix / app).read_bytes() == b'old application', name
                    assert not (prefix / '.wecom-application').exists(), name
                    assert running.poll() is None, name
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
            if mode == 'arch' or busy and mode == 'upgrade':
                assert not registry, events
            elif wine:
                image_options = (r'HKLM\Software\Microsoft\Windows NT\CurrentVersion\Image File Execution Options'
                                 + '\\')
                images = ('WeMail.exe', 'FlutterPlugins.exe', 'wwmapp.exe')
                if failed_image:
                    images = images[:images.index(failed_image) + 1]
                    assert wine == registry, events  # Failed configuration must not launch the client.
                init = 'wineInitialThreadDpiAwareness'
                expected_calls = [['reg', 'add', image_options + image, '/v',
                                   init if image == 'wwmapp.exe' else 'dpiAwareness',
                                   '/t', 'REG_DWORD', '/d', '3' if image == 'wwmapp.exe' else '1', '/f', '/reg:32']
                                  for image in images]
                if not failed_image:
                    options = image_options + 'wwmapp.exe'
                    expected_calls.append(['reg', 'query', options, '/v', 'dpiAwareness', '/reg:32'])
                    if meeting_dpi == '0x0':
                        expected_calls.append(['reg', 'delete', options, '/v', 'dpiAwareness', '/f', '/reg:32'])
                assert [event['args'] for event in dpi_registry] == expected_calls, events
                assert wine[:len(registry)] == registry, events
                if mode != 'upgrade':
                    assert registry == dpi_registry, events
            report.append({'case': name, 'passed': True, 'wine_calls': len(wine),
                           'dpi_registry_calls': len(dpi_registry), 'exit_code': result.returncode,
                           'locale': launches[0]['locale'] if launches else None})
        finally:
            old_mapping.close()
            old_file.close()
            if running:
                running.terminate()
                running.wait(timeout=5)

    run_case('ubuntu-idle', 'ubuntu')
    run_case('ubuntu-fcitx', 'ubuntu', xim='@im=fcitx')
    run_case('ubuntu-x11', 'ubuntu', session='x11')
    run_case('kde-wayland', 'ubuntu', desktop='KDE')
    run_case('ubuntu-busy', 'ubuntu', busy=True)
    run_case('upgrade-idle', 'upgrade')
    run_case('upgrade-cef-cache-disabled', 'upgrade', cef_cache='0')
    run_case('upgrade-pe-cache-disabled', 'upgrade', pe_cache='0')
    run_case('upgrade-busy', 'upgrade', busy=True)
    run_case('upgrade-other-client', 'upgrade', busy=True, busy_image='WeMail.exe')
    run_case('upgrade-background', 'upgrade', background=True)
    run_case('upgrade-busy-linked-prefix', 'upgrade', busy=True, linked_prefix=True)
    run_case('incomplete-prefix', 'upgrade', incomplete=True)
    run_case('incomplete-linked-prefix', 'upgrade', incomplete=True, linked_prefix=True)
    run_case('incomplete-busy-prefix', 'upgrade', incomplete=True, busy=True)
    run_case('upgrade-server-error', 'upgrade', server_error=2)
    run_case('arch-idle', 'arch')
    run_case('upgrade-invalid-locale', 'upgrade', invalid_locale=True)
    run_case('arch-invalid-locale', 'arch', invalid_locale=True)
    run_case('upgrade-no-chinese-locale', 'upgrade', missing_locale=True)
    run_case('arch-no-chinese-locale', 'arch', missing_locale=True)
    run_case('ubuntu-cef-ime-disabled', 'ubuntu', cef_ime='0')
    run_case('arch-cef-ime-opt-in', 'arch', cef_ime='1')
    run_case('arch-frame-cef-ime-opt-in', 'arch', cef_ime='1', owned_frame='1')
    run_case('ubuntu-native-with-old-bridge-setting', 'ubuntu', legacy_ime='1')
    run_case('ubuntu-explicit-legacy-ime', 'ubuntu', cef_ime='0', legacy_ime='1')
    run_case('arch-native-with-old-bridge-setting', 'arch', cef_ime='1', legacy_ime='1')
    run_case('ubuntu-mail-dpi-failure', 'ubuntu', failed_image='WeMail.exe')
    run_case('ubuntu-flutter-dpi-failure', 'ubuntu', failed_image='FlutterPlugins.exe')
    run_case('ubuntu-meeting-dpi-failure', 'ubuntu', failed_image='wwmapp.exe')
    run_case('upgrade-legacy-meeting-dpi', 'upgrade', meeting_dpi='0x0')
    run_case('upgrade-configured-meeting-dpi', 'upgrade', meeting_dpi='0x2')

print(json.dumps({'passed': True, 'host_desktop_used': False, 'cases': report}, indent=2))
