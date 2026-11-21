#!/usr/bin/env python3
"""Compare a single meeting's Qt raster backing store with its physical client area."""
import argparse
import json
import re
import sys
from pathlib import Path

CREATED = re.compile(r'CreateWindowEx: returns \w+\((0x[\da-f]+)\b.*?\)\s+(0x[\da-f]+) obtained geometry:', re.I)
BACKING = re.compile(r'QWindowsBackingStore::(resize|flush)\s+(?:0x[\da-f]+\s+)?\w+\((0x[\da-f]+)\b', re.I)
SIZE = re.compile(r'\)\s+QSize\((\d+),\s*(\d+)\)')
GDI_EVENT = re.compile(
    r'(?:^|:)([\da-f]+):(Call|Ret)\s+(?:user32\.(CreateWindowExW|GetDC|ReleaseDC)|gdi32\.(BitBlt))'
    r'\(([^)]*)\)(?: retval=([\da-f]+))?', re.I)


def full_gdi_copy(log, hwnd, client, created=False):
    """Verify a successful full-client SRCCOPY between acquiring and releasing the room DC."""
    painted = False
    pending = {}
    active = {}
    for line in log:
        event = GDI_EVENT.search(line)
        if not event:
            continue
        thread, phase, user_fn, gdi_fn, args, result = event.groups()
        fn = user_fn or gdi_fn
        if fn == 'CreateWindowExW':
            if phase == 'Ret' and int(result, 16) == hwnd:
                if created:
                    raise ValueError('The trace contains two creations of the meeting HWND.')
                created = True
            continue
        if not created:
            continue
        key = (thread, fn)
        if phase == 'Call':
            pending[key] = [int(n, 16) for n in args.split(',')]
            continue
        call = pending.pop(key, [])
        value = int(result, 16)
        if fn == 'GetDC' and value:
            active.pop((thread, value), None)
            if call == [hwnd]:
                active[thread, value] = False
        elif fn == 'BitBlt' and len(call) == 9 and value:
            dc = (thread, call[0])
            if (dc in active and call[1:5] == [0, 0, *client] and call[5] and call[5] != call[0]
                    and call[6:] == [0, 0, 0x00cc0020]):
                active[dc] = True
        elif fn == 'ReleaseDC' and len(call) == 2:
            copied = active.pop((thread, call[1]), False)
            if value and call[0] == hwnd and copied:
                painted = True
    if not painted:
        raise ValueError('No complete unscaled GDI copy was verified for this meeting and client size.')


def seek_paint_phase(stream, offset, hwnd):
    """Require one creation of this HWND before the post-change repaint."""
    if offset <= 0:
        raise ValueError('The scale-change paint offset must be positive.')
    created = 0
    while stream.tell() < offset:
        line = stream.readline()
        if not line or stream.tell() > offset:
            raise ValueError('The scale-change offset must fall on a complete line in this trace.')
        event = GDI_EVENT.search(line.decode(errors='replace'))
        if event and event[2] == 'Ret' and event[3] == 'CreateWindowExW' and int(event[6], 16) == hwnd:
            created += 1
    if created != 1:
        raise ValueError('Expected one creation of the meeting HWND before the post-change repaint.')


def last_painted(log, hwnd):
    widget = None
    allocated = painted = None
    for line in log:
        created = CREATED.search(line)
        if created:
            obj, handle = (int(value, 16) for value in created.groups())
            if handle == hwnd:
                if widget is not None:
                    raise ValueError('The capture contains more than one creation of the meeting HWND.')
                widget = obj
            elif widget == obj:
                raise ValueError('The meeting Qt object was reused during the capture.')
            continue
        event = BACKING.search(line)
        if not event or int(event[2], 16) != widget:
            continue
        if event[1] == 'resize':
            value = SIZE.search(line, event.end())
            allocated = [int(n) for n in value.groups()] if value else None
        elif event[1] == 'flush':
            painted = allocated
    if not painted or min(painted) <= 0 or painted != allocated:
        raise ValueError('Missing an unambiguous resize followed by a flush for the measured meeting.')
    return painted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('window', type=Path, help='JSON lines from meeting-display.exe')
    parser.add_argument('paint_log', type=Path, help='fresh QPA or Wine GDI log from the meeting process')
    parser.add_argument('--gdi', action='store_true', help='verify a full-size GDI transfer in a Wine relay trace')
    parser.add_argument('--paint-offset', type=int, help='GDI trace offset after observing the new DPI, before repaint')
    args = parser.parse_args()
    try:
        samples = [json.loads(line) for line in args.window.read_text().splitlines() if line.strip()]
        samples = [sample for sample in samples if sample['phase'] != 'origin']
        phases = [sample['phase'] for sample in samples]
        changing = phases == ['before-scale', 'after-scale', 'repaint']
        if not changing and phases not in (['snapshot'], ['first-title-match', 'settled']):
            raise ValueError('Expected a completed window observation.')
        if changing != (args.paint_offset is not None) or (changing and not args.gdi):
            raise ValueError('A scale change requires --gdi and a post-change repaint offset.')
        observations = samples[:-1] if changing else samples
        last = observations[-1]
        hwnd, client = int(last['hwnd'], 16), last['client_px']
        if len(client) != 2 or min(client) <= 0 or any(sample['hwnd'] != last['hwnd'] for sample in samples):
            raise ValueError('A single meeting HWND and its physical client area are required.')
        if changing:
            if samples[0]['window_dpi'] == last['window_dpi']:
                raise ValueError('The before and after observations have the same DPI.')
            if samples[-1]['client_px'] != client or samples[-1]['window_dpi'] != last['window_dpi']:
                raise ValueError('The room changed DPI or size between observation and repaint.')
        elif any(sample['client_px'] != client for sample in samples):
            raise ValueError('The meeting changed size during the first-open observation.')
        checks = {}
        for field, label in [('size_ok', 'logical_size_ok'), ('native_dpi', 'native_dpi'),
                             ('output_dpi_ok', 'output_dpi_ok')]:
            if changing or any(field in sample for sample in observations):
                if any(not isinstance(sample.get(field), bool) for sample in observations):
                    raise ValueError(f'Missing or invalid {field} in the window observations.')
                checks[label] = all(sample[field] for sample in observations)
        if args.gdi:
            with args.paint_log.open('rb') as trace:
                if changing:
                    seek_paint_phase(trace, args.paint_offset, hwnd)
                full_gdi_copy((line.decode(errors='replace') for line in trace), hwnd, client, created=changing)
            result = {'hwnd': hex(hwnd), 'physical_client_px': client, 'unscaled_copy_px': client}
            print(json.dumps(result | checks))
            return int(not all(checks.values()))
        with args.paint_log.open(errors='replace') as log:
            pixels = last_painted(log, hwnd)
    except (OSError, KeyError, TypeError, ValueError) as error:
        print(error, file=sys.stderr)
        return 2
    print(json.dumps({'hwnd': hex(hwnd), 'physical_client_px': client, 'painted_buffer_px': pixels} | checks))
    return int(pixels != client or not all(checks.values()))


if __name__ == '__main__':
    sys.exit(main())
