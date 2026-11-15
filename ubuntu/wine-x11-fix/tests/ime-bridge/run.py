"""Exercise the mail bridge through real XIM commits and foreign Win32 focus in a private desktop."""
import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time

parser = argparse.ArgumentParser()
parser.add_argument('--session-env', type=Path, required=True)
parser.add_argument('--runtime', type=Path, required=True)
parser.add_argument('--fixture', type=Path, required=True)
parser.add_argument('--baseline', type=Path, required=True)
parser.add_argument('--candidate', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--case', action='append')
args = parser.parse_args()
output = args.output.resolve()
output.mkdir(exist_ok=False)
env = os.environ | json.loads(args.session_env.read_text())
assert Path(env['XDG_RUNTIME_DIR']).resolve().is_relative_to(output.parent)
assert env.get('XDG_CURRENT_DESKTOP') == 'KDE'
env.update(WINEPREFIX=str(output / 'prefix'), WINESERVER=str(args.runtime / 'bin/wineserver'),
           WECOM_WIN32U_PATH=str(args.runtime / 'lib/wine/x86_64-unix/win32u.so'),
           WINEDLLOVERRIDES='winewayland.drv=d;mscoree,mshtml,winemenubuilder=',
           WINEDEBUG='-all', WINE_X11_OWNED_FRAME='1', XMODIFIERS='@im=fcitx',
           LANG='zh_CN.UTF-8', LC_CTYPE='zh_CN.UTF-8', WECOM_IME_DEBUG='1', QT_QPA_PLATFORM='wayland')
env.pop('LD_PRELOAD', None)
wine = str(args.runtime / 'bin/wine')
shutil.copy2(args.fixture, output / 'WeMail.exe')
shutil.copy2(args.fixture, output / 'Renderer.exe')
profile = Path(env['XDG_CONFIG_HOME']) / 'fcitx5/profile'
profile.parent.mkdir(parents=True, exist_ok=True)
profile.write_text('[Groups/0]\nName=Default\nDefault Layout=us\nDefaultIM=pinyin\n\n'
                   '[Groups/0/Items/0]\nName=keyboard-us\nLayout=\n\n'
                   '[Groups/0/Items/1]\nName=pinyin\nLayout=\n\n[GroupOrder]\n0=Default\n')
x = C.CDLL('libX11.so.6')
xt = C.CDLL('libXtst.so.6')
x.XOpenDisplay.argtypes = [C.c_char_p]
x.XOpenDisplay.restype = C.c_void_p
x.XCloseDisplay.argtypes = [C.c_void_p]
x.XInternAtom.argtypes = [C.c_void_p, C.c_char_p, C.c_int]
x.XInternAtom.restype = C.c_ulong
x.XGetSelectionOwner.argtypes = [C.c_void_p, C.c_ulong]
x.XGetSelectionOwner.restype = C.c_ulong
x.XSetInputFocus.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.c_ulong]
x.XSync.argtypes = [C.c_void_p, C.c_int]
x.XStringToKeysym.argtypes = [C.c_char_p]
x.XStringToKeysym.restype = C.c_ulong
x.XKeysymToKeycode.argtypes = [C.c_void_p, C.c_ulong]
x.XKeysymToKeycode.restype = C.c_ubyte
xt.XTestFakeKeyEvent.argtypes = [C.c_void_p, C.c_uint, C.c_int, C.c_ulong]
os.environ['XAUTHORITY'] = env['XAUTHORITY']
display = x.XOpenDisplay(env['DISPLAY'].encode())
assert display
report = {'input_engine': 'fcitx5-pinyin', 'mock_wine_apis': False, 'private_prefix': env['WINEPREFIX'],
          'account_data_used': False, 'baseline_sha256': hashlib.sha256(args.baseline.read_bytes()).hexdigest(),
          'candidate_sha256': hashlib.sha256(args.candidate.read_bytes()).hexdigest(), 'cases': [], 'passed': False}


def key(name):
    code = x.XKeysymToKeycode(display, x.XStringToKeysym(name.encode()))
    assert code
    xt.XTestFakeKeyEvent(display, code, True, 0)
    xt.XTestFakeKeyEvent(display, code, False, 0)
    x.XSync(display, False)
    time.sleep(.08)


def commit():
    subprocess.run(['fcitx5-remote', '-o'], env=env, check=True)
    time.sleep(.15)
    for char in 'nihao':
        key(char)
    time.sleep(.2)
    key('space')
    time.sleep(.5)


def run_case(name, library, body_class, parent_class, process_kind, expected_chinese):
    rows, pending = [], queue.Queue()
    log = (output / (name + '.log')).open('w')
    app = subprocess.Popen([wine, str(output / 'WeMail.exe'), body_class, parent_class, process_kind],
                           env=env | {'LD_PRELOAD': str(library)}, stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE, stderr=log, text=True, bufsize=1)

    def read():
        for line in app.stdout:
            if line.startswith('{'):
                value = json.loads(line)
                rows.append(value)
                pending.put(value)

    threading.Thread(target=read, daemon=True).start()
    result = {'name': name, 'class': body_class, 'parent_class': parent_class,
              'process_kind': process_kind, 'expected_chinese': expected_chinese, 'events': rows, 'passed': False}

    def wait_event(event):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            value = pending.get(timeout=max(.01, deadline - time.monotonic()))
            if value['event'] == event:
                return value
        raise TimeoutError(event)

    def units(field):
        return next((r['units'] for r in reversed(rows) if r['event'] == field), [])

    try:
        ready = wait_event('ready')
        time.sleep(.3)
        x.XSetInputFocus(display, ready['xid'], 2, 0)
        x.XSync(display, False)
        app.stdin.write('body\n')
        app.stdin.flush()
        ready = wait_event('ready')
        result['ready'] = ready
        assert ready['focus'] == ready['body'], ready
        assert (ready['body_pid'] == ready['root_pid']) == (process_kind == 'same-process'), ready
        subprocess.run(['gdbus', 'call', '--session', '--dest', 'org.fcitx.Fcitx5', '--object-path',
                        '/controller', '--method', 'org.fcitx.Fcitx.Controller1.SetCurrentIM', 'pinyin'],
                       env=env, check=True, capture_output=True)
        commit()
        result['body_after_commit'] = units('body')[:]
        chinese = [0x4f60, 0x597d] if expected_chinese else []
        assert units('body') == chinese, result
        subprocess.run(['fcitx5-remote', '-c'], env=env, check=True)
        time.sleep(.15)
        for char in 'abc123':
            key(char)
        time.sleep(.3)
        result['body_after_ascii'] = units('body')[:]
        assert units('body') == chinese + list(map(ord, 'abc123')), result
        app.stdin.write('subject\n')
        app.stdin.flush()
        wait_event('subject-focus')
        commit()
        result['subject_after_commit'] = units('subject')[:]
        assert units('subject') == [0x4f60, 0x597d], result
        result['passed'] = True
    except Exception as error:
        result['error'] = repr(error)
    finally:
        if app.poll() is None:
            app.stdin.write('quit\n')
            app.stdin.flush()
            try:
                app.wait(timeout=10)
            except subprocess.TimeoutExpired:
                app.terminate()
                app.wait(timeout=5)
        result['exit_code'] = app.returncode
        log.close()
        result['passed'] &= app.returncode == 0
        report['cases'].append(result)
        print(json.dumps({k: v for k, v in result.items() if k != 'events'}), flush=True)


fcitx = None
try:
    with (output / 'fcitx.log').open('w') as log:
        fcitx = subprocess.Popen(['fcitx5', '-r', '--disable=wayland,waylandim'],
                                env=env, stdout=log, stderr=log)
    selection = x.XInternAtom(display, b'@server=fcitx', False)
    deadline = time.monotonic() + 20
    while not x.XGetSelectionOwner(display, selection):
        assert fcitx.poll() is None
        assert time.monotonic() < deadline, 'Private Fcitx XIM startup timed out'
        time.sleep(.05)
    with (output / 'wineboot.log').open('w') as log:
        subprocess.run([wine, 'wineboot', '-u'], env=env, stdout=log, stderr=log, check=True, timeout=90)
        subprocess.run([wine, 'reg', 'add', 'HKCU\\Control Panel\\Desktop', '/v', 'LogPixels',
                        '/t', 'REG_DWORD', '/d', '192', '/f'], env=env, stdout=log, stderr=log,
                       check=True, timeout=20)
    subprocess.run([env['WINESERVER'], '-k'], env=env, check=True, timeout=10)
    subprocess.run([env['WINESERVER'], '-w'], env=env, check=True, timeout=10)
    cases = [('body0-baseline', args.baseline, 'Chrome_WidgetWin_0', 'CefBrowserWindow', 'foreign', False),
             ('body0-fixed', args.candidate, 'Chrome_WidgetWin_0', 'CefBrowserWindow', 'foreign', True),
             ('body1-baseline', args.baseline, 'Chrome_WidgetWin_1', 'CefBrowserWindow', 'foreign', True),
             ('body1-fixed', args.candidate, 'Chrome_WidgetWin_1', 'CefBrowserWindow', 'foreign', True),
             ('same-process', args.candidate, 'Chrome_WidgetWin_0', 'CefBrowserWindow', 'same-process', False),
             ('unrelated-parent', args.candidate, 'Chrome_WidgetWin_0', 'UnrelatedHostWindow', 'foreign', False),
             ('unsupported-class', args.candidate, 'Chrome_WidgetWin_2', 'CefBrowserWindow', 'foreign', False)]
    for case in cases:
        if not args.case or case[0] in args.case:
            run_case(*case)
    report['passed'] = bool(report['cases']) and all(row['passed'] for row in report['cases'])
finally:
    subprocess.run([env['WINESERVER'], '-k'], env=env, timeout=10)
    subprocess.run([env['WINESERVER'], '-w'], env=env, timeout=10)
    if fcitx and fcitx.poll() is None:
        fcitx.terminate()
        fcitx.wait(timeout=10)
    x.XCloseDisplay(display)
    (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
raise SystemExit(0 if report['passed'] else 1)
