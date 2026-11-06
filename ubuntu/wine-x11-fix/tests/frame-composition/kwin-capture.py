#!/usr/bin/env python3
"""Capture pixels from an owned KWin test session through its screenshot API."""
import argparse
import json
import os
from pathlib import Path
import tempfile
import time

from gi.repository import Gio, GLib
from PIL import Image

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('output', type=Path)
parser.add_argument('--area', nargs=4, type=int, default=[0, 0, 1969, 1108])
args = parser.parse_args()
qa = Path(os.environ['WECOM_QA_ROOT']).resolve(strict=True)
target = args.output.resolve()
assert (qa / '.wecom-frame-qa').is_file() and target.is_relative_to(qa)
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
options = {'native-resolution': GLib.Variant('b', False), 'hide-caller-windows': GLib.Variant('b', False)}
with tempfile.TemporaryFile(dir=qa) as raw_file:
    fds = Gio.UnixFDList.new()
    index = fds.append(raw_file.fileno())
    reply, _ = bus.call_with_unix_fd_list_sync(
        'org.kde.KWin.ScreenShot2', '/org/kde/KWin/ScreenShot2', 'org.kde.KWin.ScreenShot2',
        'CaptureArea', GLib.Variant('(iiuua{sv}h)', (*args.area, options, index)), None,
        Gio.DBusCallFlags.NONE, 10000, fds, None)
    metadata = reply.unpack()[0]
    fds = None
    size = metadata['stride'] * metadata['height']
    deadline = time.monotonic() + 10
    while os.fstat(raw_file.fileno()).st_size < size and time.monotonic() < deadline:
        time.sleep(.01)
    raw_file.seek(0)
    raw = raw_file.read()
assert len(raw) == size, (len(raw), metadata)
assert metadata['format'] in (4, 5, 6), metadata
image = Image.frombytes('RGBA', (metadata['width'], metadata['height']), raw,
                       'raw', 'BGRA', metadata['stride'])
image.save(target)
target.with_suffix('.json').write_text(json.dumps(metadata, indent=2) + '\n')
