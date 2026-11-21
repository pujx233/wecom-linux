"""Read XRandR monitor pixels and Mutter logical output geometry."""
import ctypes as C


class Monitor(C.Structure):
    _fields_ = [("name", C.c_ulong), ("primary", C.c_int),
                ("automatic", C.c_int), ("noutput", C.c_int),
                ("x", C.c_int), ("y", C.c_int),
                ("width", C.c_int), ("height", C.c_int),
                ("mwidth", C.c_int), ("mheight", C.c_int),
                ("outputs", C.POINTER(C.c_ulong))]


def x11_monitors():
    x, r = C.CDLL("libX11.so.6"), C.CDLL("libXrandr.so.2")
    x.XOpenDisplay.argtypes = [C.c_char_p]
    x.XOpenDisplay.restype = C.c_void_p
    x.XCloseDisplay.argtypes = [C.c_void_p]
    x.XDefaultRootWindow.argtypes = [C.c_void_p]
    x.XDefaultRootWindow.restype = C.c_ulong
    x.XGetAtomName.argtypes = [C.c_void_p, C.c_ulong]
    x.XGetAtomName.restype = C.c_void_p
    x.XFree.argtypes = [C.c_void_p]
    r.XRRGetMonitors.argtypes = [C.c_void_p, C.c_ulong, C.c_int, C.POINTER(C.c_int)]
    r.XRRGetMonitors.restype = C.POINTER(Monitor)
    r.XRRFreeMonitors.argtypes = [C.POINTER(Monitor)]
    display = x.XOpenDisplay(None)
    if not display:
        return []
    monitors = None
    try:
        count = C.c_int()
        monitors = r.XRRGetMonitors(display, x.XDefaultRootWindow(display), 1, C.byref(count))
        result = []
        for i in range(count.value if monitors else 0):
            m = monitors[i]
            name = x.XGetAtomName(display, m.name)
            if not name:
                continue
            try:
                item = {key: getattr(m, key) for key in
                        ("primary", "x", "y", "width", "height")}
                item["name"] = C.string_at(name).decode("utf-8")
                result.append(item)
            finally:
                x.XFree(name)
        return result
    finally:
        if monitors:
            r.XRRFreeMonitors(monitors)
        x.XCloseDisplay(display)


def gnome_outputs(state):
    """Convert Mutter's logical monitor layout into output rectangles."""
    _, monitors, logical_monitors, properties = state
    if properties.get("layout-mode") != 1:
        return []
    modes_by_name = {spec[0]: modes for spec, modes, _ in monitors}
    outputs = []
    for x, y, scale, transform, _, specs, _ in logical_monitors:
        if scale <= 0:
            return []
        for spec in specs:
            current = [mode for mode in modes_by_name[spec[0]] if mode[6].get("is-current")]
            if len(current) != 1:
                return []
            width, height = current[0][1:3]
            if transform in (1, 3, 5, 7):
                width, height = height, width
            outputs.append({"name": spec[0], "enabled": True, "pos": {"x": x, "y": y},
                            "size": {"width": round(width / scale), "height": round(height / scale)}})
    return outputs


def xwayland_dpi(monitors, outputs):
    """Return the common X pixels per logical inch for this compositor layout."""
    sizes = {output["name"]: output["size"] for output in outputs}
    if (not monitors or len(monitors) != len(sizes) or len(sizes) != len(outputs)
            or {m["name"] for m in monitors} != sizes.keys()):
        return None
    values = set()
    for monitor in monitors:
        size = sizes[monitor["name"]]
        for axis in ("width", "height"):
            if size[axis] <= 0 or monitor[axis] <= 0:
                return None
            values.add(round(96 * monitor[axis] / size[axis]))
    if len(values) == 1:
        dpi = values.pop()
        if 48 <= dpi <= 768:
            return dpi
    return None

