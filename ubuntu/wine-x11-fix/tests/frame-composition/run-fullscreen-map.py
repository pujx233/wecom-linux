"""Check first-map and remap fullscreen requests on a private, two-output desktop."""
import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import threading
import time

from isolated import desktop, processes

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--display-change', action='store_true', help='Change monitor layout in the same Wine process')
parser.add_argument('--host-reply', action='store_true', help='Deliver the WM initial size before its span reply')
args = parser.parse_args()
if args.host_reply and args.display_change:
    parser.error('--host-reply and --display-change use separate fixture handshakes')
qa = Path(os.environ['WECOM_QA_ROOT']).resolve()
runtime = qa / 'wine'
source = Path(__file__).with_name('fullscreen-map.c')
subprocess.run(['x86_64-w64-mingw32-gcc', '-O2', '-Wall', '-Wextra', '-Werror',
                str(source), '-o', str(qa / 'fullscreen-map.exe'), '-lgdi32', '-luser32'], check=True)
if args.host_reply:
    subprocess.run(['cc', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                    str(Path(__file__).with_name('fullscreen-host-reply.c')),
                    '-o', str(qa / 'fullscreen-host-reply.so'), '-ldl', '-lX11'], check=True)
x = C.CDLL('libX11.so.6')
x.XOpenDisplay.argtypes = [C.c_char_p]
x.XOpenDisplay.restype = C.c_void_p
x.XDefaultRootWindow.argtypes = [C.c_void_p]
x.XDefaultRootWindow.restype = C.c_ulong
x.XInternAtom.argtypes = [C.c_void_p, C.c_char_p, C.c_int]
x.XInternAtom.restype = C.c_ulong
x.XSelectInput.argtypes = [C.c_void_p, C.c_ulong, C.c_long]
x.XSync.argtypes = [C.c_void_p, C.c_int]
x.XPending.argtypes = [C.c_void_p]
x.XNextEvent.argtypes = [C.c_void_p, C.c_void_p]
x.XCloseDisplay.argtypes = [C.c_void_p]
x.XGetGeometry.argtypes = [C.c_void_p, C.c_ulong] + [C.c_void_p] * 7
x.XTranslateCoordinates.argtypes = [C.c_void_p, C.c_ulong, C.c_ulong, C.c_int, C.c_int] + [C.c_void_p] * 3


class ClientMessage(C.Structure):
    _fields_ = [('type', C.c_int), ('serial', C.c_ulong), ('send_event', C.c_int), ('display', C.c_void_p),
                ('window', C.c_ulong), ('message_type', C.c_ulong), ('format', C.c_int), ('data', C.c_long * 5)]


messages = []
checks = []
intermediate_replies = []
loaded_drivers = set()
with desktop(qa, '1920x1080', second_monitor='2560x1440') as env:
    from gi.repository import Gio, GLib
    connection = Gio.DBusConnection.new_for_address_sync(
        env['DBUS_SESSION_BUS_ADDRESS'],
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
        None, None)

    def layout(vertical, primary_right):
        service = 'org.gnome.Mutter.DisplayConfig'
        path = '/org/gnome/Mutter/DisplayConfig'
        config = connection.call_sync(service, path, service, 'GetCurrentState', None, None,
                                      Gio.DBusCallFlags.NONE, 10000, None).unpack()
        outputs = []
        for spec, modes, properties in config[1]:
            mode = next(mode for mode in modes if mode[6].get('is-current'))
            outputs.append((mode[1], mode[2], spec[0], mode[0]))
        outputs.sort()
        first, second = outputs
        logical = [(0, 0, 1.0, 0, not primary_right, [(first[2], first[3], {})]),
                   (0 if vertical else first[0], first[1] if vertical else 0, 1.0, 0, primary_right,
                    [(second[2], second[3], {})])]
        connection.call_sync(service, path, service, 'ApplyMonitorsConfig',
                             GLib.Variant('(uua(iiduba(ssa{sv}))a{sv})', (config[0], 1, logical, {})), None,
                             Gio.DBusCallFlags.NONE, 10000, None)

    env.update(WINEPREFIX=str(qa / 'prefix'), WINESERVER=str(runtime / 'bin/wineserver'), WINEDEBUG='-all',
               WINEDLLOVERRIDES='winewayland.drv=d;mscoree,mshtml,winemenubuilder=')
    wm_pid = None
    if args.host_reply:
        private_wm = [pid for pid, argv in processes(qa)
                      if argv and Path(os.fsdecode(argv[0])).name == 'gnome-shell']
        assert len(private_wm) == 1, private_wm
        wm_pid = private_wm[0]
        env.update(LD_PRELOAD=str(qa / 'fullscreen-host-reply.so'), WECOM_QA_WM_PID=str(wm_pid),
                   WINE_X11_OWNED_FRAME='0')
    old_auth = os.environ.get('XAUTHORITY')
    os.environ['XAUTHORITY'] = env['XAUTHORITY']
    display = x.XOpenDisplay(env['DISPLAY'].encode())
    if old_auth is None: os.environ.pop('XAUTHORITY')
    else: os.environ['XAUTHORITY'] = old_auth
    assert display
    try:
        atom = x.XInternAtom(display, b'_NET_WM_FULLSCREEN_MONITORS', False)
        root = x.XDefaultRootWindow(display)
        x.XSelectInput(display, root, 1 << 19)
        x.XSync(display, False)

        def native_geometry(row):
            parent, child = C.c_ulong(), C.c_ulong()
            px, py = C.c_int(), C.c_int()
            width, height, border, depth = [C.c_uint() for _ in range(4)]
            assert x.XGetGeometry(display, row['xid'], C.byref(parent), C.byref(px), C.byref(py),
                                  C.byref(width), C.byref(height), C.byref(border), C.byref(depth))
            assert x.XTranslateCoordinates(display, row['xid'], root, 0, 0,
                                            C.byref(px), C.byref(py), C.byref(child))
            ox, oy = row['origin']
            return [px.value + ox, py.value + oy, px.value + ox + width.value, py.value + oy + height.value]

        with (qa / 'window.log').open('w') as log:
            option = '--display-change' if args.display_change else '--host-reply' if args.host_reply else '--handshake'
            process = subprocess.Popen([str(runtime / 'bin/wine'), str(qa / 'fullscreen-map.exe'), option],
                                       env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True)
            lines = queue.Queue()

            def read_lines():
                for line in process.stdout:
                    lines.put(line)

            reader = threading.Thread(target=read_lines, daemon=True)
            reader.start()
            try:
                deadline = time.monotonic() + 30
                while process.poll() is None or x.XPending(display):
                    assert time.monotonic() < deadline, 'fullscreen fixture timed out'
                    while x.XPending(display):
                        event = (C.c_long * 24)()
                        x.XNextEvent(display, C.byref(event))
                        msg = C.cast(C.byref(event), C.POINTER(ClientMessage)).contents
                        if msg.type == 33 and msg.message_type == atom:
                            messages.append(dict(window=msg.window, indices=list(msg.data)[:4]))
                    while not lines.empty():
                        line = lines.get_nowait()
                        log.write(line)
                        log.flush()
                        if not line.startswith('{'): continue
                        row = json.loads(line)
                        if row.get('phase') == 'wm-paused':
                            assert wm_pid is not None
                            status = Path(f'/proc/{wm_pid}/status').read_text().splitlines()
                            assert any(line.startswith('State:') and 'T' in line for line in status), status
                            row['native'] = native_geometry(row)
                            assert row['native'] != row['expected'], row
                            intermediate_replies.append(row)
                            os.kill(wm_pid, signal.SIGCONT)
                            process.stdin.write('\n')
                            process.stdin.flush()
                            continue
                        if not checks:
                            expected = (runtime / 'lib/wine/x86_64-unix/winex11.so').stat()
                            for pid, _ in processes(qa):
                                try:
                                    maps = Path(f'/proc/{pid}/maps').read_text().splitlines()
                                except (FileNotFoundError, ProcessLookupError):
                                    continue
                                for mapping in maps:
                                    fields = mapping.split(None, 5)
                                    if len(fields) != 6 or not fields[5].endswith('/winex11.so'): continue
                                    major, minor = (int(part, 16) for part in fields[3].split(':'))
                                    assert (os.makedev(major, minor), int(fields[4])) == (
                                        expected.st_dev, expected.st_ino), f'Unexpected loaded driver: {fields[5]}'
                                    loaded_drivers.add(fields[5])
                            assert loaded_drivers, 'Could not verify the loaded X11 driver'
                        row['native'] = native_geometry(row)
                        row['native_matches'] = row['native'] == row['expected']
                        checks.append(row)
                        if args.display_change and len(checks) in (3, 6, 9):
                            layout(len(checks) == 6, len(checks) != 9)
                        process.stdin.write('\n')
                        process.stdin.flush()
                    time.sleep(.01)
                exit_code = process.wait()
                reader.join(timeout=5)
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
    finally:
        if wm_pid is not None:
            try:
                os.kill(wm_pid, signal.SIGCONT)
            except ProcessLookupError:
                pass
        x.XCloseDisplay(display)
        connection.close_sync(None)

report = dict(driver_sha256=hashlib.sha256((runtime / 'lib/wine/x86_64-unix/winex11.so').read_bytes()).hexdigest(),
              exit_code=exit_code, checks=checks, protocol_messages=messages,
              loaded_drivers=sorted(loaded_drivers), display_change=args.display_change,
              host_reply=args.host_reply, intermediate_replies=intermediate_replies,
              account_used=False, host_desktop_used=False)
expected_checks = 12 if args.display_change else 9
messages_ok = len(messages) >= expected_checks if args.display_change else len(messages) == expected_checks
report['passed'] = (exit_code == 0 and len(checks) == expected_checks and messages_ok and
                   len(intermediate_replies) == int(args.host_reply)) and all(
    row['passed'] and row['native_matches'] for row in checks)
(qa / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
assert report['passed'], report
print(f'PASS: {expected_checks} initial-map/remap geometries with EWMH fullscreen requests')
