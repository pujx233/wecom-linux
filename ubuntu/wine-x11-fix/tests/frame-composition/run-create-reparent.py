#!/usr/bin/env python3
"""Keep a real native body alive when WM_NCCREATE changes an unlinked window's frame role."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import threading
from isolated import desktop

parser = argparse.ArgumentParser(description=__doc__)
phases = ('none', 'create', 'nccreate', 'owner-create', 'owner-nccreate')
parser.add_argument('--phase', choices=('all', *phases), default='all')
args = parser.parse_args()
qa = Path(os.environ['WECOM_QA_ROOT']).resolve()
assert (qa / '.wecom-frame-qa').is_file()
name = 'create-reparent-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
source = Path(__file__).with_name('create-reparent.c').resolve()
exe = qa / (name + '.exe')
subprocess.run(['x86_64-w64-mingw32-gcc', '-O2', '-Wall', '-Wextra', '-Werror', str(source),
                '-o', str(exe), '-lgdi32', '-luser32'], check=True)
files = {'driver': qa / 'wine/lib/wine/x86_64-unix/winex11.so',
         'core': qa / 'wine/lib/wine/x86_64-unix/win32u.so', 'server': qa / 'wine/bin/wineserver',
         'source': source, 'runner': Path(__file__).resolve(), 'fixture': exe}
report = {'cases': [], 'host_desktop_used': False, 'account_data_used': False,
          'sha256_before': {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in files.items()}}
with desktop(qa) as env:
    env.update(WINEPREFIX=str(qa / 'prefix'), WINESERVER=str(qa / 'wine/bin/wineserver'),
               DBUS_SYSTEM_BUS_ADDRESS='unix:path=' + str(qa / 'no-system-bus'), WINEDEBUG='-all,+x11drv',
               WINE_X11_OWNED_FRAME='1', WINE_WINDOW_DIAGNOSTICS='0',
               WINE_X11_FRAME_ATTACHED_CLASSES='CreateReparent',
               WINEDLLOVERRIDES='winewayland.drv=d;mscoree,mshtml,winemenubuilder=')
    try:
        for phase in (phases if args.phase == 'all' else (args.phase,)):
            case = {'phase': phase, 'events': [], 'passed': False}
            report['cases'].append(case)
            with (qa / (name + '-' + phase + '.log')).open('w') as log:
                app = subprocess.Popen([str(qa / 'wine/bin/wine'), str(exe), phase], env=env,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True)
                lines = queue.Queue()

                def read(stdout=app.stdout, target=lines):
                    for line in stdout:
                        try:
                            target.put(json.loads(line))
                        except ValueError:
                            target.put({'invalid_json': line})
                    target.put(None)

                threading.Thread(target=read, daemon=True).start()
                try:
                    while True:
                        event = lines.get(timeout=20)
                        assert event is not None, 'fixture exited before ready'
                        case['events'].append(event)
                        if event.get('stage') == 'ready':
                            break
                    app.stdin.write('state\n'); app.stdin.flush()
                    while True:
                        event = lines.get(timeout=10)
                        assert event is not None, 'fixture exited before event-pump barrier'
                        case['events'].append(event)
                        if event.get('stage') == 'state':
                            break
                    native = {}
                    for role in ('body', 'frame', 'owner_frame', 'host_frame'):
                        if role in ('owner_frame', 'host_frame') and not event[role]:
                            continue
                        geometry = subprocess.run(['xwininfo', '-stats', '-tree', '-id', str(event[role])], env=env,
                                                  capture_output=True, text=True, timeout=5)
                        assert geometry.returncode == 0, role + ': ' + geometry.stderr.strip()
                        native[role] = [int(re.search(r'Width:\s+(\d+)', geometry.stdout)[1]),
                                        int(re.search(r'Height:\s+(\d+)', geometry.stdout)[1])]
                        if role == 'body':
                            case['body_parent'] = int(re.search(r'Parent window id:\s+(0x[0-9a-f]+)',
                                                               geometry.stdout)[1], 16)
                    case['native'] = native
                    case['passed'] = (event['enum_ok'] and event['listed'] and
                                      event['width'] == event['height'] == 200 and native['body'] == [200, 200] and
                                      case['body_parent'] == event['frame'])
                    if phase.startswith('owner-'):
                        case['passed'] &= (event['owner_parent_is_host'] and event['owner_frame'] == 0 and
                                           event['frame'] == event['host_frame'])
                    else:
                        case['passed'] &= (event['frame'] == event['owner_frame']) == (phase != 'none')
                    if phase != 'none':
                        before = next(item for item in case['events'] if item.get('stage', '').startswith('before-'))
                        case['passed'] &= (before['enum_ok'] and
                                           before['listed'] == (phase in ('create', 'owner-create')) and
                                           before['body'] == event['body'])
                        if phase.startswith('owner-'):
                            case['passed'] &= before['frame'] == before['owner_frame'] != event['frame']
                except Exception as error:
                    case['error'] = str(error) or type(error).__name__
                finally:
                    if app.poll() is None:
                        try:
                            app.stdin.write('quit\n'); app.stdin.flush()
                            app.wait(timeout=5)
                        except (BrokenPipeError, subprocess.TimeoutExpired):
                            if app.poll() is None:
                                app.kill(); app.wait(timeout=5)
                    else:
                        app.wait(timeout=5)
                    case['exit_code'] = app.returncode
                    case['passed'] &= app.returncode == 0
    finally:
        subprocess.run([env['WINESERVER'], '-k'], env=env, check=False, timeout=10)
        subprocess.run([env['WINESERVER'], '-w'], env=env, check=True, timeout=10)
report['sha256_after'] = {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in files.items()}
report['passed'] = all(case['passed'] for case in report['cases']) and report['sha256_before'] == report['sha256_after']
path = qa / (name + '.json')
path.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'report': str(path), 'passed': report['passed'], 'cases': report['cases']}))
raise SystemExit(0 if report['passed'] else 1)
