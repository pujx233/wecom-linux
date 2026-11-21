"""Check an X11 drawable and its composed pixels when the other output changes scale."""
import argparse
import json
import os
from pathlib import Path
import re
import select
import subprocess
import time

from gi.repository import Gio, GLib
from PIL import Image, ImageChops

from isolated import desktop
from screencast import recording


def set_layout(bus, env, right_scale):
    service = 'org.gnome.Mutter.DisplayConfig'
    path = '/org/gnome/Mutter/DisplayConfig'
    serial, monitors, _, _ = bus.call_sync(service, path, service, 'GetCurrentState', None, None,
                                          Gio.DBusCallFlags.NONE, 5000, None).unpack()
    modes = sorted((spec[0], next(m for m in available if m[6].get('is-current')))
                   for spec, available, _ in monitors)
    left, right = modes
    assert right_scale in right[1][5]
    logical = [(0, 0, 1., 0, True, [(left[0], left[1][0], {})]),
               (left[1][1], 0, right_scale, 0, False, [(right[0], right[1][0], {})])]
    bus.call_sync(service, path, service, 'ApplyMonitorsConfig',
                  GLib.Variant('(uua(iiduba(ssa{sv}))a{sv})', (serial, 1, logical, {})), None,
                  Gio.DBusCallFlags.NONE, 5000, None)
    panel = left[1][1:3]
    expected = [int(pixels * right_scale) for pixels in panel]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        lines = subprocess.check_output(['xrandr', '--listmonitors'], env=env, text=True).splitlines()[1:]
        for line in lines:
            if line.split()[-1] == left[0] and (match := re.search(r'(\d+)/\d+x(\d+)/', line)):
                if list(map(int, match.groups())) == expected:
                    return left[0], panel
        time.sleep(.05)
    raise TimeoutError('XRandR did not publish the expected coordinate space for the primary output.')


def color_bounds(image, color):
    delta = ImageChops.difference(image, Image.new('RGB', image.size, color))
    r, g, b = delta.split()
    return ImageChops.lighter(r, ImageChops.lighter(g, b)).point(lambda v: 255 if v < 12 else 0).getbbox()


def read_reply(proc):
    if not select.select([proc.stdout], [], [], 8)[0]:
        raise TimeoutError('The native X11 window received no configure reply.')
    reply = proc.stdout.readline().strip()
    if not reply:
        raise RuntimeError('The X11 client exited before reporting its geometry.')
    return reply


def measure(qa, env, proc, phase, output, panel, target, marker):
    width, height = target
    proc.stdin.write(f'{width} {height} {marker:06x}\n')
    proc.stdin.flush()
    result = json.loads(read_reply(proc))
    with recording(qa, env, phase, monitor=output) as capture:
        frame = qa / (phase + '-before.png')
        try:
            deadline = time.monotonic() + 5
            while True:
                with Image.open(frame) as raw:
                    assert tuple(panel) == raw.size
                    rgb = raw.convert('RGB')
                if color_bounds(rgb, f'#{marker:06x}'):
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError('The new paint did not reach the compositor output.')
                time.sleep(.05)
                capture(frame)
            body = color_bounds(rgb, '#15d934')
            right = color_bounds(rgb, '#f527bf')
        finally:
            frame.unlink(missing_ok=True)
    result.update(phase=phase, requested=target, panel=panel, body=body, right_marker=right)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--small', action='store_true', help='Use 1600×1000 and 2560×1440 outputs')
    args = parser.parse_args()
    qa = Path(os.environ['WECOM_QA_ROOT']).resolve()
    assert (qa / '.wecom-frame-qa').is_file() and os.environ.get('WECOM_QA_SCALE') != '2'
    left, right = ('1600x1000', '2560x1440') if args.small else ('1920x1080', '3840x2160')
    width, height = (732, 448) if args.small else (800, 500)
    app = qa / 'xwayland-scale'
    subprocess.run(['cc', '-O2', '-Wall', '-Wextra', '-Werror', str(Path(__file__).with_name('xwayland-scale.c')),
                    '-lX11', '-o', app], check=True)
    results = []
    with desktop(qa, left, second_monitor=right, boot_wine=False) as env:
        bus = Gio.DBusConnection.new_for_address_sync(
            env['DBUS_SESSION_BUS_ADDRESS'],
            Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None, None)
        try:
            output, panel = set_layout(bus, env, 1.)
            with subprocess.Popen([app, str(width), str(height)], env=env, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True) as proc:
                try:
                    assert read_reply(proc) == 'mapped'
                    for phase, scale, marker in [('initial', 1, 0x0b72ed), ('double', 2, 0xe56329),
                                                  ('restore', 1, 0x2284bb)]:
                        if phase != 'initial':
                            set_layout(bus, env, float(scale))
                        target = [width * scale, height * scale]
                        result = measure(qa, env, proc, phase, output, panel, target, marker)
                        body, edge = result['body'], result['right_marker']
                        result['passed'] = bool(result['configure'] == result['drawable'] == target and body
                                                and body[2] - body[0] == width and edge
                                                and 0 <= body[2] - edge[2] <= 4)
                        results.append(result)
                finally:
                    proc.stdin.close()
                    if proc.poll() is None:
                        proc.terminate()
        finally:
            bus.close_sync(None)
    print(json.dumps(results))
    return int(not all(row['passed'] for row in results))


if __name__ == '__main__':
    raise SystemExit(main())
