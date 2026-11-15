#!/usr/bin/env python3
"""Type consecutive words through real private IBus and check the foreign editor's IMM results."""
import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time
import gi

gi.require_version('IBus', '1.0')
from gi.repository import GLib, IBus

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'frame-composition'))
from isolated import desktop

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime', type=Path, required=True)
parser.add_argument('--driver', type=Path)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--bits', choices=('32', '64'), default='64')
parser.add_argument('--expect-failure', action='store_true')
parser.add_argument('--trace', action='store_true')
args = parser.parse_args()
qa = args.output.resolve()
qa.mkdir(parents=True, exist_ok=False)
(qa / '.wecom-frame-qa').touch()
os.environ['WECOM_QA_ROOT'] = str(qa)
runtime = args.runtime.resolve()
driver = (args.driver or runtime / 'lib/wine/x86_64-unix/winex11.so').resolve()
overlay = qa / 'wine'
(overlay / 'lib/wine/x86_64-unix').mkdir(parents=True)
shutil.copytree(runtime / 'bin', overlay / 'bin', symlinks=True)
for name in ('share', 'include'):
    if (runtime / name).exists(): (overlay / name).symlink_to(runtime / name, target_is_directory=True)
for name in ('i386-windows', 'x86_64-windows'):
    (overlay / 'lib/wine' / name).symlink_to(runtime / 'lib/wine' / name, target_is_directory=True)
for path in (runtime / 'lib/wine/x86_64-unix').iterdir():
    dest = overlay / 'lib/wine/x86_64-unix' / path.name
    if path.name in ('wine', 'wine-preloader', 'ntdll.so'): shutil.copy2(path, dest)
    else: dest.symlink_to(path.resolve(), target_is_directory=path.is_dir())
(overlay / 'lib/wine/x86_64-unix/winex11.so').unlink()
shutil.copy2(driver, overlay / 'lib/wine/x86_64-unix/winex11.so')
compiler = 'i686-w64-mingw32-gcc' if args.bits == '32' else 'x86_64-w64-mingw32-gcc'
exe = qa / 'ime-process.exe'
subprocess.run([compiler, '-O2', '-Wall', '-Wextra', str(HERE / 'ime-process.c'), '-o', str(exe),
                '-limm32', '-luser32'], check=True)
report = {'bits': args.bits, 'events': [], 'account_data_used': False, 'host_desktop_used': False,
          'driver_sha256': hashlib.sha256(driver.read_bytes()).hexdigest()}
lines = queue.Queue()
app = ibus = None
loop = None


class WordEngine(IBus.Engine):
    """Deterministic words; the real daemon and XIM frontend deliver the callbacks."""
    __gtype_name__ = 'WeComContinuousEngine'

    def __init__(self, *arguments, **keywords):
        super().__init__(*arguments, **keywords)
        self.word = ''

    def do_process_key_event(self, keyval, keycode, state):
        if state & IBus.ModifierType.RELEASE_MASK: return False
        if keyval == ord(' ') and self.word:
            self.commit_text(IBus.Text.new_from_string(
                {'ceshi': '测试', 'wenjian': '文件', 'zhongwen': '中文'}.get(self.word, self.word)))
            self.word = ''
            self.hide_preedit_text()
            return True
        if ord('a') <= keyval <= ord('z'):
            self.word += chr(keyval)
            self.update_preedit_text(IBus.Text.new_from_string(self.word), len(self.word), True)
            return True
        return False

    def do_reset(self):
        self.word = ''
        self.hide_preedit_text()


def wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try: value = lines.get(timeout=max(.01, deadline - time.monotonic()))
        except queue.Empty: break
        if value is None: raise RuntimeError('Wine fixture exited')
        report['events'].append(value)
        if predicate(value): return value
    raise TimeoutError('Expected editor response did not arrive')


try:
    with desktop(qa, size='1600x1000', bare=True) as env:
        env.update(WINEPREFIX=str(qa / 'prefix'), WINESERVER=str(overlay / 'bin/wineserver'), WINEDEBUG='-all,+xim',
                   XMODIFIERS='@im=ibus', LANG='zh_CN.UTF-8', LC_CTYPE='zh_CN.UTF-8', WECOM_IME_FIXTURE='1',
                   WINEDLLOVERRIDES='winewayland.drv=d;mscoree,mshtml,winemenubuilder=',
                   IBUS_ADDRESS='unix:abstract=wecom-continuous-' + str(os.getpid()))
        if args.trace: env['WINEDEBUG'] = '-all,+xim,+imm,+timestamp,+pid'
        x = C.CDLL('libX11.so.6')
        xt = C.CDLL('libXtst.so.6')
        x.XOpenDisplay.argtypes = [C.c_char_p]; x.XOpenDisplay.restype = C.c_void_p
        x.XInternAtom.argtypes = [C.c_void_p, C.c_char_p, C.c_int]; x.XInternAtom.restype = C.c_ulong
        x.XGetSelectionOwner.argtypes = [C.c_void_p, C.c_ulong]; x.XGetSelectionOwner.restype = C.c_ulong
        x.XKeysymToKeycode.argtypes = [C.c_void_p, C.c_ulong]; x.XKeysymToKeycode.restype = C.c_uint
        x.XFlush.argtypes = [C.c_void_p]; x.XCloseDisplay.argtypes = [C.c_void_p]
        xt.XTestFakeKeyEvent.argtypes = [C.c_void_p, C.c_uint, C.c_int, C.c_ulong]
        old_auth = os.environ.get('XAUTHORITY')
        os.environ['XAUTHORITY'] = env['XAUTHORITY']
        display = x.XOpenDisplay(env['DISPLAY'].encode())
        if old_auth is None: os.environ.pop('XAUTHORITY', None)
        else: os.environ['XAUTHORITY'] = old_auth
        assert display and env['DISPLAY'] != ':0'
        with (qa / 'ibus.log').open('w') as bus_log, (qa / 'wine.log').open('w') as wine_log:
            ibus = subprocess.Popen(['ibus-daemon', '--xim', '--single', '--emoji-extension=disable',
                                     '--cache=none', '--address=' + env['IBUS_ADDRESS']],
                                    env=env, stdout=bus_log, stderr=bus_log)
            selection = x.XInternAtom(display, b'@server=ibus', False)
            deadline = time.monotonic() + 12
            while not x.XGetSelectionOwner(display, selection):
                assert ibus.poll() is None and time.monotonic() < deadline, 'Private IBus did not start'
                time.sleep(.03)
            app = subprocess.Popen([str(overlay / 'bin/wine'), str(exe), str(exe)], env=env,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=wine_log,
                                   text=True, bufsize=1)

            def read_lines():
                for line in app.stdout:
                    if line.startswith('{'): lines.put(json.loads(line))
                lines.put(None)

            threading.Thread(target=read_lines, daemon=True).start()
            report['ready'] = wait_for(lambda v: v['event'] == 'ready')
            os.environ['IBUS_ADDRESS'] = env['IBUS_ADDRESS']
            IBus.init()
            bus = IBus.Bus.new()
            assert bus.is_connected(), 'Private fixture engine could not connect'
            factory = IBus.Factory.new(bus.get_connection())
            factory.add_engine('wecom-continuous', WordEngine)
            component = IBus.Component.new('org.freedesktop.IBus.WeComContinuous', 'Continuous input fixture',
                                           '1', 'MIT', 'WeCom QA', '', '', '')
            component.add_engine(IBus.EngineDesc.new('wecom-continuous', 'WeCom QA', 'Fixture',
                                                    'zh_CN', 'MIT', 'WeCom QA', '', 'us'))
            assert bus.register_component(component)
            loop = GLib.MainLoop()
            threading.Thread(target=loop.run, daemon=True).start()
            assert bus.set_global_engine('wecom-continuous')
            time.sleep(.3)
            text = 'ceshi wenjian zhongwen ' * 4
            for character in text:
                key = x.XKeysymToKeycode(display, ord(character))
                assert key and xt.XTestFakeKeyEvent(display, key, True, 0)
                assert xt.XTestFakeKeyEvent(display, key, False, 0)
                x.XFlush(display)
                time.sleep(.008)
            time.sleep(.8)
            app.stdin.write('state\n'); app.stdin.flush()
            report['state'] = wait_for(lambda v: v['event'] == 'posted')
            report['native_owner_state'] = next(v for v in reversed(report['events']) if v['event'] == 'root-state')
            actual = [n for event in report['events'] for n in event.get('result', [])]
            expected = list(map(ord, '测试文件中文' * 4))
            report.update(actual=actual, expected=expected, input_interval_ms=8)
            functional = actual == expected and report['native_owner_state']['open'] == 1
            report['negative_control_reproduced'] = not functional if args.expect_failure else False
            report['passed'] = not functional if args.expect_failure else functional
            app.stdin.write('quit\n'); app.stdin.flush(); app.wait(timeout=10)
            assert app.returncode == 0
        x.XCloseDisplay(display)
except Exception as error:
    report.update(error=str(error), passed=False)
finally:
    if loop is not None: loop.quit()
    for process in (app, ibus):
        if process is not None and process.poll() is None:
            process.terminate(); process.wait(timeout=8)
    (qa / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({k: report.get(k) for k in ('passed', 'error', 'actual', 'expected', 'state')}))
sys.exit(0 if report['passed'] else 1)
