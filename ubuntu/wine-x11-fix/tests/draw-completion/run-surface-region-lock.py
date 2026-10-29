#!/usr/bin/env python3
"""Check the production region helper's lock and lifetime contract with API substitutes.

This does not reproduce a real X11 deadlock. The caller must also release its outer
USER lock before invoking the helper; that boundary is reviewed separately.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('source', type=Path, help='Wine dlls/win32u/window.c to inspect')
parser.add_argument('output', type=Path, help='JSON result file')
args = parser.parse_args()
source = args.source.read_text()
start = source.index('static void update_surface_region( HWND hwnd )')
body = source.index('{', start)
depth = 1
end = body + 1
while depth:
    depth += (source[end] == '{') - (source[end] == '}')
    end += 1
function = source[start:end]

harness = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef int HWND, HRGN;
typedef unsigned int DWORD;
typedef struct { int left, top, right, bottom; } RECT;
struct window_surface { int ref; } storage;
typedef struct { struct window_surface *surface; DWORD dwExStyle; } WND;
static WND wnd;
#define WND_DESKTOP ((WND *)1)
#define WND_OTHER_PROCESS ((WND *)2)
#define FALSE 0
#define TRUE 1
#define WS_EX_LAYOUTRTL 0x400000
#define RGN_AND 1
static int user_depth, lock_errors, ref_errors, regions, shape_calls, clip_calls, mirror_calls;
static int invalid, fail_query, shape_present, clip_present, detach, did_detach, queries;
static HRGN last_shape, last_clip;
static int next_region;
static int live[64];
static WND *get_win_ptr(HWND hwnd)
{
    (void)hwnd;
    if (invalid == 1) return NULL;
    if (invalid == 2) return WND_DESKTOP;
    if (invalid == 3) return WND_OTHER_PROCESS;
    user_depth++;
    return &wnd;
}
static void release_win_ptr(WND *win) { (void)win; user_depth--; }
static inline void window_surface_add_ref(struct window_surface *surface) { surface->ref++; }
static void window_surface_release(struct window_surface *surface)
{
    if (--surface->ref < 0) ref_errors++;
}
static HRGN new_region(void)
{
    regions++;
    live[++next_region] = 1;
    return next_region;
}
static int get_window_region(HWND hwnd, int surface, HRGN *region, RECT *visible)
{
    (void)hwnd;
    *region = 0;
    queries++;
    if (detach && queries == 1 && !user_depth)
    {
        /* A window can lose its reference while the helper still uses the surface. */
        window_surface_release(wnd.surface);
        wnd.surface = NULL;
        wnd.dwExStyle = 0;
        did_detach = 1;
    }
    if (fail_query == queries) return 1;
    if (surface ? clip_present : shape_present) *region = new_region();
    *visible = (RECT){10, 20, 110, 220};
    return 0;
}
static HRGN NtGdiCreateRectRgn(int left, int top, int right, int bottom)
{
    if (left || top || right != 100 || bottom != 200) ref_errors++;
    return new_region();
}
static int NtGdiCombineRgn(HRGN dst, HRGN a, HRGN b, int mode)
{
    if (!live[dst] || !live[a] || !live[b] || mode != RGN_AND) ref_errors++;
    return 1;
}
static void NtUserMirrorRgn(HWND hwnd, HRGN shape)
{
    (void)hwnd;
    if (!live[shape]) ref_errors++;
    mirror_calls++;
}
static void NtGdiDeleteObjectApp(HRGN region)
{
    if (!live[region]) ref_errors++;
    else { live[region] = 0; regions--; }
}
static void NtGdiOffsetRgn(HRGN region, int x, int y)
{
    if (!live[region] || x != -10 || y != -20) ref_errors++;
}
static void window_surface_set_shape(struct window_surface *surface, HRGN region)
{
    if (user_depth) lock_errors++;
    if (!surface || surface->ref <= 0) ref_errors++;
    if (region && !live[region]) ref_errors++;
    last_shape = region;
    shape_calls++;
}
static void window_surface_set_clip(struct window_surface *surface, HRGN region)
{
    if (user_depth) lock_errors++;
    if (!surface || surface->ref <= 0) ref_errors++;
    if (region && !live[region]) ref_errors++;
    last_clip = region;
    clip_calls++;
}
'''
main = r'''
int main(void)
{
    int i, failed = 0;
    struct testcase
    {
        const char *name;
        int invalid, missing, fail, shape, clip, rtl, detach, expected_shape, expected_clip;
    } cases[] = {
        {"invalid", 1, 0, 0, 0, 0, 0, 0, 0, 0},
        {"desktop", 2, 0, 0, 0, 0, 0, 0, 0, 0},
        {"foreign", 3, 0, 0, 0, 0, 0, 0, 0, 0},
        {"no-surface", 0, 1, 0, 0, 0, 0, 0, 0, 0},
        {"shape-error", 0, 0, 1, 0, 0, 0, 0, 0, 0},
        {"clip-error", 0, 0, 2, 1, 0, 0, 0, 1, 0},
        {"unbounded", 0, 0, 0, 0, 0, 0, 0, 1, 1},
        {"shape-only", 0, 0, 0, 1, 0, 0, 0, 1, 1},
        {"clip-only", 0, 0, 0, 0, 1, 0, 0, 1, 1},
        {"shape-and-clip", 0, 0, 0, 1, 1, 0, 0, 1, 1},
        {"rtl", 0, 0, 0, 1, 1, 1, 0, 1, 1},
        {"surface-detached", 0, 0, 0, 1, 1, 1, 1, 1, 1},
        {"detached-error", 0, 0, 1, 0, 0, 0, 1, 0, 0},
    };
    printf("{\"cases\":[");
    for (i = 0; i < (int)(sizeof(cases) / sizeof(cases[0])); i++)
    {
        struct testcase *c = &cases[i];
        int ok;
        user_depth = lock_errors = ref_errors = regions = shape_calls = clip_calls = mirror_calls = 0;
        queries = last_shape = last_clip = next_region = did_detach = 0;
        memset(live, 0, sizeof(live));
        invalid = c->invalid; fail_query = c->fail; shape_present = c->shape;
        clip_present = c->clip; detach = c->detach;
        storage.ref = c->missing ? 0 : 1;
        wnd.surface = c->missing ? NULL : &storage;
        wnd.dwExStyle = c->rtl ? WS_EX_LAYOUTRTL : 0;
        update_surface_region(42);
        ok = !user_depth && !lock_errors && !ref_errors && !regions &&
             storage.ref == (c->missing || did_detach ? 0 : 1) &&
             shape_calls == c->expected_shape && clip_calls == c->expected_clip &&
             mirror_calls == (c->rtl && c->shape && c->fail != 1);
        if (c->expected_clip && !c->clip) ok &= last_clip == last_shape;
        failed += !ok;
        printf("%s{\"name\":\"%s\",\"passed\":%s,\"lock_errors\":%d,\"ref_errors\":%d,\"detached\":%s}",
               i ? "," : "", c->name, ok ? "true" : "false", lock_errors, ref_errors,
               did_detach ? "true" : "false");
    }
    printf("],\"passed\":%s}\n", failed ? "false" : "true");
    return !!failed;
}
'''
with tempfile.TemporaryDirectory(prefix='surface-region-lock-') as directory:
    path = Path(directory)
    test = path / 'test.c'
    test.write_text(harness + function + main)
    exe = path / 'test'
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', str(test), '-o', str(exe)], check=True)
    result = subprocess.run([str(exe)], capture_output=True, text=True)
report = json.loads(result.stdout)
report.update(source=str(args.source.resolve()), source_sha256=hashlib.sha256(source.encode()).hexdigest(),
              helper_sha256=hashlib.sha256(function.encode()).hexdigest(), exit_code=result.returncode,
              scope='production helper with API substitutes; not a runtime deadlock reproduction')
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
raise SystemExit(result.returncode)
