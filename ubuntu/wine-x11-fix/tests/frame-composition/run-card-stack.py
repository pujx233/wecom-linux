"""Compare Win32 and native order for an ownerless, nonactivating card under Mutter."""
from datetime import datetime, timezone
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import threading
import time

from PIL import Image
from isolated import desktop
from screencast import recording

qa = Path(os.environ['WECOM_QA_ROOT']).resolve()
name = 'card-stack-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
source = Path(__file__).with_name('card-stack.c')
exe = qa / (name + '.exe')
subprocess.run(['x86_64-w64-mingw32-gcc', '-O2', '-Wall', '-Wextra', '-Werror', str(source),
                '-o', str(exe), '-lgdi32', '-luser32'], check=True)
report = {'host_desktop_used': False, 'account_data_used': False, 'cases': [], 'runtime': {}}
for module in ('winex11.so', 'win32u.so'):
    report['runtime'][module] = hashlib.sha256((qa / 'wine/lib/wine/x86_64-unix' / module).read_bytes()).hexdigest()
with desktop(qa) as env:
    env.update(WINEPREFIX=str(qa / 'prefix'), WINESERVER=str(qa / 'wine/bin/wineserver'),
               WINEDEBUG='-all,+x11drv,+cursor', WINE_X11_OWNED_FRAME='1',
               WINE_WECOM_FIRST_PRESENT_ARGB='1', WINE_X11_FIXED_TRANSIENT_ARGB='1',
               WINE_X11_FIXED_TRANSIENT_UTILITY='1',
               WINEDLLOVERRIDES='winewayland.drv=d;mscoree,mshtml,winemenubuilder=')
    with (qa / (name + '-startup.log')).open('w') as log:
        subprocess.run([str(qa / 'wine/bin/wine'), 'wineboot.exe', '-u'], env=env,
                       stdout=log, stderr=log, check=True, timeout=60)
    with recording(qa, env, name, interactive=True) as capture, (qa / (name + '.log')).open('w') as log:
        apps = []

        def launch(foreign=False):
            app = subprocess.Popen([str(qa / 'wine/bin/wine'), str(exe), *(['foreign'] if foreign else [])],
                                   env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True)
            lines = queue.Queue()
            apps.append((app, lines))

            def read():
                for line in app.stdout:
                    lines.put(json.loads(line))
                lines.put(None)

            threading.Thread(target=read, daemon=True).start()
            ready = lines.get(timeout=15)
            assert ready and ready['event'] == 'ready', ready
            return app, lines, ready

        def command(app, value):
            app.stdin.write(value + '\n'); app.stdin.flush()

        def native():
            value = subprocess.run(['xprop', '-root', '_NET_CLIENT_LIST_STACKING', '_NET_ACTIVE_WINDOW'], env=env,
                                   capture_output=True, text=True, check=True, timeout=3).stdout.splitlines()
            return ([int(item, 16) for item in re.findall(r'0x[0-9a-f]+', value[0])],
                    int(re.search(r'0x[0-9a-f]+', value[1])[0], 16))

        def geometry(window):
            text = subprocess.run(['xwininfo', '-stats', '-id', str(window)], env=env,
                                  capture_output=True, text=True, check=True, timeout=3).stdout
            return [int(re.search(pattern, text)[1]) for pattern in
                    (r'Absolute upper-left X:\s+(-?\d+)', r'Absolute upper-left Y:\s+(-?\d+)',
                     r'Width:\s+(\d+)', r'Height:\s+(\d+)')]

        def native_activate(window, current):
            class ClientMessage(C.Structure):
                _fields_ = [('type', C.c_int), ('serial', C.c_ulong), ('send_event', C.c_int),
                            ('display', C.c_void_p), ('window', C.c_ulong), ('message_type', C.c_ulong),
                            ('format', C.c_int), ('data', C.c_long * 5)]

            class Event(C.Union):
                _fields_ = [('client', ClientMessage), ('padding', C.c_long * 24)]

            x = C.CDLL('libX11.so.6')
            x.XOpenDisplay.argtypes = [C.c_char_p]; x.XOpenDisplay.restype = C.c_void_p
            x.XDefaultRootWindow.argtypes = [C.c_void_p]; x.XDefaultRootWindow.restype = C.c_ulong
            x.XInternAtom.argtypes = [C.c_void_p, C.c_char_p, C.c_int]; x.XInternAtom.restype = C.c_ulong
            x.XSendEvent.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.c_long, C.POINTER(Event)]
            x.XSync.argtypes = [C.c_void_p, C.c_int]
            x.XCloseDisplay.argtypes = [C.c_void_p]
            saved = os.environ.get('XAUTHORITY'); os.environ['XAUTHORITY'] = env['XAUTHORITY']
            display = x.XOpenDisplay(env['DISPLAY'].encode())
            if saved is None: os.environ.pop('XAUTHORITY')
            else: os.environ['XAUTHORITY'] = saved
            assert display
            try:
                event = Event()
                event.client = ClientMessage(33, 0, True, display, window,
                                             x.XInternAtom(display, b'_NET_ACTIVE_WINDOW', False), 32,
                                             (C.c_long * 5)(2, 0, current, 0, 0))
                assert x.XSendEvent(display, x.XDefaultRootWindow(display), False,
                                    (1 << 19) | (1 << 20), C.byref(event))
                x.XSync(display, False)
            finally:
                x.XCloseDisplay(display)

        def native_restack_case(label, lower, upper, active, color, foreign_window=None, straddle_foreign=False):
            class Changes(C.Structure):
                _fields_ = [(name, C.c_int) for name in ('x', 'y', 'width', 'height', 'border_width')]
                _fields_ += [('sibling', C.c_ulong), ('stack_mode', C.c_int)]

            windows = [lower, upper] + ([foreign_window] if foreign_window else [])
            command(app, 'state'); win32_before = lines.get(timeout=5)
            before = {str(window): geometry(window) for window in windows}
            x = C.CDLL('libX11.so.6')
            x.XOpenDisplay.argtypes = [C.c_char_p]; x.XOpenDisplay.restype = C.c_void_p
            x.XReconfigureWMWindow.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.c_uint, C.POINTER(Changes)]
            x.XSync.argtypes = [C.c_void_p, C.c_int]
            x.XCloseDisplay.argtypes = [C.c_void_p]
            saved = os.environ.get('XAUTHORITY'); os.environ['XAUTHORITY'] = env['XAUTHORITY']
            display = x.XOpenDisplay(env['DISPLAY'].encode())
            if saved is None: os.environ.pop('XAUTHORITY')
            else: os.environ['XAUTHORITY'] = saved
            assert display
            try:
                changes = Changes(sibling=foreign_window if straddle_foreign else upper, stack_mode=0)
                x.XReconfigureWMWindow(display, lower, 0, 32 | 64, C.byref(changes))
                x.XSync(display, False)
            finally:
                x.XCloseDisplay(display)
            deadline = time.monotonic() + 3
            time.sleep(.1)
            target = qa / (name + '-' + label + '.png')
            while True:
                order, focused = native()
                correct = lower in order and upper in order and order.index(lower) < order.index(upper)
                capture(target)
                pixel = Image.open(target).convert('RGB').getpixel((500, 400))
                if (correct and pixel == color) or time.monotonic() >= deadline: break
                time.sleep(.05)
            after = {str(window): geometry(window) for window in windows}
            command(app, 'state'); win32_after = lines.get(timeout=5)
            corrections = (qa / (name + '.log')).read_text().count('native-stack ')
            time.sleep(.3)
            settled = (qa / (name + '.log')).read_text().count('native-stack ')
            foreign_order = not foreign_window or all(
                (order.index(foreign_window) < order.index(window)) == straddle_foreign for window in (lower, upper))
            win32_correct = all(state['order'].index(upper) < state['order'].index(lower)
                                for state in (win32_before, win32_after))
            passed = (correct and focused == active and pixel == color and before == after and
                      corrections == settled and foreign_order and win32_correct)
            report['cases'].append(dict(name=label, native_order=order, active=focused, pixel=pixel,
                                        win32_before=win32_before, win32_after=win32_after,
                                        before=before, after=after, corrections=corrections,
                                        settled_corrections=settled, passed=bool(passed)))

        try:
            app, lines, ready = launch()
            time.sleep(.5)
            command(app, 'activate')
            time.sleep(.3)
            for label, commands in [('initial', ['show']), ('reshow', ['hide', 'show']),
                                    ('maximized', ['hide', 'maximize', 'show']),
                                    ('restored', ['hide', 'restore', 'show']),
                                    ('minimized-peer', ['minimize-peer', 'show'])]:
                for value in commands:
                    command(app, value); time.sleep(.3)
                deadline = time.monotonic() + 3
                target = qa / (name + '-' + label + '.png')
                while True:
                    command(app, 'state'); state = lines.get(timeout=5)
                    order, active = native()
                    capture(target)
                    pixel = Image.open(target).convert('RGB').getpixel((500, 400))
                    passed = (state['card_above_main'] and state['card_owner'] == 0 and
                              not state['card_exstyle'] & 8 and state['active'] == state['main'] == active and
                              state['main'] in order and state['card'] in order and
                              order.index(state['card']) > order.index(state['main']) and pixel == (0, 0, 255) and
                              bool(state['main_maximized']) == (label == 'maximized') and
                              (label != 'minimized-peer' or state['peer_minimized']))
                    if passed or time.monotonic() >= deadline: break
                    time.sleep(.1)
                report['cases'].append(dict(name=label, win32=state, native_order=order, active=active,
                                            pixel=pixel, passed=bool(passed)))
            x = C.CDLL('libX11.so.6')
            x.XOpenDisplay.argtypes = [C.c_char_p]; x.XOpenDisplay.restype = C.c_void_p
            x.XDefaultRootWindow.argtypes = [C.c_void_p]; x.XDefaultRootWindow.restype = C.c_ulong
            x.XQueryPointer.argtypes = [C.c_void_p, C.c_ulong] + [C.c_void_p] * 7
            x.XCloseDisplay.argtypes = [C.c_void_p]
            saved = os.environ.get('XAUTHORITY'); os.environ['XAUTHORITY'] = env['XAUTHORITY']
            display = x.XOpenDisplay(env['DISPLAY'].encode())
            if saved is None: os.environ.pop('XAUTHORITY')
            else: os.environ['XAUTHORITY'] = saved
            assert display
            root, child = C.c_ulong(), C.c_ulong()
            px, py, wx, wy = [C.c_int() for _ in range(4)]
            mask = C.c_uint()
            deadline = time.monotonic() + 3
            while True:
                capture.pointer(500, 400); time.sleep(.1)
                x.XQueryPointer(display, x.XDefaultRootWindow(display), C.byref(root), C.byref(child),
                                C.byref(px), C.byref(py), C.byref(wx), C.byref(wy), C.byref(mask))
                if (px.value, py.value) == (500, 400): break
                assert time.monotonic() < deadline, (px.value, py.value)
            report['pointer'] = {'point': [px.value, py.value], 'native_child': child.value}
            capture.button(True); time.sleep(.1)
            capture.button(False)
            x.XCloseDisplay(display)
            time.sleep(.3)
            command(app, 'state'); state = lines.get(timeout=5)
            order, active = native()
            passed = (state['card_clicks'] == 1 and state['main_clicks'] == 0 and
                      active == state['active'] == state['main'])
            report['cases'].append(dict(name='card-input', win32=state, active=active, passed=passed))
            native_restack_case('same-focus-native-restack', state['main'], state['card'],
                                active, (0, 0, 255))
            command(app, 'owned'); time.sleep(.5)
            command(app, 'state'); state = lines.get(timeout=5)
            order, active = native()
            target = qa / (name + '-owned.png'); capture(target)
            pixel = Image.open(target).convert('RGB').getpixel((500, 400))
            passed = (state['card_owner'] != 0 and active == state['main'] and
                      state['order'].index(state['preview']) < state['order'].index(state['card']) <
                      state['order'].index(state['main']) and
                      order.index(state['preview']) > order.index(state['card']) > order.index(state['main']) and
                      pixel == (0, 255, 0))
            report['cases'].append(dict(name='owned-sibling-preview', win32=state, native_order=order,
                                        active=active, pixel=pixel, passed=passed))
            native_restack_case('multiple-card-native-restack', state['card'], state['preview'],
                                active, (0, 255, 0))
            peer, peer_lines, peer_ready = launch(True)
            time.sleep(.5)
            command(peer, 'activate'); time.sleep(.3)
            command(app, 'repaint'); time.sleep(.3)
            command(app, 'state'); state = lines.get(timeout=5)
            command(peer, 'state'); peer_state = peer_lines.get(timeout=5)
            order, active = native()
            target = qa / (name + '-foreign.png'); capture(target)
            pixel = Image.open(target).convert('RGB').getpixel((500, 400))
            passed = (active == peer_state['main'] == state['active'] and
                      order.index(peer_state['main']) > order.index(state['preview']) and pixel == (255, 0, 0))
            report['cases'].append(dict(name='foreign-app-activation', win32=state, foreign=peer_state,
                                        native_order=order, active=active, pixel=pixel, passed=bool(passed)))
            native_restack_case('foreign-above-native-restack', state['card'], state['preview'],
                                active, (255, 0, 0), peer_state['main'])
            command(app, 'unowned'); time.sleep(.3)
            native_activate(peer_state['main'], native()[1]); time.sleep(.3)
            command(app, 'state'); state = lines.get(timeout=5)
            assert not state['card_owner'], state
            native_restack_case('foreign-between-native-restack', state['card'], state['preview'],
                                active, (0, 255, 0), peer_state['main'], straddle_foreign=True)
            for label, reshow in [('foreign-to-main-with-helper', False), ('reshown-main-with-helper', True)]:
                if reshow: command(app, 'reshow-main')
                command(app, 'helper'); time.sleep(.3)
                native_activate(peer_state['main'], native()[1]); time.sleep(.3)
                command(app, 'state'); before = lines.get(timeout=5)
                before_order, before_active = native()
                helper = before['helper']
                precondition = (helper in before_order and before['main'] in before_order and
                                peer_state['main'] in before_order and before['helper_owner'] == 0 and
                                before['helper_style'] & 0x10000000 and not before['helper_style'] & 0x20000000 and
                                before['helper_exstyle'] & 0x8080080 == 0x8080080 and
                                not before['helper_exstyle'] & 8 and
                                before['order'].index(helper) < before['order'].index(before['main']) and
                                before_active == before['active'] == peer_state['main'] and
                                before_order.index(before['main']) < before_order.index(peer_state['main']) and
                                before_order.index(helper) < before_order.index(peer_state['main']))
                native_activate(before['main'], before_active)
                time.sleep(.5)
                command(app, 'state'); after = lines.get(timeout=5)
                order, active = native()
                target = qa / (name + '-' + label + '.png'); capture(target)
                pixel = Image.open(target).convert('RGB').getpixel((500, 400))
                passed = (precondition and active == after['active'] == after['main'] and
                          order.index(after['main']) > order.index(peer_state['main']) and pixel == (255, 255, 255) and
                          (order.index(helper) > order.index(after['main'])) ==
                          (after['order'].index(helper) < after['order'].index(after['main'])))
                report['cases'].append(dict(name=label, before=before, before_order=before_order,
                                            before_active=before_active, precondition=bool(precondition), win32=after,
                                            native_order=order, active=active, pixel=pixel, passed=bool(passed)))
        except Exception as error:
            report['error'] = str(error) or type(error).__name__
        finally:
            for app, lines in apps:
                if app.poll() is None:
                    command(app, 'quit'); app.wait(timeout=10)
            subprocess.run([env['WINESERVER'], '-k'], env=env)
            subprocess.run([env['WINESERVER'], '-w'], env=env, check=True, timeout=10)
report['passed'] = len(report['cases']) == 14 and 'error' not in report and all(c['passed'] for c in report['cases'])
path = qa / (name + '.json')
path.write_text(json.dumps(report, indent=2) + '\n')
print(path); print(json.dumps(report))
raise SystemExit(0 if report['passed'] else 1)
