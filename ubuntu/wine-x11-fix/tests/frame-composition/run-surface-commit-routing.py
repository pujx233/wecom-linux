#!/usr/bin/env python3
"""Verify commit routing across actual nested Win32 windows, owners and process boundaries."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from isolated import desktop


def block(text, start):
    opening = text.index('{', start)
    depth = 1
    index = opening + 1
    while depth:
        depth += (text[index] == '{') - (text[index] == '}')
        index += 1
    return text[opening + 1:index - 1]


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
source = args.source.resolve() / 'dlls/winex11.drv/window.c'
text = source.read_text()
start = text.index('if (action == WINE_SURFACE_COMMIT)', text.index('static LRESULT surface_paint('))
after = start + len('if (action == WINE_SURFACE_COMMIT)')
if text[after:].lstrip().startswith('{'):
    commit = block(text, after)
else:
    commit = text[after:text.index(';', after) + 1]
start = text.index('case WM_X11DRV_SYNC_OWNED_FRAME:')
end = text.index('if ((data = get_win_data( hwnd )))', start)
owner = text[start + len('case WM_X11DRV_SYNC_OWNED_FRAME:'):end]
header = ('#define WM_X11DRV_SYNC_OWNED_FRAME 0x80001006u\n'
          'static void route_commit(HWND hwnd)\n{\n' + commit + '\n}\n'
          'static LRESULT route_owner_notification(HWND hwnd, WPARAM wp)\n{\n'
          '    (void)hwnd; (void)wp;\n' + owner + '\n    return -1;\n}\n')
(qa / 'surface-commit-source.h').write_text(header)
fixture = Path(__file__).with_name('surface-commit-routing.c')
for bits, compiler in [('32', 'i686-w64-mingw32-gcc'), ('64', 'x86_64-w64-mingw32-gcc')]:
    result = subprocess.run([compiler, '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(qa), str(fixture),
                             '-o', str(qa / ('commit-' + bits + '.exe')), '-lgdi32', '-luser32'],
                            capture_output=True, text=True)
    (qa / ('build-' + bits + '.log')).write_text(result.stdout + result.stderr)
    result.check_returncode()
report = {'host_desktop_used': False, 'account_data_used': False, 'real_win32_topology': True,
          'scope': 'Routing and call order; XSync and the local compositor are recording test functions',
          'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'cases': []}
with desktop(qa) as session:
    try:
        for bits in ('32', '64'):
            for framed in ('0', '1'):
                env = session | {'WINEPREFIX': str(qa / 'prefix'), 'WINEDEBUG': '-all',
                    'WINESERVER': str(qa / 'wine/bin/wineserver'), 'WINE_X11_OWNED_FRAME': framed,
                    'WINE_X11_FRAME_ATTACHED_CLASSES': 'CommitRoutingDecoration',
                    'WINE_X11_FRAME_DECORATION_CLASSES': 'CommitRoutingDecoration',
                    'WINEDLLOVERRIDES': 'winewayland.drv=d;mscoree,mshtml,winemenubuilder='}
                run = subprocess.run([str(qa / 'wine/bin/wine'), str(qa / ('commit-' + bits + '.exe')), framed],
                                     env=env, capture_output=True, text=True, timeout=30)
                rows = [json.loads(line) for line in run.stdout.splitlines() if line.startswith('{')]
                expected = 9 if framed == '1' else 7
                passed = run.returncode == 0 and len(rows) == expected and all(r['passed'] for r in rows)
                report['cases'].append({'bits': bits, 'frame': framed, 'returncode': run.returncode,
                                        'checks': rows, 'stderr': run.stderr, 'passed': passed})
    finally:
        env = session | {'WINEPREFIX': str(qa / 'prefix')}
        stop = subprocess.run([str(qa / 'wine/bin/wineserver'), '-k'], env=env, timeout=5)
        assert stop.returncode in (0, 1)
        subprocess.run([str(qa / 'wine/bin/wineserver'), '-w'], env=env, check=True, timeout=10)
report['passed'] = all(case['passed'] for case in report['cases'])
(qa / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'report': str(qa / 'result.json'), 'passed': report['passed']}))
raise SystemExit(0 if report['passed'] else 1)
