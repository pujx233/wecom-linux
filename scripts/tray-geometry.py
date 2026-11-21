#!/usr/bin/env python3
"""Print guarded Wine tray correction parameters for KDE/GNOME Wayland/XWayland."""
import json
import os
import subprocess
import sys

from display_geometry import gnome_outputs, x11_monitors


def correction(xmonitors, outputs):
    """Map each output's native desktop coordinates into the XWayland desktop."""
    primary = [m for m in xmonitors if m["primary"]]
    if len(primary) != 1:
        return None
    p = primary[0]
    enabled = [o for o in outputs if o.get("enabled")]
    if len(enabled) != len(xmonitors) or len(xmonitors) > 16:
        return None
    mappings = []
    for monitor in xmonitors:
        matches = [o for o in enabled if o.get("name") == monitor["name"]]
        if len(matches) != 1:
            return None
        output = matches[0]
        source = (output["pos"]["x"] - p["x"], output["pos"]["y"] - p["y"],
                  output["size"]["width"], output["size"]["height"])
        target = (monitor["x"] - p["x"], monitor["y"] - p["y"],
                  monitor["width"], monitor["height"])
        if min(source[2:] + target[2:]) <= 0:
            return None
        mappings.append(source + target)
    if all(row[:4] == row[4:] for row in mappings):
        return None
    left, top = min(m["x"] for m in xmonitors), min(m["y"] for m in xmonitors)
    right = max(m["x"] + m["width"] for m in xmonitors)
    bottom = max(m["y"] + m["height"] for m in xmonitors)
    header = (2, left - p["x"], top - p["y"], right - left, bottom - top,
              p["width"], p["height"], len(xmonitors))
    return ";".join(",".join(map(str, row)) for row in [header] + mappings)


def main():
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").split(":")
    if (os.environ.get("XDG_SESSION_TYPE") != "wayland" or
            not any(name in desktop for name in ("KDE", "GNOME")) or
            os.environ.get("WECOM_TRAY_FIX") == "0"):
        return
    try:
        if "KDE" in desktop:
            result = subprocess.run(["kscreen-doctor", "-j"], capture_output=True,
                                    text=True, timeout=3, check=True)
            outputs = json.loads(result.stdout)["outputs"]
        else:
            from gi.repository import Gio, GLib
            try:
                bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
                state = bus.call_sync("org.gnome.Mutter.DisplayConfig", "/org/gnome/Mutter/DisplayConfig",
                                      "org.gnome.Mutter.DisplayConfig", "GetCurrentState", None, None,
                                      Gio.DBusCallFlags.NONE, 3000, None).unpack()
            except GLib.Error as exc:
                print(f"Tray coordinate correction unavailable: {type(exc).__name__}", file=sys.stderr)
                return
            outputs = gnome_outputs(state)
        parameters = correction(x11_monitors(), outputs)
        if parameters:
            print(parameters)
    except (ImportError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(f"Tray coordinate correction unavailable: {type(exc).__name__}", file=sys.stderr)


if __name__ == "__main__":
    main()
