#!/usr/bin/env python3
"""Move a shared native frame while its owner thread cannot consume ConfigureNotify."""
import ctypes as C
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import signal
import shutil
import subprocess
import threading
import time
from isolated import desktop, processes

parser = argparse.ArgumentParser(description=__doc__)
pending = parser.add_mutually_exclusive_group()
pending.add_argument('--pending-move', action='store_true', help='Stop only the private WM during an app move')
pending.add_argument('--pending-resize', action='store_true', help='Move the frame before a resize acknowledgement')
parser.add_argument('--create-after-move', action='store_true', help='Create the overlay after the owner moves')
args = parser.parse_args()
assert not args.pending_resize or not args.create_after_move
qa = Path(os.environ['WECOM_QA_ROOT']).resolve()
assert (qa / '.wecom-frame-qa').is_file()
name = 'frame-move-race-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
source = Path(__file__).with_name('frame-move-race.c')
exe = qa / (name + '.exe')
subprocess.run(['x86_64-w64-mingw32-gcc', '-O2', '-Wall', '-Wextra', '-Werror', str(source),
                '-o', str(exe), '-luser32'], check=True)
files = {'driver': qa / 'wine/lib/wine/x86_64-unix/winex11.so',
         'core': qa / 'wine/lib/wine/x86_64-unix/win32u.so', 'server': qa / 'wine/bin/wineserver',
         'fixture': source, 'runner': Path(__file__), 'exe': exe}
report = {'host_desktop_used': False, 'account_data_used': False, 'events': [], 'passed': False,
          'mode': 'pending-resize' if args.pending_resize else 'pending-move' if args.pending_move else 'external-move',
          'create_after_move': args.create_after_move,
          'before': {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in files.items()}}
with desktop(qa) as env:
    env.update(WINEPREFIX=str(qa / 'prefix'), WINESERVER=str(qa / 'wine/bin/wineserver'),
               WINEDEBUG='-all,+x11drv', WINE_X11_OWNED_FRAME='1',
               WINE_X11_FRAME_DECORATION_CLASSES='MoveRaceOverlay',
               WINEDLLOVERRIDES='winewayland.drv=d;mscoree,mshtml,winemenubuilder=')
    started = time.monotonic()
    with (qa / (name + '-startup.log')).open('w') as startup:
        subprocess.run([str(qa / 'wine/bin/wine'), 'wineboot.exe', '-u'], env=env,
                       stdout=startup, stderr=subprocess.STDOUT, check=True, timeout=60)
    report['startup_seconds'] = time.monotonic() - started
    with (qa / (name + '.log')).open('w') as log:
        app = subprocess.Popen([str(qa / 'wine/bin/wine'), str(exe),
                                *(['defer-overlay'] if args.create_after_move else [])], env=env, text=True,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log)
        lines = queue.Queue()

        def read():
            for line in app.stdout:
                lines.put(json.loads(line))
            lines.put(None)

        threading.Thread(target=read, daemon=True).start()

        def command(text):
            app.stdin.write(text + '\n'); app.stdin.flush()

        def wait(stage):
            while True:
                event = lines.get(timeout=10)
                assert event is not None, 'fixture exited before ' + stage
                report['events'].append(event)
                if event['event'] == stage:
                    return event

        def geometry(xid):
            text = subprocess.run(['xwininfo', '-stats', '-tree', '-id', str(xid)], env=env,
                                  capture_output=True, text=True, check=True, timeout=3).stdout
            values = [int(re.search(pattern, text)[1]) for pattern in
                      (r'Absolute upper-left X:\s+(-?\d+)', r'Absolute upper-left Y:\s+(-?\d+)',
                       r'Width:\s+(\d+)', r'Height:\s+(\d+)')]
            return values

        display = wm_pid = None
        try:
            state = wait('owner-ready' if args.create_after_move else 'ready')
            if not args.create_after_move:
                assert state['frame'] == state['overlay_frame'], state
            deadline = time.monotonic() + 3
            while True:
                initial = {role: geometry(state[role]) for role in ('frame', 'body', 'owner_body') if state[role]}
                if (args.create_after_move and initial['frame'] == [200, 200, 500, 400] or
                    not args.create_after_move and initial['frame'][2:] == [532, 432] and
                    initial['body'] == [184, 184, 532, 432]):
                    break
                assert time.monotonic() < deadline, initial
                time.sleep(.02)
            report['initial'] = initial
            if args.pending_move or args.pending_resize:
                private_wm = [pid for pid, argv in processes(qa) if argv and Path(os.fsdecode(argv[0])).name ==
                              'gnome-shell']
                assert len(private_wm) == 1, private_wm
                wm_pid = private_wm[0]
                os.kill(wm_pid, signal.SIGSTOP)
                command('resize-owner' if args.pending_resize else 'move-owner 500 300')
                paused = wait('owner-resized' if args.pending_resize else 'owner-moved')
                expected = [200, 200, 800, 600] if args.pending_resize else [500, 300, 1000, 700]
                assert paused['owner'] == expected, paused
                assert geometry(state['frame']) == initial['frame'], 'WM applied move before requested barrier'
            else:
                command('pause'); paused = wait('paused')
            x = C.CDLL('libX11.so.6')
            x.XOpenDisplay.argtypes = [C.c_char_p]; x.XOpenDisplay.restype = C.c_void_p
            x.XMoveWindow.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.c_int]
            x.XSync.argtypes = [C.c_void_p, C.c_int]
            x.XCloseDisplay.argtypes = [C.c_void_p]
            previous = os.environ.get('XAUTHORITY'); os.environ['XAUTHORITY'] = env['XAUTHORITY']
            display = x.XOpenDisplay(env['DISPLAY'].encode())
            if previous is None: os.environ.pop('XAUTHORITY')
            else: os.environ['XAUTHORITY'] = previous
            assert display
            target = [initial['frame'][0] + 300, initial['frame'][1] + 100]
            if not args.pending_move:
                x.XMoveWindow(display, state['frame'], *target); x.XSync(display, False)
                if args.pending_resize:
                    os.kill(wm_pid, signal.SIGCONT); wm_pid = None
                deadline = time.monotonic() + 3
                while geometry(state['frame'])[:2] != target:
                    assert time.monotonic() < deadline, 'WM did not move the frame'
                    time.sleep(.02)
            report['moved_frame'] = geometry(state['frame'])
            requested = [184 + 300, 184 + 100]
            action = 'resize-overlay' if args.pending_resize else 'create' if args.create_after_move else 'move'
            command(action + ' %d %d' % tuple(requested))
            moved = wait('ready' if args.create_after_move else 'moved')
            state = moved
            assert state['frame'] == state['overlay_frame'], state
            report['paused_snapshot'] = {role: geometry(state[role]) for role in ('frame', 'body', 'owner_body')}
            report['stale_owner_confirmed'] = moved['owner'] == paused['owner'] == [200, 200, 700, 600]
            report['position_passed'] = report['paused_snapshot']['body'][:2] == requested
            if args.pending_move:
                os.kill(wm_pid, signal.SIGCONT); wm_pid = None
                deadline = time.monotonic() + 3
                while geometry(state['frame'])[:2] == initial['frame'][:2]:
                    assert time.monotonic() < deadline, 'private WM did not resume its move'
                    time.sleep(.02)
            else:
                command('resume'); wait('resumed')
            expected_owner = [500, 300, 1100, 700] if args.pending_resize else [500, 300, 1000, 700]
            deadline = time.monotonic() + 3
            while True:
                command('owner-state'); state = wait('owner-state')
                if state['owner'] == expected_owner:
                    break
                assert time.monotonic() < deadline, state
                time.sleep(.02)
            command('owner-state'); wait('owner-state')
            command('state'); wait('overlay-state')
            report['resumed_snapshot'] = {role: geometry(state[role]) for role in ('frame', 'body', 'owner_body')}
            extents = subprocess.run(['xprop', '-id', str(state['frame']), '_GTK_FRAME_EXTENTS'], env=env,
                                     capture_output=True, text=True, check=True, timeout=3).stdout
            report['resumed_extents'] = [int(value) for value in extents.partition('=')[2].split(',')]
            width = 632 if args.pending_resize else 532
            report['size_passed'] = (report['resumed_snapshot']['frame'] == [*requested, width, 432] and
                                     report['resumed_snapshot']['body'] == [*requested, width, 432] and
                                     report['resumed_extents'] == [16, 16, 16, 16])
            report['passed'] = report['size_passed'] and (args.pending_move or args.pending_resize or
                                                        report['stale_owner_confirmed'] and report['position_passed'])
            if args.pending_resize: report['passed'] &= report['position_passed']
        except Exception as error:
            report['error'] = str(error) or type(error).__name__
            if app.poll() is None and shutil.which('gdb'):
                stack = qa / (name + '-threads.log')
                with stack.open('w') as output:
                    try:
                        subprocess.run(['gdb', '-q', '-batch', '-ex', 'set debuginfod enabled off',
                                        '-ex', 'thread apply all bt 20', '-p', str(app.pid)],
                                       stdout=output, stderr=subprocess.STDOUT, check=False, timeout=6)
                    except subprocess.TimeoutExpired:
                        report['stack_capture_timeout'] = True
                report['threads'] = str(stack)
        finally:
            if wm_pid:
                os.kill(wm_pid, signal.SIGCONT)
            if display:
                x.XCloseDisplay(display)
            if app.poll() is None:
                try:
                    command('quit'); app.wait(timeout=5)
                except (BrokenPipeError, subprocess.TimeoutExpired):
                    if app.poll() is None:
                        app.kill(); app.wait(timeout=5)
            report['exit_code'] = app.returncode
            subprocess.run([env['WINESERVER'], '-k'], env=env, check=False, timeout=10)
            subprocess.run([env['WINESERVER'], '-w'], env=env, check=True, timeout=10)
report['after'] = {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in files.items()}
report['passed'] &= report['exit_code'] == 0 and report['before'] == report['after']
path = qa / (name + '.json')
path.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'report': str(path), **report}))
raise SystemExit(0 if report['passed'] else 1)
