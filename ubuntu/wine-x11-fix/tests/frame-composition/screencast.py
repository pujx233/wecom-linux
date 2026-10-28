from contextlib import contextmanager
import json
import shutil
from pathlib import Path
import subprocess
import time

from gi.repository import Gio, GLib


@contextmanager
def recording(qa, env, run_name, interactive=False):
    connection = Gio.DBusConnection.new_for_address_sync(
        (qa / 'bus-address').read_text().strip(),
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
        None, None)

    def call(path, interface, method, arguments=None):
        service = 'org.gnome.Mutter.RemoteDesktop' if 'RemoteDesktop' in interface else 'org.gnome.Mutter.ScreenCast'
        return connection.call_sync(service, path, interface, method, arguments,
                                    None, Gio.DBusCallFlags.NONE, 5000, None)

    remote = None
    properties = {}
    if interactive:
        metadata = json.loads((qa / 'desktop.json').read_text())
        assert env['DISPLAY'] == metadata['display'] and env['XDG_RUNTIME_DIR'] == metadata['runtime']
        assert Path(f"/proc/{metadata['xwayland_pid']}/stat").read_text().split()[21] == metadata['xwayland_start']
        assert env['DBUS_SESSION_BUS_ADDRESS'] == metadata['bus']
        remote = call('/org/gnome/Mutter/RemoteDesktop', 'org.gnome.Mutter.RemoteDesktop', 'CreateSession').unpack()[0]
        session_id = connection.call_sync(
            'org.gnome.Mutter.RemoteDesktop', remote, 'org.freedesktop.DBus.Properties', 'Get',
            GLib.Variant('(ss)', ('org.gnome.Mutter.RemoteDesktop.Session', 'SessionId')),
            None, Gio.DBusCallFlags.NONE, 5000, None).unpack()[0]
        properties['remote-desktop-session-id'] = GLib.Variant('s', session_id)
    session = call('/org/gnome/Mutter/ScreenCast', 'org.gnome.Mutter.ScreenCast', 'CreateSession',
                   GLib.Variant('(a{sv})', (properties,))).unpack()[0]
    frames = qa / (run_name + '-frames')
    frames.mkdir()
    process = None
    complete = False
    output = (qa / (run_name + '-recording.log')).open('w')
    try:
        stream = call(session, 'org.gnome.Mutter.ScreenCast.Session', 'RecordMonitor',
                      GLib.Variant('(sa{sv})', ('', {'cursor-mode': GLib.Variant('u', 0)}))).unpack()[0]
        nodes = []
        connection.signal_subscribe('org.gnome.Mutter.ScreenCast', 'org.gnome.Mutter.ScreenCast.Stream',
                                    'PipeWireStreamAdded', stream, None, Gio.DBusSignalFlags.NONE,
                                    lambda conn, sender, path, iface, signal, args: nodes.append(args.unpack()[0]))
        if remote:
            call(remote, 'org.gnome.Mutter.RemoteDesktop.Session', 'Start')
        else:
            call(session, 'org.gnome.Mutter.ScreenCast.Session', 'Start')
        deadline = time.monotonic() + 5
        while not nodes and time.monotonic() < deadline:
            while GLib.MainContext.default().pending():
                GLib.MainContext.default().iteration(False)
            time.sleep(0.01)
        assert len(nodes) == 1, 'private monitor did not create a stream'
        process = subprocess.Popen(['gst-launch-1.0', '-q', 'pipewiresrc', 'path=' + str(nodes[0]),
                                    'client-name=wecom-qa-capture', '!', 'queue', 'max-size-buffers=1',
                                    'max-size-bytes=0', 'max-size-time=0', 'leaky=downstream',
                                    '!', 'videoconvert', '!', 'pngenc', 'compression-level=1',
                                    '!', 'multifilesink', 'max-files=2', 'location=' + str(frames / '%08d.png')],
                                   env=env, stdout=output, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 5
        linked = False
        while time.monotonic() < deadline:
            graph = json.loads(subprocess.check_output(['pw-dump'], env=env, text=True))
            clients = {o['id'] for o in graph if o['type'].endswith(':Client') and
                       str(o.get('info', {}).get('props', {}).get('application.process.id')) == str(process.pid)}
            targets = {o['id'] for o in graph if o['type'].endswith(':Node') and
                       int(o.get('info', {}).get('props', {}).get('client.id', -1)) in clients}
            outputs = [o['id'] for o in graph if o['type'].endswith(':Port') and
                       int(o['info']['props'].get('node.id', -1)) == nodes[0] and
                       o['info']['props'].get('port.direction') == 'out']
            inputs = [o['id'] for o in graph if o['type'].endswith(':Port') and
                      int(o['info']['props'].get('node.id', -1)) in targets and
                      o['info']['props'].get('port.direction') == 'in']
            if outputs and inputs:
                assert len(outputs) == len(inputs) == 1
                subprocess.run(['pw-link', str(outputs[0]), str(inputs[0])], env=env, check=True, timeout=3)
                linked = True
                break
            if process.poll() is not None:
                break
            time.sleep(0.05)
        assert linked, 'private capture ports did not become ready'

        def capture(target):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                assert process.poll() is None, 'capture pipeline stopped'
                paths = sorted(frames.glob('*.png'))
                if paths:
                    try:
                        data = paths[-1].read_bytes()
                    except FileNotFoundError:
                        continue
                    if data.endswith(b'IEND\xaeB`\x82'):
                        target.write_bytes(data)
                        return str(target)
                time.sleep(0.01)
            raise TimeoutError('no complete composed frame')

        if remote:
            def pointer(x, y):
                call(remote, 'org.gnome.Mutter.RemoteDesktop.Session', 'NotifyPointerMotionAbsolute',
                     GLib.Variant('(sdd)', (stream, float(x), float(y))))

            def button(pressed, code=272):
                call(remote, 'org.gnome.Mutter.RemoteDesktop.Session', 'NotifyPointerButton',
                     GLib.Variant('(ib)', (code, pressed)))

            capture.pointer = pointer
            capture.button = button
        capture(qa / (run_name + '-before.png'))
        yield capture
        complete = True
    finally:
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=3)
        output.close()
        if remote:
            call(remote, 'org.gnome.Mutter.RemoteDesktop.Session', 'Stop')
        else:
            call(session, 'org.gnome.Mutter.ScreenCast.Session', 'Stop')
        connection.close_sync(None)
        if complete:
            shutil.rmtree(frames)
