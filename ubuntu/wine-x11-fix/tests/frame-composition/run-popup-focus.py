"""Keep an active override-redirect popup focused while the WM reports its managed owner."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading

from isolated import desktop

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--bits', choices=('32', '64'), default='32')
parser.add_argument('--expect-focus-loss', action='store_true', help='Verify the unfixed driver reproduces the failure')
args = parser.parse_args()
qa = Path(os.environ['WECOM_QA_ROOT']).resolve()
wine, server = qa / 'wine/bin/wine', qa / 'wine/bin/wineserver'
driver = qa / 'wine/lib/wine/x86_64-unix/winex11.so'
source = Path(__file__).with_name('popup-focus.c')
executable = qa / 'popup-focus.exe'
compiler = 'i686-w64-mingw32-gcc' if args.bits == '32' else 'x86_64-w64-mingw32-gcc'
subprocess.run([compiler, '-O2', '-Wall', '-Wextra', str(source), '-o', str(executable), '-luser32'], check=True)
report = {'host_desktop_used': False, 'account_used': False, 'bits': int(args.bits),
          'driver_sha256': hashlib.sha256(driver.read_bytes()).hexdigest(),
          'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
          'expected_focus_loss': args.expect_focus_loss}
with desktop(qa, size='3200x2000') as env:
    env.update(WINEPREFIX=str(qa / 'prefix'), WINESERVER=str(server), WINEDEBUG='-all',
               WINE_X11_OWNED_FRAME='1',
               WINEDLLOVERRIDES='winewayland.drv=d;mscoree,mshtml,winemenubuilder=')
    with (qa / 'prefix-settings.log').open('w') as log:
        subprocess.run([str(wine), 'reg', 'add', r'HKCU\Control Panel\Desktop', '/v', 'LogPixels',
                        '/t', 'REG_DWORD', '/d', '192', '/f'], env=env, stdout=log, stderr=log,
                       check=True, timeout=30)
    subprocess.run([str(server), '-k'], env=env, check=True, timeout=15)
    subprocess.run([str(server), '-w'], env=env, check=True, timeout=15)
    with (qa / 'fixture.log').open('w') as log:
        app = subprocess.Popen([str(wine), str(executable)], env=env, stdout=subprocess.PIPE,
                               stderr=log, text=True, bufsize=1)
        try:
            lines = queue.Queue()

            def read():
                for line in app.stdout:
                    lines.put(json.loads(line))

            threading.Thread(target=read, daemon=True).start()
            ready = lines.get(timeout=25)
            assert ready['event'] == 'popup', ready
            xid = str(ready['body'])
            properties = subprocess.run(['xprop', '-id', xid, '_NET_WM_PID'], env=env,
                                        capture_output=True, text=True, check=True, timeout=5).stdout
            pid = int(properties.rsplit('=', 1)[1])
            mapping = [line for line in Path(f'/proc/{pid}/maps').read_text().splitlines()
                       if 'winex11' in line and '.so' in line]
            assert {int(line.split()[4]) for line in mapping} == {driver.stat().st_ino}, mapping
            info = subprocess.run(['xwininfo', '-id', xid], env=env, capture_output=True,
                                  text=True, check=True, timeout=5).stdout
            result = lines.get(timeout=10)
            report.update(result=result, native_unmanaged='Override Redirect State: yes' in info,
                          mapped_paths=sorted({line.split()[-1] for line in mapping}),
                          returncode=app.wait(timeout=10))
            if args.expect_focus_loss:
                passed = (report['returncode'] == 1 and result['focused'] < result['samples'] and
                          result['lost'] > 0 and not result['visible'])
            else:
                passed = (report['returncode'] == 0 and result['focused'] == result['samples'] == 20 and
                          result['lost'] == 0 and result['visible'])
            report['passed'] = report['native_unmanaged'] and passed
        finally:
            if app.poll() is None:
                app.terminate()
                app.wait(timeout=10)
            subprocess.run([str(server), '-k'], env=env, timeout=15)
            subprocess.run([str(server), '-w'], env=env, check=True, timeout=15)
(qa / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
raise SystemExit(0 if report['passed'] else 1)
