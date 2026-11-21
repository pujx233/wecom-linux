#!/usr/bin/env python3
"""Check ICCCM focus delivery before a pending restore acknowledgement on a private X11 server."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import queue
import select
import subprocess
import threading

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--bits', choices=('32', '64'), default='32')
parser.add_argument('--expect-focus-loss', action='store_true')
parser.add_argument('--foreground-first', action='store_true')
args = parser.parse_args()
qa = args.output.resolve()
qa.mkdir(parents=True, exist_ok=False)
(qa / 'runtime').mkdir(mode=0o700)
runtime = args.runtime.resolve()
here = Path(__file__).parent
compiler = 'i686-w64-mingw32-gcc' if args.bits == '32' else 'x86_64-w64-mingw32-gcc'
subprocess.run([compiler, '-O2', '-Wall', '-Wextra', '-Werror', str(here / 'restore-focus.c'),
                '-o', str(qa / 'restore.exe')], check=True)
subprocess.run(['cc', '-O2', '-Wall', '-Wextra', '-Werror', str(here / 'restore-focus-wm.c'),
                '-o', str(qa / 'wm'), '-lX11'], check=True)
env = {key: value for key, value in os.environ.items() if not key.startswith(('WINE', 'WECOM_', 'LD_'))}
for key in ('DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'WAYLAND_DISPLAY'):
    env.pop(key, None)
env.update(WINEPREFIX=str(qa / 'prefix'), WINESERVER=str(runtime / 'bin/wineserver'),
           XDG_RUNTIME_DIR=str(qa / 'runtime'), XMODIFIERS='@im=none', WINEDEBUG='-all,+event',
           WINE_X11_OWNED_FRAME='1', WINEDLLOVERRIDES='winewayland.drv=d;mscoree,mshtml,winemenubuilder=')
report = dict(host_desktop_used=False, account_used=False, bits=args.bits,
              focus_request_precedes_state=True, expected_focus_loss=args.expect_focus_loss)
read_fd, write_fd = os.pipe()
with (qa / 'xvfb.log').open('w') as log:
    xserver = subprocess.Popen(['Xvfb', '-displayfd', str(write_fd), '-screen', '0', '1600x1000x24',
        '-nolisten', 'tcp', '-noreset', '-ac'], pass_fds=(write_fd,), stdout=log, stderr=log)
os.close(write_fd)
wm = app = None
try:
    if not select.select([read_fd], [], [], 10)[0]:
        raise TimeoutError('Private X11 server did not start')
    env['DISPLAY'] = ':' + os.read(read_fd, 40).decode().strip()
    with (qa / 'boot.log').open('w') as log:
        subprocess.run([str(runtime / 'bin/wine'), 'wineboot.exe', '-u'], env=env,
                       stdout=log, stderr=log, check=True, timeout=40)
    with (qa / 'wm.log').open('w') as log:
        wm = subprocess.Popen([str(qa / 'wm')], env=env, stdout=subprocess.PIPE, stderr=log, text=True)
    assert select.select([wm.stdout], [], [], 5)[0] and wm.stdout.readline().strip() == 'ready'
    with (qa / 'wine.log').open('w') as log:
        command = [str(runtime / 'bin/wine'), str(qa / 'restore.exe')]
        if args.foreground_first:
            command.append('foreground-first')
        app = subprocess.Popen(command,
            env=env, stdout=subprocess.PIPE, stderr=log, text=True)
    lines = queue.Queue()

    def read():
        for line in app.stdout:
            lines.put(json.loads(line))

    threading.Thread(target=read, daemon=True).start()
    ready = lines.get(timeout=20)
    assert ready['event'] == 'ready', ready
    assert lines.get(timeout=5)['event'] == 'minimized'
    assert lines.get(timeout=5)['event'] == 'restored'
    result = lines.get(timeout=5)
    assert result['event'] == 'result', result
    xlib = ctypes.CDLL('libX11.so.6')
    xlib.XOpenDisplay.restype = ctypes.c_void_p
    xlib.XGetInputFocus.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int)]
    xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]
    display = xlib.XOpenDisplay(env['DISPLAY'].encode())
    assert display
    focus, revert = ctypes.c_ulong(), ctypes.c_int()
    xlib.XGetInputFocus(display, ctypes.byref(focus), ctypes.byref(revert))
    xlib.XCloseDisplay(display)
    native = focus.value
    assert select.select([wm.stdout], [], [], 2)[0]
    assert wm.stdout.readline().strip() == 'restore-focus-before-state'
    win32 = result['foreground'] == result['expected']
    aligned = native == ready['body']
    report.update(ready=ready, win32=result, native_focus=native, win32_foreground_correct=win32,
                  native_focus_correct=aligned, passed=win32 and (not aligned if args.expect_focus_loss else aligned))
    assert app.wait(timeout=5) == 0
finally:
    if app and app.poll() is None:
        app.terminate()
        app.wait(timeout=5)
    subprocess.run([str(runtime / 'bin/wineserver'), '-k'], env=env, timeout=10)
    subprocess.run([str(runtime / 'bin/wineserver'), '-w'], env=env, timeout=10)
    if wm and wm.poll() is None:
        wm.terminate()
        wm.wait(timeout=5)
    xserver.terminate()
    xserver.wait(timeout=5)
    os.close(read_fd)
(qa / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
raise SystemExit(0 if report['passed'] else 1)
