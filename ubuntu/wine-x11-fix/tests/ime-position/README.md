# XIM candidate position regression

This fixture checks the actual IBus `SetCursorLocation` requests against the
rendered client's physical coordinates. It creates a disposable Wine prefix and a private
Mutter/Xwayland and IBus session. It does not use account data, type into WeCom,
or change the host display configuration.

Run from any directory:

```sh
python3 run-isolated.py \
  --runtime /absolute/path/to/private/wine \
  --driver /absolute/path/to/winex11.so \
  --core /absolute/path/to/win32u.so \
  --output /absolute/path/to/test-output \
  --name pm192 --dpi 192 --awareness pm
```

The output directory must be empty or already carry the fixture's marker. Report
names cannot be reused. Binaries, logs, reports and the disposable prefix stay
under that directory. `--driver` and `--core` default to the supplied runtime;
pass both when testing the paired X11/core change. The report records native core,
driver, server, IMM32, fixture and runner hashes, checks the private processes' mapped
module paths, and verifies that the loaded
IMM32 matches the selected runtime and application architecture.
Caret cases require `CreateCaret`, `SetCaretPos` and `ShowCaret` to succeed. Explicit
composition requests exercise the IMM32-to-win32u dispatch through the public API;
there is no test-only production caret query. Run against the installed runtime after
every component replacement; an older report only validates its recorded binary set.

The existing `frame-composition/isolated.py` supplies the private desktop. This
requires its Mutter/Python GI dependencies, IBus, `dbus-monitor`, X11 libraries,
and the MinGW compiler selected by `--bits 32` or `--bits 64`.

The default 21 cases cover:

- Caret movement, line changes, and 24/48-unit caret heights.
- Explicit composition points matching the caret and unrelated composition points.
- Large and one-unit `CFS_RECT` regions at the caret origin, both retaining their supplied origin.
- `CFS_FORCE_POSITION` at the caret origin, without automatic movement below the caret.
- Moving, maximizing and restoring the window while retaining both point and forced-position anchors.
- Changing the focused child and destroying the previous caret.

`--preedit position` requests server-side preedit and keeps automatic updates at the
caret's top edge. The runner checks the actual selected XIM style in the Wine log.
Automatic caret updates use the lower edge only for XIM callback preedit. Explicit
`ImmSetCompositionWindow` requests retain their supplied anchor; the fixture no longer
treats a point coinciding with the caret as proof of an automatic caret update. This
checks the Wine-to-XIM anchor, not whether every host IME honors forced placement.
See the [COMPOSITIONFORM contract](https://learn.microsoft.com/en-us/windows/win32/api/imm/ns-imm-compositionform).

The fixture records `ClientToScreen` followed by
`LogicalToPhysicalPointForPerMonitorDPI` for both the anchor and root client
rectangle. The acceptance oracle adds the anchor's local physical displacement
to the actual X client origin from `XTranslateCoordinates`. `XGetGeometry` must
independently match the physical root client size before that mapping is used.
Reports retain both this native `expected` and the original `win32_expected`,
plus native origins and sizes. This exposes differences between Wine's stored
screen geometry and the X window's placement without allowing a tolerance or
adding an offset. Position assertions require exact coordinate equality.
`--awareness unaware --dpi 192` checks scaling from the
application's 96-DPI coordinate space. Also run `--dpi 96`, `--bits 32`, and
`--frame 0` to cover ordinary X11 windows without shared-frame composition.

`--mixed-scale` adds a second virtual monitor and temporarily configures only
the private compositor to 100%/200%. It adds six cases that move between monitors
and update composition/caret positions there. These assertions cover IBus's
physical screen-coordinate requests, not the host GNOME candidate panel's pixel
appearance. The runner verifies that it is using a different session bus and
X display before configuring the private monitors.

A nonzero exit or `passed: false` is a failure. Collection completion alone is
not acceptance. The runner only checks the APIs in the cases above; explicit
candidate-position APIs and cross-process hosted input need separate coverage. The
existing automatic caret path can still replace an explicit composition anchor after
`SetCaretPos` or `ShowCaret`; persistent IMC positioning policy is not covered or fixed
by these per-request tests.
The fixture refuses to run directly on host `DISPLAY=:0`.
