"""Check maximization and restoration on either side of the primary monitor."""
from datetime import datetime, timezone
import argparse
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
from screencast import recording

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--case', help='Run one case by its full name, such as negative-primary-overlapped')
args = parser.parse_args()
qa = Path(os.environ['WECOM_QA_ROOT']).resolve()
name = 'maximize-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
subprocess.run(['x86_64-w64-mingw32-gcc', '-O2', '-Wall', '-Wextra',
                str(Path(__file__).with_name('maximize.c')), '-o', str(qa / 'maximize.exe'),
                '-lgdi32', '-luser32'], check=True)
report = {'driver_sha256': hashlib.sha256((qa / 'wine/lib/wine/x86_64-unix/winex11.so').read_bytes()).hexdigest(),
          'win32u_sha256': hashlib.sha256((qa / 'wine/lib/wine/x86_64-unix/win32u.so').read_bytes()).hexdigest(),
          'account_data_used': False, 'main_desktop_used': False, 'cases': []}
x = C.CDLL('libX11.so.6')
x.XOpenDisplay.restype = C.c_void_p
x.XDefaultRootWindow.argtypes = [C.c_void_p]
x.XDefaultRootWindow.restype = C.c_ulong
x.XGetGeometry.argtypes = [C.c_void_p, C.c_ulong] + [C.c_void_p] * 7
x.XTranslateCoordinates.argtypes = [C.c_void_p, C.c_ulong, C.c_ulong, C.c_int, C.c_int] + [C.c_void_p] * 3
x.XCloseDisplay.argtypes = [C.c_void_p]
x.XInternAtom.argtypes = [C.c_void_p, C.c_char_p, C.c_int]
x.XInternAtom.restype = C.c_ulong
x.XGetWindowProperty.argtypes = [C.c_void_p, C.c_ulong, C.c_ulong, C.c_long, C.c_long, C.c_int,
                                 C.c_ulong] + [C.c_void_p] * 5
x.XFree.argtypes = [C.c_void_p]
x.XCreateSimpleWindow.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.c_int, C.c_uint, C.c_uint,
                                  C.c_uint, C.c_ulong, C.c_ulong]
x.XCreateSimpleWindow.restype = C.c_ulong
x.XChangeProperty.argtypes = [C.c_void_p, C.c_ulong, C.c_ulong, C.c_ulong, C.c_int, C.c_int,
                              C.c_void_p, C.c_int]
x.XMapWindow.argtypes = [C.c_void_p, C.c_ulong]
x.XDestroyWindow.argtypes = [C.c_void_p, C.c_ulong]
x.XFlush.argtypes = [C.c_void_p]
x.XSendEvent.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.c_long, C.c_void_p]
x.XSelectInput.argtypes = [C.c_void_p, C.c_ulong, C.c_long]
x.XPending.argtypes = [C.c_void_p]
x.XNextEvent.argtypes = [C.c_void_p, C.c_void_p]
x.XQueryPointer.argtypes = [C.c_void_p, C.c_ulong] + [C.c_void_p] * 7


class ClientMessage(C.Structure):
    _fields_ = [('type', C.c_int), ('serial', C.c_ulong), ('send_event', C.c_int), ('display', C.c_void_p),
                ('window', C.c_ulong), ('message_type', C.c_ulong), ('format', C.c_int), ('data', C.c_long * 5)]


class ConfigureEvent(C.Structure):
    _fields_ = [('type', C.c_int), ('serial', C.c_ulong), ('send_event', C.c_int), ('display', C.c_void_p),
                ('event', C.c_ulong), ('window', C.c_ulong), ('x', C.c_int), ('y', C.c_int),
                ('width', C.c_int), ('height', C.c_int), ('border_width', C.c_int),
                ('above', C.c_ulong), ('override_redirect', C.c_int)]

with desktop(qa, '3200x2000', second_monitor='3840x2160') as env:
    connection = Gio.DBusConnection.new_for_address_sync(
        env['DBUS_SESSION_BUS_ADDRESS'],
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
        None, None)
    env.update(WINEPREFIX=str(qa / 'prefix'), WINESERVER=str(qa / 'wine/bin/wineserver'),
               WINE_X11_FRAME_ATTACHED_CLASSES='MaximizeRegressionShadow',
               WINE_X11_FRAME_DECORATION_CLASSES='MaximizeRegressionShadow',
               WINEDEBUG='-all', WINEDLLOVERRIDES='winewayland.drv=d;mscoree,mshtml,winemenubuilder=')
    wine, server = str(qa / 'wine/bin/wine'), str(qa / 'wine/bin/wineserver')
    saved = os.environ.get('XAUTHORITY')
    os.environ['XAUTHORITY'] = env['XAUTHORITY']
    display = x.XOpenDisplay(env['DISPLAY'].encode())
    if saved is None: os.environ.pop('XAUTHORITY')
    else: os.environ['XAUTHORITY'] = saved
    assert display
    root = x.XDefaultRootWindow(display)
    wm_state = x.XInternAtom(display, b'WM_STATE', True)
    active_window = x.XInternAtom(display, b'_NET_ACTIVE_WINDOW', False)
    docks = []

    def native_rect(window, origin):
        parent, child = C.c_ulong(), C.c_ulong()
        px, py = C.c_int(), C.c_int()
        width, height, border, depth = [C.c_uint() for _ in range(4)]
        assert x.XGetGeometry(display, window, C.byref(parent), C.byref(px), C.byref(py),
                              C.byref(width), C.byref(height), C.byref(border), C.byref(depth))
        assert x.XTranslateCoordinates(display, window, root, 0, 0, C.byref(px), C.byref(py), C.byref(child))
        left, top = px.value + origin[0], py.value + origin[1]
        return [left, top, left + width.value, top + height.value]

    def native_property(window, atom):
        kind, count, remaining = C.c_ulong(), C.c_ulong(), C.c_ulong()
        bits = C.c_int()
        data = C.c_void_p()
        assert x.XGetWindowProperty(display, window, atom, 0, 2, False, 0,
                                    C.byref(kind), C.byref(bits), C.byref(count),
                                    C.byref(remaining), C.byref(data)) == 0
        result = C.cast(data, C.POINTER(C.c_ulong))[0] if data and bits.value == 32 and count.value else None
        if data: x.XFree(data)
        return result

    def stop():
        # -k returns 1 when this private prefix has no server to stop.
        result = subprocess.run([server, '-k'], env=env, timeout=15)
        assert result.returncode in (0, 1), result.returncode
        subprocess.run([server, '-w'], env=env, check=True, timeout=15)

    def display_call(method, arguments=None):
        return connection.call_sync('org.gnome.Mutter.DisplayConfig', '/org/gnome/Mutter/DisplayConfig',
                                    'org.gnome.Mutter.DisplayConfig', method, arguments, None,
                                    Gio.DBusCallFlags.NONE, 10000, None).unpack()

    try:
        subprocess.run([wine, 'reg', 'add', r'HKCU\Control Panel\Desktop', '/v', 'LogPixels',
                        '/t', 'REG_DWORD', '/d', '192', '/f'], env=env, check=True, timeout=20)
        for primary_right in (True, False):
            stop()
            config = display_call('GetCurrentState')
            outputs = []
            for spec, modes, properties in config[1]:
                mode = next(mode for mode in modes if mode[6].get('is-current'))
                outputs.append((mode[1], spec[0], mode[0]))
            outputs.sort()
            assert [output[0] for output in outputs] == [3200, 3840]
            logical = [(0, 0, 2.0, 0, not primary_right, [(outputs[0][1], outputs[0][2], {})]),
                       (1600, 0, 2.0, 0, primary_right, [(outputs[1][1], outputs[1][2], {})])]
            display_call('ApplyMonitorsConfig', GLib.Variant('(uua(iiduba(ssa{sv}))a{sv})',
                                                           (config[0], 1, logical, {})))
            if not docks:
                # Reserve a bottom panel through the WM, so maximization does not become fullscreen.
                for left, top, width, bottom in ((0, 1898, 3200, 262), (3200, 2058, 3840, 102)):
                    dock = x.XCreateSimpleWindow(display, root, left, top, width, 102, 0, 0, 0x202020)
                    docks.append(dock)
                    kind = C.c_ulong(x.XInternAtom(display, b'_NET_WM_WINDOW_TYPE_DOCK', False))
                    x.XChangeProperty(display, dock, x.XInternAtom(display, b'_NET_WM_WINDOW_TYPE', False),
                                      4, 32, 0, C.byref(kind), 1)
                    struts = (C.c_ulong * 12)(0, 0, 0, bottom, 0, 0, 0, 0, 0, 0, left, left + width - 1)
                    x.XChangeProperty(display, dock, x.XInternAtom(display, b'_NET_WM_STRUT_PARTIAL', False),
                                      6, 32, 0, struts, 12)
                    x.XMapWindow(display, dock)
                x.XFlush(display)
            time.sleep(.5)
            cases = [('secondary-shadow', 0, 1, 0, '1', 0, 0), ('primary-shadow', 1, 1, 0, '1', 0, 0)]
            if primary_right:
                cases += [('secondary-boundary', 0, 1, 0, '1', 1, 0), ('disabled', 0, 1, 0, '0', 0, 0),
                          ('primary-disabled', 1, 1, 0, '0', 0, 0), ('no-shadow', 0, 0, 0, '1', 0, 0),
                          ('secondary-overlapped', 0, 1, 0, '1', 0, 1),
                          ('primary-overlapped', 1, 1, 0, '1', 0, 1),
                          ('secondary-offset', 0, 1, 2, '1', 0, 1),
                          ('default-limits', 0, 1, 1, '1', 0, 0)]
            for case_name, primary, shadow, defaults, frame, boundary, overlapped in cases:
                label = ('negative-' if primary_right else 'positive-') + case_name
                if args.case and args.case != label:
                    continue
                stop()
                test_minimize = primary_right and case_name in (
                    'secondary-shadow', 'primary-shadow', 'primary-disabled',
                    'secondary-overlapped', 'primary-overlapped')
                case = {'name': label, 'shared_frame': frame == '1', 'shadow': bool(shadow),
                        'default_limits': defaults == 1, 'custom_offset': defaults == 2, 'gating': defaults != 1,
                        'minimize_restore': test_minimize, 'overlapped': bool(overlapped),
                        'native_mapped': True, 'samples': []}
                report['cases'].append(case)
                with (qa / (name + '-' + label + '.log')).open('w') as log:
                    app = subprocess.Popen([wine, str(qa / 'maximize.exe'), str(primary), str(shadow),
                                            str(defaults), str(boundary), str(overlapped)],
                                           env=env | {'WINE_X11_OWNED_FRAME': frame,
                                                      'WINEDEBUG': os.environ.get('QA_WINEDEBUG', '-all,+x11drv')},
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                                           text=True, bufsize=1)
                    lines = queue.Queue()

                    def read():
                        for line in app.stdout: lines.put(json.loads(line))

                    reader = threading.Thread(target=read, daemon=True)
                    reader.start()
                    frame_limit = None
                    frame_min_size = None
                    watching_frame = 0

                    def command(value):
                        app.stdin.write(value + '\n')
                        app.stdin.flush()

                    def sample(phase, maximized, expected=None, minimized=False):
                        deadline = time.monotonic() + 3
                        stable = None
                        configures = []
                        visible_configures = []
                        configure_events = []
                        while True:
                            command('state')
                            value = lines.get(timeout=5)
                            assert value['event'] == 'state', value
                            body = native_rect(value['body'], ready['virtual_origin'])
                            frame_rect = native_rect(value['frame'], ready['virtual_origin'])
                            shadow_rect = None
                            frame_matches = frame_rect == body
                            if value['shadow_visible'] and value['shadow'] and case['shared_frame']:
                                shadow_rect = native_rect(value['shadow'], ready['virtual_origin'])
                                bounds = [min(body[i], shadow_rect[i]) for i in (0, 1)]
                                bounds += [max(body[i], shadow_rect[i]) for i in (2, 3)]
                                frame_matches = frame_rect == bounds and shadow_rect == value['shadow_rect']
                            host_state = native_property(value['frame'], wm_state)
                            event = (C.c_long * 24)()
                            while x.XPending(display):
                                x.XNextEvent(display, C.byref(event))
                                configure = ConfigureEvent.from_buffer(event)
                                if configure.window != watching_frame:
                                    continue
                                if configure.type in (18, 19):
                                    case['native_mapped'] = configure.type == 19
                                elif configure.type == 22:
                                    configures.append([configure.width, configure.height])
                                    configure_events.append(dict(size=configures[-1],
                                                                 synthetic=bool(configure.send_event),
                                                                 serial=configure.serial, mapped=case['native_mapped']))
                                    if case['native_mapped']:
                                        visible_configures.append(configures[-1])
                            bounds_ok = not maximized or frame_limit is None or all(
                                size[0] <= frame_limit[0] and size[1] <= frame_limit[1]
                                for size in visible_configures)
                            if not maximized and not minimized and frame_min_size is not None:
                                bounds_ok &= all(size[0] >= frame_min_size[0] and size[1] >= frame_min_size[1]
                                                 for size in visible_configures)
                            monitor = ready['monitor']
                            center = [(frame_rect[i] + frame_rect[i + 2]) / 2 for i in (0, 1)]
                            passed = (value['selected_monitor'] and not value['minimized'] and host_state == 1 and
                                      bool(value['maximized']) == maximized and frame_matches and
                                      not value['proposal_wrong_monitor'] and bounds_ok and
                                      (body == value['rect'] or defaults == 1 and maximized) and
                                      frame_rect[0] <= body[0] <= body[2] <= frame_rect[2] and
                                      frame_rect[1] <= body[1] <= body[3] <= frame_rect[3] and
                                      monitor[0] <= center[0] < monitor[2] and
                                      monitor[1] <= center[1] < monitor[3] and
                                      (expected is None or value['rect'] == expected))
                            if phase == 'maximized' and defaults == 2:
                                passed = passed and value['first_proposal'][:2] == [
                                    ready['work'][0] + 23, ready['work'][1] + 17]
                            if minimized:
                                passed = value['minimized'] and host_state == 3
                            if passed:
                                if stable is None: stable = time.monotonic()
                                passed = time.monotonic() - stable >= .4
                                if passed: break
                            else:
                                stable = None
                            if time.monotonic() >= deadline: break
                            time.sleep(.1)
                        result = dict(phase=phase, win32=value, native_body=body, native_frame=frame_rect,
                                      native_shadow=shadow_rect, native_state=host_state,
                                      configures=configures, visible_configures=visible_configures,
                                      configure_events=configure_events,
                                      frame_limit=frame_limit, frame_min_size=frame_min_size, passed=bool(passed))
                        case['samples'].append(result)
                        return value

                    try:
                        ready = lines.get(timeout=20)
                        assert ready['event'] == 'ready', ready
                        assert ready['work'][3] == ready['monitor'][3] - 102, ready
                        case['ready'] = ready
                        initial = sample('normal', False)
                        initial_frame = case['samples'][-1]['native_frame']
                        frame_min_size = [initial['rect'][i + 2] - initial['rect'][i] for i in (0, 1)]
                        extra = [initial_frame[i + 2] - initial_frame[i] - initial['rect'][i + 2] +
                                 initial['rect'][i] for i in (0, 1)]
                        extra = [max(value, 16 if shadow and frame == '1' else 0) for value in extra]
                        if defaults == 2:
                            extra = [extra[0] + 23, extra[1] + 17]
                        frame_limit = [max(initial_frame[i + 2] - initial_frame[i],
                                           ready['work'][i + 2] - ready['work'][i] + extra[i]) for i in (0, 1)]
                        watching_frame = initial['frame']
                        x.XSelectInput(display, watching_frame, 1 << 17)
                        x.XFlush(display)
                        command('maximize')
                        sample('maximized', True, None if defaults == 1 else ready['work'])
                        if test_minimize:
                            command('restore')
                            sample('restore-direct', False, initial['rect'])
                            command('maximize')
                            sample('maximized-before-minimize', True, ready['work'])
                            command('iconify')
                            sample('minimized', False, minimized=True)
                            command('restore')
                            sample('restore-maximized', True, ready['work'])
                            command('cycle')
                            sample('rapid-restore-maximized', True, ready['work'])
                        command('restore')
                        sample('restored', False, initial['rect'])
                        if test_minimize:
                            command('iconify')
                            sample('minimized-normal', False, minimized=True)
                            command('restore')
                            sample('restore-normal-after-minimize', False, initial['rect'])
                            command('cycle')
                            sample('rapid-restore-normal', False, initial['rect'])
                        if case_name in ('secondary-overlapped', 'primary-overlapped'):
                            command('maximize')
                            sample('maximized-before-activation', True, ready['work'])
                            command('iconify')
                            value = sample('minimized-before-activation', False, minimized=True)
                            event = (C.c_long * 24)()
                            message = ClientMessage.from_buffer(event)
                            message.type, message.send_event, message.display = 33, True, display
                            message.window, message.message_type, message.format = value['frame'], active_window, 32
                            message.data[0] = 2
                            assert x.XSendEvent(display, root, False, (1 << 19) | (1 << 20), C.byref(event))
                            x.XFlush(display)
                            sample('host-restore-before-callback', True, ready['work'])
                            command('activate-restore')
                            value = sample('restore-after-native-activation', True, ready['work'])
                            result = case['samples'][-1]
                            result['native_active'] = native_property(root, active_window)
                            result['passed'] &= result['native_active'] == value['frame']
                            command('restore')
                            sample('restore-normal-after-activation', False, initial['rect'])
                        if case_name == 'primary-overlapped':
                            command('maximize')
                            value = sample('maximized-before-drag', True, ready['work'])
                            with recording(qa, env, name + '-drag', interactive=True) as capture:
                                start = [1000, ready['work'][1] - ready['monitor'][1] + 24]
                                expected_pointer = [ready['monitor'][i] - ready['virtual_origin'][i] +
                                                    start[i] for i in (0, 1)]
                                deadline = time.monotonic() + 3
                                while True:
                                    capture.pointer(*start)
                                    time.sleep(.05)
                                    r, child = C.c_ulong(), C.c_ulong()
                                    px, py, wx, wy = [C.c_int() for _ in range(4)]
                                    mask = C.c_uint()
                                    assert x.XQueryPointer(display, root, C.byref(r), C.byref(child), C.byref(px),
                                                           C.byref(py), C.byref(wx), C.byref(wy), C.byref(mask))
                                    if [px.value, py.value] == expected_pointer and child.value == value['frame']:
                                        break
                                    assert time.monotonic() < deadline, ([px.value, py.value], expected_pointer)
                                    time.sleep(.05)
                                capture.button(True)
                                try:
                                    for step in range(1, 61):
                                        capture.pointer(start[0] + 250 * step / 60, start[1] + 280 * step / 60)
                                        time.sleep(.016)
                                finally:
                                    capture.button(False)
                                moved = sample('drag-restored', False)
                                result = case['samples'][-1]
                                result['passed'] &= all(moved['rect'][i + 2] - moved['rect'][i] ==
                                                        initial['rect'][i + 2] - initial['rect'][i] for i in (0, 1))
                                result['passed'] &= moved['rect'] != initial['rect']
                                result['screenshot'] = capture(qa / (name + '-drag-after.png'))
                        case['passed'] = all(item['passed'] for item in case['samples'])
                        print(json.dumps(case), flush=True)
                    finally:
                        if app.poll() is None:
                            command('quit')
                            app.wait(timeout=10)
                        reader.join(timeout=2)
    finally:
        stop()
        for dock in docks: x.XDestroyWindow(display, dock)
        x.XCloseDisplay(display)
        connection.close_sync(None)

assert report['cases'], 'No matching test cases'
report['passed'] = all(case['passed'] for case in report['cases'] if case['gating'])
path = qa / (name + '.json')
path.write_text(json.dumps(report, indent=2) + '\n')
print(path)
raise SystemExit(0 if report['passed'] else 1)
