#!/usr/bin/env python3
"""Copy real Wine CF_HDROP selections through GTK/GIO in a private XWayland session."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gio, GLib


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime', required=True, type=Path)
parser.add_argument('--qa', required=True, type=Path)
parser.add_argument('--expect-unsupported', action='store_true',
                    help='Check the unpatched runtime as a negative control')
args = parser.parse_args()
runtime = args.runtime.resolve(strict=True)
qa = args.qa.resolve()
assert not qa.exists(), 'Use a new disposable QA directory'
qa.mkdir(parents=True)
(qa / '.wecom-frame-qa').touch()
(qa / 'wine').symlink_to(runtime, target_is_directory=True)
os.environ['WECOM_QA_ROOT'] = str(qa)
sys.path.insert(0, str(Path(__file__).resolve().parent / 'frame-composition'))
from isolated import desktop


def windows(path):
    return 'Z:' + str(path).replace('/', '\\')


fixtures = {}
for architecture, compiler in (('32', 'i686-w64-mingw32-gcc'), ('64', 'x86_64-w64-mingw32-gcc')):
    fixture = qa / ('clipboard' + architecture + '.exe')
    subprocess.run([compiler, '-std=gnu11', '-municode', '-O2', '-Wall', '-Wextra', '-Werror',
                    str(Path(__file__).with_name('clipboard-files.c')), '-o', str(fixture), '-luser32'], check=True)
    fixtures[architecture] = fixture

directory = qa / 'sources/nested directory'
directory.mkdir(parents=True)
sources = []
for index, name in enumerate(('ascii.txt', '中文 文件.txt', 'hash#percent%plus+semicolon;.txt')):
    path = directory / name
    path.write_bytes(bytes([0, 255, index]) + name.encode())
    sources.append(path)
cases = [('ascii', 'unicode', sources[:1]), ('unicode', 'unicode', sources[1:2]),
         ('escaped', 'unicode', sources[2:]), ('multiple', 'unicode', sources),
         ('ansi', 'ansi', sources[:1]), ('text', 'text', ['剪贴板 text 123'])]
report = {'negative_control': args.expect_unsupported, 'host_desktop_used': False, 'cases': []}

with desktop(qa) as env:
    env.update(WINEPREFIX=str(qa / 'prefix'), WINESERVER=str(runtime / 'bin/wineserver'),
               WINEDEBUG='-all', GDK_BACKEND='x11')
    os.environ.update(env)
    from gi.repository import Gdk, Gtk
    Gtk.init([])
    assert Gdk.Display.get_default().get_name() == env['DISPLAY']
    clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
    try:
        for architecture, fixture in fixtures.items():
            for name, mode, values in cases:
                output = qa / (architecture + '-' + name)
                output.mkdir()
                ready, done = output / 'ready', output / 'done'
                arguments = values if mode == 'text' else [windows(path) for path in values]
                with (output / 'wine.log').open('w') as log:
                    process = subprocess.Popen([str(runtime / 'bin/wine'), str(fixture), mode,
                                                windows(ready), windows(done), *arguments],
                                               env=env, stdout=log, stderr=log)
                try:
                    deadline = time.monotonic() + 15
                    while not ready.exists():
                        assert process.poll() is None, (architecture, name, process.returncode)
                        assert time.monotonic() < deadline, (architecture, name, 'clipboard owner not ready')
                        time.sleep(0.05)
                    if mode == 'text':
                        assert clipboard.wait_for_text() == values[0]
                        report['cases'].append({'architecture': architecture, 'case': name, 'passed': True})
                        continue
                    uris = clipboard.wait_for_uris()
                    assert uris and len(uris) == len(values), (architecture, name, uris)
                    for source, uri in zip(values, uris):
                        native = Gio.File.new_for_uri(uri)
                        target = output / source.name
                        try:
                            native.copy(Gio.File.new_for_path(str(target)), Gio.FileCopyFlags.NONE, None, None, None)
                        except GLib.Error as error:
                            assert args.expect_unsupported and error.matches(Gio.io_error_quark(),
                                                                            Gio.IOErrorEnum.NOT_SUPPORTED), error
                        else:
                            assert not args.expect_unsupported, 'Negative control unexpectedly copied a file'
                            assert Path(native.get_path()).resolve() == source
                            assert target.read_bytes() == source.read_bytes()
                    report['cases'].append({'architecture': architecture, 'case': name, 'uris': uris, 'passed': True})
                finally:
                    done.touch()
                    process.wait(timeout=5)
                    assert process.returncode == 0, (architecture, name, process.returncode)
    finally:
        for option in ('-k', '-w'):
            subprocess.run([str(runtime / 'bin/wineserver'), option], env=env, check=True, timeout=15)

report['passed'] = True
(qa / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(report, ensure_ascii=False, indent=2))
