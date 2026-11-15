#!/usr/bin/env python3
"""Check real XIM context lifecycle and IMM deactivation with ASan/UBSan."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
src = (args.source / 'dlls/winex11.drv/xim.c').read_text()
imm = (args.source / 'dlls/imm32/ime.c').read_text()
r = args.output
r.mkdir(parents=True, exist_ok=True)


def function(name, source=None):
    if source is None:
        source = src
    match = re.search(r'^(?:static )?(?:void|BOOL|int) (?:WINAPI )?' + name + r'\([^;]*?\n\{', source, re.M)
    assert match, name
    end, depth = match.end(), 1
    while depth:
        if source[end] == '{':
            depth += 1
        if source[end] == '}':
            depth -= 1
        end += 1
    return source[match.start():end] + '\n'


struct = re.search(r'struct xim_input_context\n\{.*?\n\};', src, re.S).group()
head = r'''

#include <X11/Xlib.h>
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef int32_t LONG;
typedef uintptr_t HWND;
typedef uint16_t WCHAR;
typedef uint32_t DWORD;
typedef unsigned UINT;
typedef int BOOL;
#define TRUE 1
#define FALSE 0
#define TRACE(...) ((void)0)
#define ERR(...) abort ()
#define max(a, b) ((a) > (b) ? (a) : (b))
#define InterlockedDecrement(p) __atomic_sub_fetch ((p), 1, __ATOMIC_SEQ_CST)
#define InterlockedIncrement(p) __atomic_add_fetch ((p), 1, __ATOMIC_SEQ_CST)
#define WM_WINE_IME_NOTIFY 1
#define IMN_WINE_SET_OPEN_STATUS 2
'''
body = r'''


struct x11drv_win_data
{
    HWND hwnd;
    XIC xic;
    struct xim_input_context *xic_context;
};
static struct x11drv_win_data windows[3];
static XIMStyle input_style = XIMPreeditCallbacks;
#define WINAPI
#define GA_ROOT 2
#define WM_WINE_IME_RESET 3
#define NtUserSendMessage 4
typedef uintptr_t HIMC;
typedef struct
{
    HWND hWnd;
} INPUTCONTEXT;
static INPUTCONTEXT imc;
static UINT end_message;
static unsigned cleared;
static HWND reenter_hwnd;
static INPUTCONTEXT *
ImmLockIMC (HIMC handle)
{
    return &imc;
}
static void
ImmUnlockIMC (HIMC handle)
{
}
static UINT
ime_set_composition_status (HIMC handle, BOOL active)
{
    return end_message;
}
static void
input_context_set_comp_str (INPUTCONTEXT *ctx, const WCHAR *text, UINT len)
{
    cleared++;
}
static void
ime_send_message (HIMC handle, UINT msg, UINT p, UINT value)
{
    if (reenter_hwnd)
        imc.hWnd = reenter_hwnd;
}
static HWND
GetAncestor (HWND hwnd, UINT mode)
{
    return hwnd;
}
void xim_reset (HWND hwnd);
static void
NtUserMessageCall (HWND hwnd, UINT msg, uintptr_t p, intptr_t value, void *data, UINT type, BOOL ansi)
{
    assert (msg == WM_WINE_IME_RESET);
    xim_reset (hwnd);
}
static unsigned updates, notifications, resets;
static XIC last_reset;
static int destroy_during_reset, destroy_callback;
static struct xim_input_context *explicit_destroy_context;
static size_t
test_wcslen (const WCHAR *s)
{
    size_t n = 0;
    while (s[n])
        n++;
    return n;
}
#define wcslen test_wcslen
static struct x11drv_win_data *
get_win_data (HWND hwnd)
{
    return hwnd > 0 && hwnd < 3 ? &windows[hwnd] : NULL;
}
static void
release_win_data (struct x11drv_win_data *w)
{
}
static void
activate_ime_hkl (HWND hwnd)
{
}
static void
NtUserPostMessage (HWND hwnd, UINT msg, UINT p, UINT value)
{
    notifications++;
}
static void
post_ime_update (HWND hwnd, UINT pos, WCHAR *comp, WCHAR *result)
{
    updates++;
}
struct thread_data
{
    Display *display;
};
static struct thread_data thread;
static struct thread_data *
x11drv_thread_data (void)
{
    return &thread;
}
static char *reset_ic (XIC xic);
static void destroy_ic (XIC xic);
static void set_focus (XIC xic);
static XIC
X11DRV_get_ic (HWND hwnd)
{
    return windows[hwnd].xic;
}
#define XSetICFocus set_focus
#define XmbResetIC reset_ic
#define XUnsetICFocus(xic) ((void)0)
#define XDestroyIC destroy_ic
#define XFree(p) free (p)
#define XFlush(d) ((void)0)
'''
source_functions = ['release_xim_context', 'xim_update_comp_string', 'xic_preedit_start',
                    'xic_preedit_done', 'xic_destroy', 'xim_reset', 'xim_destroy_ic', 'xim_set_focus']
functions = '\n'.join(function(name) for name in source_functions)
functions += '\n' + function('reset_native_ime', imm) + function('ImeSetActiveContext', imm)
tail = r'''

static int transfer_preedit, destroy_on_focus;
static void
set_focus (XIC xic)
{
    HWND hwnd = (uintptr_t)xic - 100;
    struct xim_input_context *ctx = windows[hwnd].xic_context;
    if (destroy_on_focus)
        {
            xic_destroy (xic, (XPointer)ctx, NULL);
            return;
        }
    if (transfer_preedit)
        {
            unsigned before_updates = updates, before_notifications = notifications;
            assert (ctx->resetting_focus);
            xic_preedit_start (xic, (XPointer)ctx, NULL);
            xic_preedit_done (xic, (XPointer)ctx, NULL);
            assert (!ctx->comp_str && before_updates == updates && before_notifications == notifications);
        }
}

static struct xim_input_context *
context (HWND hwnd)
{
    return windows[hwnd].xic_context;
}
static void
create (HWND hwnd)
{
    windows[hwnd].hwnd = hwnd;
    windows[hwnd].xic = (XIC)(uintptr_t)(hwnd + 100);
    struct xim_input_context *c = calloc (1, sizeof (*c));
    assert (c);
    c->hwnd = hwnd;
    c->refs = 1;
    windows[hwnd].xic_context = c;
}
static void
start (HWND hwnd)
{
    struct xim_input_context *c = context (hwnd);
    assert (c);
    xic_preedit_start (windows[hwnd].xic, (XPointer)c, NULL);
    WCHAR text[] = { 0x6d4b, 0x8bd5 };
    xim_update_comp_string (c, 0, 0, text, 2);
}
static char *
reset_ic (XIC xic)
{
    resets++;
    last_reset = xic;
    if (destroy_during_reset)
        {
            HWND h = (uintptr_t)xic - 100;
            xic_destroy (xic, (XPointer)context (h), NULL);
        }
    return NULL;
}
static void
destroy_ic (XIC xic)
{
    if (destroy_callback)
        {
            HWND h = (uintptr_t)xic - 100;
            // Explicit teardown detached the owner before entering Xlib.
            assert (!windows[h].xic_context);
            xic_destroy (xic, (XPointer)explicit_destroy_context, NULL);
        }
}
int
main (void)
{
    for (unsigned i = 0; i < 100; i++)
        {
            create (1);
            create (2);
            start (1);
            start (2);
            imc.hWnd = 1;
            end_message = 0;
            unsigned old_resets = resets;
            ImeSetActiveContext (1, TRUE);
            assert (resets == old_resets);
            ImeSetActiveContext (1, FALSE);
            assert (resets == old_resets + 1 && last_reset == windows[1].xic);
            xic_preedit_done (windows[1].xic, (XPointer)context (1), NULL);
            start (1);
            end_message = 5;
            reenter_hwnd = 2;
            imc.hWnd = 1;
            ImeSetActiveContext (1, FALSE);
            assert (last_reset == windows[1].xic && cleared == i + 1);
            assert (context (2)->comp_str && !context (2)->resetting);
            reenter_hwnd = 0;
            end_message = 0;
            xic_preedit_done (windows[1].xic, (XPointer)context (1), NULL);
            start (1);
            struct xim_input_context *a = context (1), *b = context (2);
            assert (a != b && a->comp_str != b->comp_str && wcslen (a->comp_str) == 2 && wcslen (b->comp_str) == 2);
            unsigned before = updates;
            xim_reset (1);
            assert (last_reset == windows[1].xic && a->resetting && !a->comp_str);
            assert (!b->resetting && wcslen (b->comp_str) == 2);
            xic_preedit_done (windows[1].xic, (XPointer)a, NULL);
            assert (!a->resetting && updates == before && wcslen (b->comp_str) == 2);
            xic_preedit_start (windows[1].xic, (XPointer)a, NULL);
            assert (a->comp_str && !*a->comp_str && wcslen (b->comp_str) == 2);
            destroy_callback = i % 2;
            explicit_destroy_context = a;
            xim_destroy_ic (&windows[1]);
            explicit_destroy_context = b;
            xim_destroy_ic (&windows[2]);
            create (1);
            start (1);
            destroy_during_reset = 1;
            xim_reset (1);
            assert (!windows[1].xic && !context (1));
            destroy_during_reset = 0;
            // Repeated empty resets must not suppress the next preedit phase.
            create (1);
            xim_reset (1);
            assert (!context (1)->resetting);
            explicit_destroy_context = context (1);
            xim_destroy_ic (&windows[1]);
        }
    create (1);
    transfer_preedit = 1;
    xim_set_focus (1, TRUE);
    assert (context (1)->resetting && !context (1)->comp_str);
    transfer_preedit = 0;
    start (1);
    unsigned before = resets;
    xim_set_focus (1, TRUE);
    assert (resets == before && wcslen (context (1)->comp_str) == 2);
    explicit_destroy_context = context (1);
    xim_destroy_ic (&windows[1]);
    create (1);
    input_style = XIMPreeditPosition;
    xim_set_focus (1, TRUE);
    assert (resets == before);
    explicit_destroy_context = context (1);
    xim_destroy_ic (&windows[1]);
    create (1);
    input_style = XIMPreeditCallbacks;
    destroy_on_focus = 1;
    xim_set_focus (1, TRUE);
    assert (!context (1));
    destroy_on_focus = 0;
    printf ("{\"passed\":true,\"rounds\":100,\"resets\":%u}\n", resets);
}
'''
fixture = r / 'xim-context-lifecycle.c'
fixture.write_text(head + struct + body + functions + tail)
subprocess.run(['cc', '-O1', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', str(fixture),
                '-o', str(r / 'xim-context-lifecycle')], check=True)
with (r / 'xim-context-lifecycle.log').open('w') as log:
    result = subprocess.run([str(r / 'xim-context-lifecycle')], stdout=log, stderr=log)
meta = {
    'passed': result.returncode == 0, 'exit_code': result.returncode, 'rounds': 100,
    'source_sha256': hashlib.sha256(src.encode()).hexdigest(), 'source_functions': source_functions,
    'source_extracted_without_changes': True, 'asan_ubsan': True, 'real_xim_server': False,
    'imm_source_sha256': hashlib.sha256(imm.encode()).hexdigest(),
    'deactivation_without_end_message': True, 'deactivation_reentrant_hwnd_change': True,
    'incoming_foreign_preedit_suppressed': True, 'own_preedit_retained': True,
    'position_style_unchanged': True, 'focus_reentry_on_xim_destroy': True,
    'scope': 'Per-XIC state isolation, delayed done, reset reentry during XIM destruction, '
             'explicit teardown, empty reset, and IMM deactivation with a reentrant HWND change.'
}
(r / 'xim-context-lifecycle-result.json').write_text(json.dumps(meta, indent=2) + '\n')
print(json.dumps(meta))
assert result.returncode == 0, (r / 'xim-context-lifecycle.log').read_text()
