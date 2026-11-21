#!/usr/bin/env python3
"""Exercise production frame pixels and cross-client resource lifetime on private X11."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
from isolated import desktop


def function(text, signature):
    start = text.index(signature)
    return text[start:text.index('\n}', start) + 2]


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--runtime', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
qa = args.output.resolve()
qa.mkdir(parents=True, exist_ok=False)
(qa / '.wecom-frame-qa').touch()
(qa / 'wine').symlink_to(args.runtime.resolve())
os.environ['WECOM_QA_ROOT'] = str(qa)
source = args.source.resolve() / 'dlls/winex11.drv'
xrender = (source / 'xrender.c').read_text()
main = (source / 'x11drv_main.c').read_text()
header = ''
for signature in ('static inline BOOL ignore_error(', 'void X11DRV_expect_error(',
                  'int X11DRV_check_error(', 'static int error_handler('):
    header += function(main, signature) + '\n\n'
header += function(xrender, 'static Picture get_mask_pict(') + '\n\n'
start = xrender.index('struct frame_compositor\n')
end = xrender.index('\n/***********************************************************************', start)
header += xrender[start:end]
header += '\n\n' + function((source / 'frame.c').read_text(), 'static BOOL frame_damage_notify(')
has_present = 'void X11DRV_PresentFrame(' in header
if has_present:
    header = '#define HAVE_FRAME_PRESENT 1\n' + header
(qa / 'frame-production.h').write_text(header)
fixture = Path(__file__).with_name('frame-compositor.c')
command = ['cc', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', '-I', str(qa),
           str(fixture), '-o', str(qa / 'frame-compositor'), '-lX11', '-lXcomposite',
           '-lXrender', '-lXext', '-lXdamage', '-lpthread']
build = subprocess.run(command, capture_output=True, text=True)
(qa / 'build.log').write_text(build.stdout + build.stderr)
build.check_returncode()
report = {'host_desktop_used': False, 'account_data_used': False, 'real_x11': True,
          'production_error_policy': True, 'has_present': has_present, 'cases': [], 'sha256': {}}
for path in (source / 'xrender.c', source / 'x11drv_main.c', fixture, Path(__file__), qa / 'frame-production.h'):
    report['sha256'][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
with desktop(qa) as env:
    try:
        for case in ('presentation', *(['host-growth'] if has_present else []),
                     'destroy-before-name', 'unmap-before-name',
                     'destroy-after-name', 'input-only', 'unexpected-error'):
            run = subprocess.run([str(qa / 'frame-compositor'), case], env=env,
                                 capture_output=True, text=True, timeout=15)
            expected = 1 if case == 'unexpected-error' else 0
            passed = run.returncode == expected
            if case == 'unexpected-error':
                passed &= 'BadMatch' in run.stderr and 'Composite' in run.stderr
            report['cases'].append({'name': case, 'returncode': run.returncode, 'expected': expected,
                                    'stdout': run.stdout, 'stderr': run.stderr, 'passed': passed})
    finally:
        private = env | {'WINEPREFIX': str(qa / 'prefix')}
        subprocess.run([str(qa / 'wine/bin/wineserver'), '-k'], env=private, check=True, timeout=5)
        subprocess.run([str(qa / 'wine/bin/wineserver'), '-w'], env=private, check=True, timeout=10)
# Xwayland need not honor the server grab used to delay one connection. Use a private Xvfb
# for the ordering race; the presentation/lifetime cases above continue to run on Mutter.
read_fd, write_fd = os.pipe()
try:
    with (qa / 'damage-xvfb.log').open('w') as log:
        server = subprocess.Popen([shutil.which('Xvfb') or 'Xvfb', '-displayfd', str(write_fd),
            '-screen', '0', '800x600x24', '-nolisten', 'tcp', '-noreset', '-ac'],
            pass_fds=(write_fd,), stdout=log, stderr=log)
        os.close(write_fd)
        write_fd = -1
        try:
            if not select.select([read_fd], [], [], 10)[0]:
                raise TimeoutError('private damage Xvfb did not start')
            number = os.read(read_fd, 40).decode().strip()
            assert number.isdigit(), number
            env = os.environ | {'DISPLAY': ':' + number}
            env.pop('XAUTHORITY', None)
            for case in ('damage-cross', 'damage-same'):
                run = subprocess.run([str(qa / 'frame-compositor'), case], env=env,
                                     capture_output=True, text=True, timeout=15)
                report['cases'].append({'name': case, 'returncode': run.returncode, 'expected': 0,
                    'stdout': run.stdout, 'stderr': run.stderr, 'passed': run.returncode == 0})
        finally:
            server.terminate()
            server.wait(timeout=5)
finally:
    os.close(read_fd)
    if write_fd != -1:
        os.close(write_fd)
report['passed'] = all(case['passed'] for case in report['cases'])
(qa / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'report': str(qa / 'result.json'), 'passed': report['passed']}))
raise SystemExit(0 if report['passed'] else 1)
