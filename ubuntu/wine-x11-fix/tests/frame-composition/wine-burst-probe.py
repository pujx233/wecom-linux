import json
import hashlib
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time
from PIL import Image, ImageChops

sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolated import desktop
from screencast import recording

qa = Path(sys.argv[1]).resolve()
qa.mkdir(exist_ok=True)
run = sys.argv[3]
(qa / '.wecom-frame-qa').touch()
(qa / 'wine').unlink(missing_ok=True)
(qa / 'wine').symlink_to(Path(sys.argv[2]).resolve())
os.environ['WECOM_QA_ROOT'] = str(qa)
source = Path(__file__).with_name('popup-burst.c')
subprocess.run(['x86_64-w64-mingw32-gcc', '-O2', '-Wall', '-Wextra', '-Werror', str(source),
                '-o', str(qa / 'popup.exe'), '-luser32', '-lgdi32'], check=True)
report = {'states': [], 'pixels': [], 'phases': {},
          'driver': hashlib.sha256((qa / 'wine/lib/wine/x86_64-unix/winex11.so').read_bytes()).hexdigest()}
with desktop(qa) as env:
    env.update(WINEPREFIX=str(qa / 'prefix'), WINESERVER=str(qa / 'wine/bin/wineserver'),
               WINEDEBUG='-all,+x11drv', WINE_X11_OWNED_FRAME='1',
               WINE_X11_FRAME_ATTACHED_CLASSES='PopupShadowDecoration',
               WINE_X11_FRAME_DECORATION_CLASSES='PopupShadowDecoration',
               WINE_WECOM_FIRST_PRESENT_ARGB='1', WINE_X11_FIXED_TRANSIENT_ARGB='1',
               WINE_X11_FIXED_TRANSIENT_UTILITY='1',
               WINEDLLOVERRIDES='winewayland.drv=d;mscoree,mshtml,winemenubuilder=')
    with recording(qa, env, run) as capture, (qa / (run + '.log')).open('w') as log:
        app = subprocess.Popen([str(qa / 'wine/bin/wine'), str(qa / 'popup.exe')], env=env,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                               text=True, bufsize=1)
        replies = queue.Queue()
        def read():
            for line in app.stdout:
                replies.put(json.loads(line))
        threading.Thread(target=read, daemon=True).start()
        frames = qa / (run + '-saved')
        frames.mkdir()
        seen = set()
        def collect(phase):
            for p in sorted((qa / (run + '-frames')).glob('*.png')):
                if p.name in seen:
                    continue
                try:
                    data = p.read_bytes()
                except FileNotFoundError:
                    continue
                if data.endswith(b'IEND\xaeB`\x82'):
                    (frames / p.name).write_bytes(data)
                    report['phases'][p.name] = phase
                    seen.add(p.name)
        try:
            report['states'].append(replies.get(timeout=15))
            mappings = [s for s in Path(f'/proc/{app.pid}/maps').read_text().splitlines() if '/winex11.so' in s]
            expected_inode = (qa / 'wine/lib/wine/x86_64-unix/winex11.so').stat().st_ino
            assert mappings and all(int(s.split()[4]) == expected_inode for s in mappings), mappings
            report['loaded_driver_verified'] = True
            for command in ('both', 'close') * 6:
                app.stdin.write(command + '\n'); app.stdin.flush()
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    collect(command)
                    time.sleep(.005)
                report['states'].append(replies.get(timeout=5))
        finally:
            if app.poll() is None:
                app.stdin.write('quit\n'); app.stdin.flush(); app.wait(timeout=5)
            subprocess.run([env['WINESERVER'], '-k'], env=env, timeout=5)
            subprocess.run([env['WINESERVER'], '-w'], env=env, timeout=10)
for path in sorted((qa / (run + '-saved')).glob('*.png')):
    im = Image.open(path).convert('RGB')
    r, g, b = im.split()
    mask = ImageChops.multiply(g.point(lambda x: 255 if x > 245 else 0),
                              ImageChops.add(r, b).point(lambda x: 255 if x < 10 else 0))
    bbox = mask.getbbox()
    if not report['pixels'] or report['pixels'][-1]['bbox'] != bbox:
        report['pixels'].append({'frame': path.name, 'phase': report['phases'][path.name], 'bbox': bbox})
visible = [state for state in report['pixels'] if state['bbox']]
report['visible_opens'] = len(visible)
report['wrong_bounds'] = sum(state['bbox'] != (500, 300, 1140, 1260) for state in visible)
report['passed'] = report['visible_opens'] == 6 and report['wrong_bounds'] == 0
(qa / (run + '.json')).write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
