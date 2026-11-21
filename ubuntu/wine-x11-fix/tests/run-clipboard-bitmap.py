#!/usr/bin/env python3
"""Check bitmap pixels across both Windows architectures and the native X11 clipboard."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import select
import subprocess
import sys

import gi
gi.require_version('Gtk', '3.0')

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime', required=True, type=Path)
parser.add_argument('--output', required=True, type=Path)
parser.add_argument('--previous-runtime', type=Path, help='Published runtime to keep active during upgrade')
args = parser.parse_args()
runtime, qa = args.runtime.resolve(strict=True), args.output.resolve()
qa.mkdir(parents=True, exist_ok=False)
(qa / '.wecom-frame-qa').touch()
(qa / 'wine').symlink_to(runtime)
os.environ['WECOM_QA_ROOT'] = str(qa)
sys.path.insert(0, str(Path(__file__).with_name('frame-composition')))
from isolated import desktop, processes

executables = {}
report = dict(cases=[], modules={}, host_desktop_used=False, account_used=False)
for bits, arch, compiler in [('32', 'i386', 'i686-w64-mingw32-gcc'),
                              ('64', 'x86_64', 'x86_64-w64-mingw32-gcc')]:
    executable = qa / ('clipboard-' + bits + '.exe')
    subprocess.run([compiler, '-O2', '-Wall', '-Wextra', '-Werror',
                    str(Path(__file__).with_name('clipboard-bitmap.c')), '-o', str(executable),
                    '-luser32', '-lgdi32'], check=True)
    executables[bits] = executable
    module = runtime / 'lib/wine' / (arch + '-windows') / 'user32.dll'
    report['modules'][bits] = hashlib.sha256(module.read_bytes()).hexdigest()


@contextmanager
def publisher(loader, bits, directory, env):
    done = directory / ('publisher-' + bits + '.done')
    done.unlink(missing_ok=True)
    with (directory / ('publisher-' + bits + '.log')).open('w') as log:
        with subprocess.Popen([str(loader / 'bin/wine'), str(executables[bits]), 'write',
                               'Z:' + str(done).replace('/', '\\')], env=env,
                              stdout=subprocess.PIPE, stderr=log, text=True) as owner:
            try:
                assert select.select([owner.stdout], [], [], 15)[0], 'Clipboard publisher timed out'
                assert owner.stdout.readline().strip() == 'ready', 'Clipboard publisher failed'
                architecture = 'i386' if bits == '32' else 'x86_64'
                module = (loader / 'lib/wine' / (architecture + '-windows') / 'user32.dll').resolve()
                mapped = set()
                for pid, _ in processes(directory):
                    try:
                        mappings = Path(f'/proc/{pid}/maps').read_text().splitlines()
                    except (FileNotFoundError, ProcessLookupError):
                        continue
                    if any(line.endswith(' ' + str(executables[bits])) for line in mappings):
                        mapped.update(Path(line.split(None, 5)[5]) for line in mappings if line.endswith('/user32.dll'))
                expected = hashlib.sha256(module.read_bytes()).digest()
                assert any(hashlib.sha256(path.read_bytes()).digest() == expected for path in mapped), (module, mapped)
                yield
            finally:
                done.touch()
                owner.wait(timeout=5)


def read_bitmap(loader, source, destination, env, source_version='current', destination_version='current'):
    result = subprocess.run([str(loader / 'bin/wine'), str(executables[destination]), 'read'], env=env,
                            capture_output=True, text=True, timeout=10)
    report['cases'].append(dict(source=source, destination=destination, source_version=source_version,
                                destination_version=destination_version, passed=result.returncode == 0,
                                output=result.stdout, stderr=result.stderr))


with desktop(qa, bare=True) as env:
    env.update(WINEPREFIX=str(qa / 'prefix'), WINESERVER=str(runtime / 'bin/wineserver'),
               WINEDEBUG='-all', GDK_BACKEND='x11')
    os.environ.update(env)
    from gi.repository import Gtk, Gdk
    Gtk.init([])
    assert Gdk.Display.get_default().get_name() == env['DISPLAY']
    clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
    for source in executables:
        with publisher(runtime, source, qa, env):
            for destination in executables:
                read_bitmap(runtime, source, destination, env)
            pixels = clipboard.wait_for_image()
            assert pixels is not None, 'Native clipboard could not read the bitmap'
            pixels.savev(str(qa / ('native-' + source + '.png')), 'png', [], [])
            from PIL import Image
            actual = Image.open(qa / ('native-' + source + '.png')).convert('RGB')
            expected = [(17, 34, 51), (68, 85, 102), (119, 136, 153),
                        (171, 205, 239), (171, 205, 239), (0, 255, 0)]
            report['cases'].append(dict(source=source, destination='native',
                                        passed=actual.size == (3, 2) and
                                        [actual.getpixel((x, y)) for y in range(2) for x in range(3)] == expected))

if args.previous_runtime:
    previous = args.previous_runtime.resolve(strict=True)
    old_session = qa / 'previous'
    old_session.mkdir()
    (old_session / '.wecom-frame-qa').touch()
    (old_session / 'wine').symlink_to(previous)
    os.environ['WECOM_QA_ROOT'] = str(old_session)
    with desktop(old_session, bare=True) as env:
        env.update(WINEPREFIX=str(old_session / 'prefix'), WINESERVER=str(previous / 'bin/wineserver'),
                   WINEDEBUG='-all')
        for source in executables:
            with publisher(previous, source, old_session, env):
                read_bitmap(previous, source, source, env, 'previous', 'previous')
                for destination in executables:
                    read_bitmap(runtime, source, destination, env, 'previous')
            with publisher(runtime, source, old_session, env):
                read_bitmap(previous, source, source, env, 'current', 'previous')

expected_cases = 14 if args.previous_runtime else 6
report['passed'] = len(report['cases']) == expected_cases and all(row['passed'] for row in report['cases'])
(qa / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
assert report['passed'], report
print(f'PASS: {expected_cases} clipboard pixel checks')
