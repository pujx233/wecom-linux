"""Keep framed windows alive while removing the primary output from a private GNOME desktop."""
from datetime import datetime, timezone
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

from gi.repository import Gio, GLib
from isolated import desktop

qa = Path(os.environ['WECOM_QA_ROOT']).resolve()
name = 'display-removal-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
exe = qa / (name + '.exe')
subprocess.run(['x86_64-w64-mingw32-gcc', '-O2', '-Wall', '-Wextra', '-Werror',
                str(Path(__file__).with_name('display-removal.c')), '-o', str(exe),
                '-lgdi32', '-luser32', '-ladvapi32'],
               check=True)
pending = os.environ.get('WECOM_HOTPLUG_PENDING', '')
assert pending in ('', 'resize', 'move', 'update')
minimized = os.environ.get('WECOM_HOTPLUG_MINIMIZED') == '1'
assert not (pending and minimized)
report = {'host_desktop_used': False, 'account_data_used': False, 'samples': [], 'runtime': {},
          'pending': pending, 'minimized': minimized}
for module in ('winex11.so', 'win32u.so'):
    report['runtime'][module] = hashlib.sha256((qa / 'wine/lib/wine/x86_64-unix' / module).read_bytes()).hexdigest()
with desktop(qa, '3200x2000', second_monitor='3840x2160') as env:
    connection = Gio.DBusConnection.new_for_address_sync(
        env['DBUS_SESSION_BUS_ADDRESS'],
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
    env.update(WINEPREFIX=str(qa / 'prefix'), WINESERVER=str(qa / 'wine/bin/wineserver'),
               WINEDEBUG='-all,+x11drv,+display', WINE_X11_OWNED_FRAME='1',
               WINE_X11_FRAME_ATTACHED_CLASSES='DisplayRemovalShadow',
               WINE_X11_FRAME_DECORATION_CLASSES='DisplayRemovalShadow',
               WINE_WECOM_FIRST_PRESENT_ARGB='1',
               WINEDLLOVERRIDES='winewayland.drv=d;mscoree,mshtml,winemenubuilder=')
    wine, server = str(qa / 'wine/bin/wine'), str(qa / 'wine/bin/wineserver')
    x = C.CDLL('libX11.so.6')
    x.XOpenDisplay.argtypes = [C.c_char_p]; x.XOpenDisplay.restype = C.c_void_p
    x.XDefaultRootWindow.argtypes = [C.c_void_p]; x.XDefaultRootWindow.restype = C.c_ulong
    x.XGetGeometry.argtypes = [C.c_void_p, C.c_ulong] + [C.c_void_p] * 7
    x.XTranslateCoordinates.argtypes = [C.c_void_p, C.c_ulong, C.c_ulong, C.c_int, C.c_int] + [C.c_void_p] * 3
    x.XCloseDisplay.argtypes = [C.c_void_p]
    x.XFree.argtypes = [C.c_void_p]
    x.XInternAtom.argtypes = [C.c_void_p, C.c_char_p, C.c_int]; x.XInternAtom.restype = C.c_ulong
    x.XGetWindowProperty.argtypes = [C.c_void_p, C.c_ulong, C.c_ulong, C.c_long, C.c_long, C.c_int,
                                    C.c_ulong, C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p]
    shape = C.CDLL('libXext.so.6')

    class Rectangle(C.Structure):
        _fields_ = [('x', C.c_short), ('y', C.c_short), ('width', C.c_ushort), ('height', C.c_ushort)]

    shape.XShapeGetRectangles.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.c_void_p, C.c_void_p]
    shape.XShapeGetRectangles.restype = C.POINTER(Rectangle)
    saved = os.environ.get('XAUTHORITY'); os.environ['XAUTHORITY'] = env['XAUTHORITY']
    display = x.XOpenDisplay(env['DISPLAY'].encode())
    if saved is None: os.environ.pop('XAUTHORITY')
    else: os.environ['XAUTHORITY'] = saved
    assert display
    root = x.XDefaultRootWindow(display)

    def wm_state(window):
        kind, count, remaining = C.c_ulong(), C.c_ulong(), C.c_ulong()
        bits, value = C.c_int(), C.c_void_p()
        atom = x.XInternAtom(display, b'WM_STATE', False)
        assert not x.XGetWindowProperty(display, window, atom, 0, 2, False, atom, C.byref(kind), C.byref(bits),
                                        C.byref(count), C.byref(remaining), C.byref(value))
        state = C.cast(value, C.POINTER(C.c_ulong))[0] if count.value else None
        if value: x.XFree(value)
        return state

    def native_activate(window):
        class ClientMessage(C.Structure):
            _fields_ = [('type', C.c_int), ('serial', C.c_ulong), ('send_event', C.c_int),
                        ('display', C.c_void_p), ('window', C.c_ulong), ('message_type', C.c_ulong),
                        ('format', C.c_int), ('data', C.c_long * 5)]

        class Event(C.Union):
            _fields_ = [('client', ClientMessage), ('padding', C.c_long * 24)]

        x.XSendEvent.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.c_long, C.POINTER(Event)]
        x.XSync.argtypes = [C.c_void_p, C.c_int]
        event = Event()
        event.client = ClientMessage(33, 0, True, display, window,
                                     x.XInternAtom(display, b'_NET_ACTIVE_WINDOW', False), 32,
                                     (C.c_long * 5)(2, 0, 0, 0, 0))
        assert x.XSendEvent(display, root, False, (1 << 19) | (1 << 20), C.byref(event))
        x.XSync(display, False)

    def display_call(method, arguments=None):
        return connection.call_sync('org.gnome.Mutter.DisplayConfig', '/org/gnome/Mutter/DisplayConfig',
                                     'org.gnome.Mutter.DisplayConfig', method, arguments, None,
                                     Gio.DBusCallFlags.NONE, 10000, None).unpack()

    def configure(single=False, primary_right=True):
        current = display_call('GetCurrentState')
        outputs = []
        for spec, modes, properties in current[1]:
            mode = next((m for m in modes if m[6].get('is-current')), modes[0])
            outputs.append((mode[1], spec[0], mode[0]))
        outputs.sort()
        assert [o[0] for o in outputs] == [3200, 3840], outputs
        logical = [(0, 0, 2.0, 0, single or not primary_right, [(outputs[0][1], outputs[0][2], {})])]
        if not single:
            logical.append((1600, 0, 2.0, 0, primary_right, [(outputs[1][1], outputs[1][2], {})]))
        display_call('ApplyMonitorsConfig', GLib.Variant('(uua(iiduba(ssa{sv}))a{sv})',
                                                       (current[0], 1, logical, {})))

    def geometry(window):
        parent, child = C.c_ulong(), C.c_ulong()
        px, py = C.c_int(), C.c_int()
        width, height, border, depth = [C.c_uint() for _ in range(4)]
        assert window and x.XGetGeometry(display, window, C.byref(parent), C.byref(px), C.byref(py),
                                         C.byref(width), C.byref(height), C.byref(border), C.byref(depth))
        assert x.XTranslateCoordinates(display, window, root, 0, 0, C.byref(px), C.byref(py), C.byref(child))
        return [px.value, py.value, px.value + width.value, py.value + height.value]

    def shapes(window):
        result = {}
        for kind, label in ((0, 'bounding'), (1, 'clip')):
            count, ordering = C.c_int(), C.c_int()
            rectangles = shape.XShapeGetRectangles(display, window, kind, C.byref(count), C.byref(ordering))
            result[label] = [[r.x, r.y, r.width, r.height] for r in rectangles[:count.value]]
            if rectangles: x.XFree(rectangles)
        return result

    app = None
    try:
        configure()
        with (qa / (name + '-registry.log')).open('w') as log:
            subprocess.run([wine, 'reg', 'add', r'HKCU\Control Panel\Desktop', '/v', 'LogPixels', '/t',
                            'REG_DWORD', '/d', '192', '/f'], env=env, stdout=log, stderr=log, check=True, timeout=20)
        subprocess.run([server, '-k'], env=env, timeout=15)
        subprocess.run([server, '-w'], env=env, check=True, timeout=15)
        lines = queue.Queue()
        with (qa / (name + '.log')).open('w') as log:
            app = subprocess.Popen([wine, str(exe)], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=log, text=True)

            def read():
                for line in app.stdout: lines.put(json.loads(line))
                lines.put(None)

            threading.Thread(target=read, daemon=True).start()
            ready = lines.get(timeout=20)
            report['ready'] = ready
            assert ready, 'fixture exited before publishing display state'

            def command(value):
                app.stdin.write(value + '\n'); app.stdin.flush()

            def sample(stage):
                command('s'); state = lines.get(timeout=5)
                assert state
                value = {'stage': stage, 'time': time.monotonic(), 'win32': state, 'native': {}}
                origin = state['origin']
                for key in ('main', 'shadow', 'helper'):
                    body = geometry(state[key]['body'])
                    expected = [v - origin[i % 2] for i, v in enumerate(state[key]['rect'])]
                    value['native'][key] = {'body': body, 'expected': expected, 'matches': body == expected,
                                            'frame': geometry(state[key]['frame']),
                                            'body_shape': shapes(state[key]['body']),
                                            'frame_shape': shapes(state[key]['frame'])}
                value['main_wm_state'] = wm_state(state['main']['frame'])
                report['samples'].append(value)
                return value

            time.sleep(.5)
            report['before'] = sample('dual')
            if minimized:
                command('i'); time.sleep(.3)
                report['minimized_before'] = sample('minimized-before')
                assert report['minimized_before']['main_wm_state'] == 3
                assert report['minimized_before']['win32']['main']['iconic']
            configure(primary_right=False); time.sleep(.5)
            report['primary_left'] = sample('primary-left')
            configure(); time.sleep(.5)
            report['primary_right'] = sample('primary-right')
            if pending:
                command('l'); time.sleep(.3)
                report['pending_before'] = sample('pending-before')
                command({'resize': 'b', 'move': 'p', 'update': 'v'}[pending])
                report['pending_requested'] = lines.get(timeout=5)
                assert report['pending_requested']
            configure(True)
            if pending:
                time.sleep(.3)
                command('u')
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                sample('removal'); time.sleep(.05)
            if minimized:
                report['minimized_after'] = sample('minimized-after')
                native_activate(report['minimized_after']['win32']['main']['frame']); time.sleep(.5)
            report['after'] = sample('single')
            command('e'); time.sleep(.3)
            report['same_position'] = sample('same-position')
            command('n'); time.sleep(.3)
            report['one_pixel_move'] = sample('one-pixel-move')
            command('q'); app.wait(timeout=10)
        report['geometry_passed'] = (report['after']['win32']['monitors'] == 1 and
                                     report['after']['win32']['origin'] == [0, 0] and
                                     report['after']['main_wm_state'] == 1 and
                                     not report['after']['win32']['main']['iconic'] and
                                     all(window['matches'] for window in report['after']['native'].values()))
        topology = [('before', [-3200, 0, 3840, 2160]), ('primary_left', [0, 0, 7040, 2160]),
                    ('primary_right', [-3200, 0, 3840, 2160]), ('after', [0, 0, 3200, 2000])]
        targets = []
        valid = True
        for label, raw in topology:
            state = report[label]['win32']
            bindings = state['bindings']
            targets.append(next((entry['target'] for entry in bindings if entry['device'] == r'\Device\Video0'), ''))
            valid &= bool(bindings) and all(entry['monitor_exists'] for entry in bindings)
            valid &= state['raw_rect'] == raw and len(state['enumerated_monitors']) == (1 if label == 'after' else 2)
            valid &= all(monitor['handle'] and monitor['device'] != 'WinDisc'
                         for monitor in state['enumerated_monitors'])
        report['index_zero_targets'] = targets
        report['index_rebound'] = bool(all(targets)) and targets[0] != targets[1] and targets[0] != targets[3]
        report['bindings_passed'] = bool(valid and report['index_rebound'])
        report['pending_passed'] = True
        if pending:
            requested = report['pending_requested']
            origin = requested['origin']
            expected = [value - origin[i % 2] for i, value in enumerate(requested['main']['rect'])]
            report['pending_expected'] = expected
            report['pending_passed'] = report['after']['native']['main']['body'] == expected
        report['passed'] = report['geometry_passed'] and report['bindings_passed'] and report['pending_passed']
    except Exception as error:
        report['error'] = repr(error)
        report['passed'] = False
    finally:
        if app and app.poll() is None:
            app.stdin.write('q\n'); app.stdin.flush(); app.wait(timeout=10)
        subprocess.run([server, '-k'], env=env, timeout=15)
        subprocess.run([server, '-w'], env=env, check=True, timeout=15)
        x.XCloseDisplay(display)
        connection.close_sync(None)
path = qa / (name + '.json')
path.write_text(json.dumps(report, indent=2) + '\n')
print(path)
print(json.dumps({key: report.get(key) for key in ('passed', 'error', 'before', 'after', 'same_position',
                                                  'one_pixel_move')}))
raise SystemExit(0 if report['passed'] else 1)
