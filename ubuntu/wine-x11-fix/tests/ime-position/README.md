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
names cannot be reused. Each report creates its runtime overlay and disposable prefix
under a new subdirectory named by `--name`; reusing the output directory never reuses
an earlier report's loader, server or PE libraries. Binaries, logs and reports stay
under the output directory. `--driver` and `--core` default to the supplied runtime;
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

The default 23 cases cover:

- Caret movement, line changes, and 24/48-unit caret heights.
- Explicit composition points matching the caret and unrelated composition points.
- Large and one-unit `CFS_RECT` regions at the caret origin, both retaining their supplied origin.
- `CFS_FORCE_POSITION` with a matching caret and after the caret is destroyed.
- Moving, maximizing and restoring the window while retaining both point and forced-position anchors.
- Changing the focused child, requesting a point for the previous input, and destroying the previous caret.

`--preedit position` requests server-side preedit and keeps automatic updates at the
caret's top edge. The runner checks the actual selected XIM style in the Wine log.
Automatic caret updates use the lower edge only for XIM callback preedit. Explicit
`CFS_POINT` and `CFS_FORCE_POSITION` requests use that lower edge for callback candidate placement
only when the input thread, focused HWND, caret HWND and insertion point match the current caret.
Their text insertion point remains unchanged for position preedit. A missing or unrelated caret
leaves the requested point unchanged. This checks the Wine-to-XIM anchor, not whether every host
IME honors forced placement.
See the [COMPOSITIONFORM contract](https://learn.microsoft.com/en-us/windows/win32/api/imm/ns-imm-compositionform).

The fixture records `ClientToScreen` followed by
`LogicalToPhysicalPointForPerMonitorDPI` for both the anchor and root client
origin in the application's DPI context. The acceptance oracle adds their physical displacement
to the actual X client origin from `XTranslateCoordinates`. `XGetGeometry` must
independently match the root client size after conversion to the window's logical DPI.
The ratio uses `GetDpiForWindow` and the private monitor's `GetDpiForMonitor(MDT_RAW_DPI)`,
queried in a per-monitor-aware context. Positive native sizes use `MulDiv` rounding;
the resulting logical sizes must match exactly. This compares at the common logical
precision instead of reconstructing odd native sizes from rounded unaware coordinates.
Anchor conversion retains the application's DPI context.
Reports retain both this native `expected` and the original `win32_expected`,
plus native origins, sizes, DPI ratios and logical sizes, including when geometry equality fails.
This exposes differences between Wine's stored
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
not acceptance. The default cases only check the APIs above; cross-process hosted
input still needs separate coverage. The
existing automatic caret path and explicit candidate requests can still replace each other's anchors;
persistent IMC positioning policy is not covered or fixed
by these per-request tests.
The fixture refuses to run directly on host `DISPLAY=:0`.

`--candidate` adds `CFS_CANDIDATEPOS`, `CFS_EXCLUDE` and a window move retaining
the exclusion anchor. These check the requested point and the exclusion area's lower
edge in IBus requests; they do not verify candidate-panel placement when the host IME
flips its panel at a screen edge.

The IME followup also checks an explicit composition point after a matching caret,
a different point, a stale caret after focus moves to another input, and a destroyed
caret. Callback preedit places candidates below the matching caret; position preedit
keeps its text insertion point. An explicit candidate point remains unchanged even
when a caret exists at that point. The stale-input case requires the old caret to remain
owned by that HWND while focus is elsewhere before accepting the result.
`CFS_RECT` remains the existing layout-area path; the bridge still uses `rcArea` rather than
preserving its separate `ptCurrentPos`. These cases do not establish full rectangular
composition layout support. The updated cases require new isolated reports; earlier reports
whose oracle expected every explicit composition point at the top do not validate this change.
