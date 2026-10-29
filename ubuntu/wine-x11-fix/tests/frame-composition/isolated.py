from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

from gi.repository import Gio, GLib


def processes(qa):
    marker = b'XDG_RUNTIME_DIR=' + os.fsencode(qa / 'runtime')
    result = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if marker in (entry / 'environ').read_bytes().split(b'\0'):
                result.append((int(entry.name), (entry / 'cmdline').read_bytes().split(b'\0')[:-1]))
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            pass
    return result


@contextmanager
def desktop(qa, size='1600x1000', bare=False, second_monitor=None):
    qa = qa.resolve()
    assert qa == Path(os.environ['WECOM_QA_ROOT']).resolve()
    assert (qa / '.wecom-frame-qa').is_file(), 'Use a marked, disposable QA directory'
    assert str(qa / 'runtime') != os.environ.get('XDG_RUNTIME_DIR')
    for directory in ('runtime', 'config', 'data', 'cache'):
        (qa / directory).mkdir(exist_ok=True)
    (qa / 'runtime').chmod(0o700)
    assert not processes(qa), 'another private test is running'
    assert size in ('1600x1000', '3200x2000')
    assert second_monitor in (None, '3840x2160')
    env = os.environ.copy()
    for name in ('DISPLAY', 'XAUTHORITY', 'WAYLAND_DISPLAY', 'DBUS_SESSION_BUS_ADDRESS', 'LD_PRELOAD',
                 'LD_LIBRARY_PATH', 'WINEDLLPATH', 'WINELOADER', 'WINELOADERNOEXEC', 'WINEARCH',
                 'WINESERVERSOCKET'):
        env.pop(name, None)
    env.update(XDG_RUNTIME_DIR=str(qa / 'runtime'), XDG_CONFIG_HOME=str(qa / 'config'),
               XDG_DATA_HOME=str(qa / 'data'), XDG_CACHE_HOME=str(qa / 'cache'),
               GSETTINGS_BACKEND='memory', LIBGL_ALWAYS_SOFTWARE='1', LP_NUM_THREADS='2',
               MESA_SHADER_CACHE_DISABLE='true', NO_AT_BRIDGE='1')
    shell_log = (qa / 'gnome-shell.log').open('a')
    pipewire_log = (qa / 'pipewire.log').open('a')
    shell = subprocess.Popen(['dbus-run-session', '--', sys.executable, str(Path(__file__).resolve()),
                              str(qa), '--bare' if bare else '--shell', size,
                              *([second_monitor] if second_monitor else [])],
                             env=env, stdout=shell_log, stderr=subprocess.STDOUT,
                             start_new_session=True)
    try:
        deadline = time.monotonic() + 30
        activated = set()
        while time.monotonic() < deadline:
            assert shell.poll() is None, 'private shell stopped during startup'
            current = processes(qa)
            xservers = [(pid, argv) for pid, argv in current if argv and
                        Path(os.fsdecode(argv[0])).name == 'Xwayland']
            if xservers:
                assert len(xservers) == 1
                pid, argv = xservers[0]
                argv = [os.fsdecode(arg) for arg in argv]
                display = next(arg for arg in argv if arg.startswith(':'))
                authority = Path(argv[argv.index('-auth') + 1])
                assert authority.is_relative_to(qa / 'runtime')
                if authority.exists():
                    env.update(DISPLAY=display, XAUTHORITY=str(authority), WAYLAND_DISPLAY='wecom-qa',
                               DBUS_SESSION_BUS_ADDRESS=(qa / 'bus-address').read_text().strip())
                    break
            shell_pids = {pid for pid, argv in current if argv and
                          (Path(os.fsdecode(argv[0])).name == 'gnome-shell' or
                           (b'--bare' in argv and os.fsencode(str(Path(__file__).resolve())) in argv))}
            for lock in Path('/tmp').glob('.X*-lock'):
                if lock in activated:
                    continue
                try:
                    owner_pid = int(lock.read_text().strip())
                except FileNotFoundError:
                    continue
                if owner_pid in shell_pids:
                    number = lock.name[2:-5]
                    with socket.socket(socket.AF_UNIX) as client:
                        client.settimeout(1)
                        client.connect('/tmp/.X11-unix/X' + number)
                    activated.add(lock)
            time.sleep(0.1)
        else:
            raise TimeoutError('private Xwayland did not start')
        metadata = dict(display=display, authority=str(authority), xwayland_pid=pid,
                        xwayland_start=Path(f'/proc/{pid}/stat').read_text().split()[21],
                        runtime=env['XDG_RUNTIME_DIR'], bus=env['DBUS_SESSION_BUS_ADDRESS'])
        (qa / 'desktop.json').write_text(json.dumps(metadata, indent=2) + '\n')
        if not bare:
            subprocess.Popen(['pipewire'], env=env, stdout=pipewire_log, stderr=subprocess.STDOUT,
                             start_new_session=True)
            connection = Gio.DBusConnection.new_for_address_sync(
                env['DBUS_SESSION_BUS_ADDRESS'],
                Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
                None, None)
            try:
                deadline = time.monotonic() + 20
                while True:
                    try:
                        values = connection.call_sync(
                            'org.gnome.Shell', '/org/gnome/Shell', 'org.freedesktop.DBus.Properties', 'GetAll',
                            GLib.Variant('(s)', ('org.gnome.Shell',)), None,
                            Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
                        if 'OverviewActive' in values:
                            break
                    except GLib.Error as error:
                        if Gio.DBusError.get_remote_error(error) not in (
                            'org.freedesktop.DBus.Error.UnknownMethod', 'org.freedesktop.DBus.Error.ServiceUnknown'):
                            raise
                    if time.monotonic() >= deadline:
                        raise TimeoutError('private Shell interface did not become ready')
                    time.sleep(0.1)
                connection.call_sync('org.gnome.Shell', '/org/gnome/Shell', 'org.freedesktop.DBus.Properties',
                                     'Set', GLib.Variant('(ssv)', ('org.gnome.Shell', 'OverviewActive',
                                                                  GLib.Variant('b', False))),
                                     None, Gio.DBusCallFlags.NONE, 5000, None)
            finally:
                connection.close_sync(None)
            deadline = time.monotonic() + 5
            while not (qa / 'runtime/pipewire-0').exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert (qa / 'runtime/pipewire-0').exists()
        prefix = qa / 'prefix'
        if not (prefix / 'system.reg').exists():
            boot_env = env | {'WINEPREFIX': str(prefix), 'WINESERVER': str(qa / 'wine/bin/wineserver'),
                              'DBUS_SYSTEM_BUS_ADDRESS': 'unix:path=' + str(qa / 'no-system-bus'),
                              'WINEDEBUG': '-all', 'WINEDLLOVERRIDES': 'mscoree,mshtml,winemenubuilder='}
            with (qa / 'wineboot.log').open('w') as log:
                subprocess.run([str(qa / 'wine/bin/wine'), 'wineboot.exe', '-u'],
                               env=boot_env, stdout=log, stderr=log, check=True, timeout=60)
        # The private compositor needs the host bus; Wine fixtures must not enumerate host Bluetooth devices.
        env['DBUS_SYSTEM_BUS_ADDRESS'] = 'unix:path=' + str(qa / 'no-system-bus')
        yield env
    finally:
        # Let Mutter close Xwayland; killing both at once can create a host crash dialog.
        for pid, argv in processes(qa):
            if not argv or Path(os.fsdecode(argv[0])).name != 'gnome-shell':
                continue
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            shell.wait(timeout=8)
        except subprocess.TimeoutExpired:
            pass
        for pid, argv in processes(qa):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        shell.wait(timeout=8)
        deadline = time.monotonic() + 2
        while processes(qa) and time.monotonic() < deadline:
            time.sleep(0.05)
        for pid, argv in processes(qa):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        shell_log.close()
        pipewire_log.close()
        (qa / 'desktop.json').unlink(missing_ok=True)


if __name__ == '__main__':
    qa = Path(sys.argv[1])
    assert sys.argv[2] in ('--shell', '--bare')
    (qa / 'bus-address').write_text(os.environ['DBUS_SESSION_BUS_ADDRESS'] + '\n')
    monitors = ['--virtual-monitor=' + size for size in sys.argv[3:]]
    if sys.argv[2] == '--shell':
        os.execlp('gnome-shell', 'gnome-shell', '--headless', '--wayland', *monitors,
                  '--wayland-display=wecom-qa')
    import gi
    repository = gi.Repository.get_default()
    repository.prepend_search_path('/usr/lib/x86_64-linux-gnu/mutter-18')
    repository.prepend_library_path('/usr/lib/x86_64-linux-gnu/mutter-18')
    gi.require_version('Meta', '18')
    from gi.repository import Meta

    class UnitTestPlugin(Meta.Plugin):
        __gtype_name__ = 'WeComUnitTestPlugin'

        def do_map(self, actor):
            actor.show()
            self.map_completed(actor)

        def do_minimize(self, actor):
            actor.hide()
            self.minimize_completed(actor)

        def do_unminimize(self, actor):
            actor.show()
            self.unminimize_completed(actor)

        def do_destroy(self, actor):
            self.destroy_completed(actor)

    context = Meta.create_context('WeCom isolated Wine unit tests')
    context.set_plugin_gtype(UnitTestPlugin.__gtype__)
    assert context.configure(['wecom-unit-tests', '--headless', '--wayland',
                              *monitors, '--wayland-display=wecom-qa'])[0]
    assert context.setup()
    assert context.start()
    assert context.run_main_loop()
