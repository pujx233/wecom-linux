#!/usr/bin/env python3
"""Exercise the XWayland DPI fallback with independently specified display layouts."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
from display_geometry import gnome_outputs, xwayland_dpi


class DisplayDpi(unittest.TestCase):
    def measure(self, outputs, monitors):
        modes, logical = [], []
        x = 0
        for i, (name, width, height, scale, transform) in enumerate(outputs):
            spec = (name, '', '', '')
            modes.append((spec, [('mode', width, height, 60, scale, [], {'is-current': True})], {}))
            logical.append((x, 0, scale, transform, i == 0, [spec], {}))
            x += round((height if transform % 2 else width) / scale)
        state = (1, modes, logical, {'layout-mode': 1})
        x11 = [dict(name=name, width=w, height=h) for name, w, h in monitors]
        return xwayland_dpi(x11, gnome_outputs(state))

    def test_fractional_desktop(self):
        for scale, widths in [(1.25, (3072, 6144)), (1.5, (2560, 5120))]:
            with self.subTest(scale=scale):
                outputs = [('A', 1920, 1080, scale, 0), ('B', 3840, 2160, scale, 0)]
                self.assertEqual(self.measure(outputs, [
                    ('B', widths[1], round(4320 / scale)), ('A', widths[0], round(2160 / scale)),
                ]), 192)

    def test_mixed_and_rotated(self):
        outputs = [('A', 1920, 1080, 1, 1), ('B', 3840, 2160, 2, 0)]
        self.assertEqual(self.measure(outputs, [('A', 2160, 3840), ('B', 3840, 2160)]), 192)
        self.assertEqual(self.measure(outputs, [('A', 1080, 1920), ('B', 1920, 1080)]), 96)

    def test_change_only_one_output_resolution(self):
        for width, height in [(2560, 1440), (3840, 2160)]:
            with self.subTest(scale=1, mode=(width, height)):
                outputs = [('A', 1920, 1080, 1, 0), ('B', width, height, 1, 0)]
                self.assertEqual(self.measure(outputs, [('A', 1920, 1080), ('B', width, height)]), 96)
        for width, height, x_width, x_height in [(1920, 1080, 3072, 1728), (3200, 2000, 5120, 3200)]:
            with self.subTest(scale=1.25, mode=(width, height)):
                outputs = [('A', width, height, 1.25, 0), ('B', 3840, 2160, 1.25, 0)]
                self.assertEqual(self.measure(outputs, [('A', x_width, x_height), ('B', 6144, 3456)]), 192)

    def test_inconsistent_layout(self):
        outputs = [('A', 1920, 1080, 1, 0), ('B', 3840, 2160, 2, 0)]
        for monitors in [
            [('A', 1920, 1080)], [('A', 1920, 1080), ('C', 1920, 1080)],
            [('A', 1920, 1080), ('B', 3840, 2160)], [('A', 1920, 2160), ('B', 1920, 1080)],
        ]:
            with self.subTest(monitors=monitors):
                self.assertIsNone(self.measure(outputs, monitors))


if __name__ == '__main__':
    unittest.main()
