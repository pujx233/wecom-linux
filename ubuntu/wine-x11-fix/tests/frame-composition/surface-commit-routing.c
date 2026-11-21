/* Check the extracted commit routing with real Win32 windows and process ownership. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef ULONG_PTR Window;
#define False 0
void *gdi_display;
static struct
{
    unsigned local, posted, synced, sequence, sync_order, post_order, completed;
    HWND local_target, post_target;
    WPARAM post_wp;
    BOOL post_result;
} calls;
static unsigned failures;
static struct x11drv_win_data
{
    BOOL frame_resize_pending, has_surface;
    unsigned first_present_depth;
} owner_data;

static struct x11drv_win_data *get_win_data(HWND hwnd)
{
    (void)hwnd;
    return &owner_data;
}

static void release_win_data(struct x11drv_win_data *data)
{
    (void)data;
}

static void set_frame_sync(struct x11drv_win_data *data, BOOL pending)
{
    (void)data;
    if (!pending) calls.completed++;
}

Window X11DRV_get_whole_window(HWND hwnd)
{
    return (Window)GetPropW(hwnd, L"__wine_x11_whole_window");
}

Window X11DRV_get_wm_window(HWND hwnd)
{
    Window window = (Window)GetPropW(hwnd, L"__wine_x11_wm_window");
    return window ? window : X11DRV_get_whole_window(hwnd);
}

void composite_owned_frame(HWND hwnd, BOOL configure)
{
    (void)configure;
    calls.local++;
    calls.local_target = hwnd;
}

int XSync(void *display, BOOL discard)
{
    (void)display;
    (void)discard;
    calls.synced++;
    calls.sync_order = ++calls.sequence;
    return 0;
}

BOOL record_post(HWND hwnd, UINT message, WPARAM wp, LPARAM lp)
{
    calls.posted++;
    calls.post_target = hwnd;
    calls.post_wp = wp;
    calls.post_order = ++calls.sequence;
    return (calls.post_result = PostMessageW(hwnd, message, wp, lp));
}

#define NtUserGetAncestor GetAncestor
#define NtUserGetWindowThread GetWindowThreadProcessId
#define NtUserPostMessage record_post
#include "surface-commit-source.h"

static void check(const char *name, BOOL passed)
{
    printf("{\"case\":\"%s\",\"passed\":%s,\"local\":%u,\"posted\":%u,\"synced\":%u,"
           "\"local_target\":%llu,\"post_target\":%llu,\"wp\":%llu}\n",
           name, passed ? "true" : "false", calls.local, calls.posted, calls.synced,
           (unsigned long long)(ULONG_PTR)calls.local_target,
           (unsigned long long)(ULONG_PTR)calls.post_target, (unsigned long long)calls.post_wp);
    fflush(stdout);
    failures += !passed;
    memset(&calls, 0, sizeof(calls));
    memset(&owner_data, 0, sizeof(owner_data));
}

static BOOL has_frame(HWND hwnd)
{
    Window frame = X11DRV_get_wm_window(hwnd);
    return frame && frame != X11DRV_get_whole_window(hwnd);
}

static BOOL forwarded(HWND root, BOOL framed)
{
    if (!framed) return !calls.posted && !calls.synced;
    return !calls.local && calls.posted == 1 && calls.post_target == root && calls.post_wp == 1 &&
           calls.post_result && calls.synced == 1 && calls.sync_order < calls.post_order;
}

static LRESULT CALLBACK procedure(HWND hwnd, UINT message, WPARAM wp, LPARAM lp)
{
    if (message == WM_NCCALCSIZE || message == WM_ERASEBKGND) return 0;
    if (message == WM_PAINT)
    {
        PAINTSTRUCT paint;
        HDC dc = BeginPaint(hwnd, &paint);
        FillRect(dc, &paint.rcPaint, GetStockObject(WHITE_BRUSH));
        EndPaint(hwnd, &paint);
        return 0;
    }
    return DefWindowProcA(hwnd, message, wp, lp);
}

static HWND create(const char *cls, DWORD style, HWND parent, int left)
{
    return CreateWindowExA(0, cls, "Commit routing fixture", style, left, 160, 320, 240,
                           parent, NULL, GetModuleHandleA(NULL), NULL);
}

static void pump(void)
{
    MSG message;
    while (PeekMessageA(&message, NULL, 0, 0, PM_REMOVE)) DispatchMessageA(&message);
}

int main(int argc, char **argv)
{
    WNDCLASSA cls = {.lpfnWndProc = procedure, .lpszClassName = "CommitRoutingRoot"};
    HWND root, second, child, nested, popup;
    BOOL framed;
    SetProcessDPIAware();
    if (!RegisterClassA(&cls)) return 2;
    if (argc == 5 && !strcmp(argv[1], "--child"))
    {
        root = (HWND)(ULONG_PTR)strtoull(argv[2], NULL, 16);
        second = (HWND)(ULONG_PTR)strtoull(argv[3], NULL, 16);
        framed = atoi(argv[4]);
        child = create(cls.lpszClassName, WS_CHILD | WS_VISIBLE, root, 10);
        nested = create(cls.lpszClassName, WS_CHILD | WS_VISIBLE, child, 10);
        if (!child || !nested) return 3;
        route_commit(nested);
        check("foreign-nested-child", forwarded(root, framed));
        route_commit(root);
        check("foreign-direct-root", forwarded(root, framed));
        SetParent(child, second);
        route_commit(nested);
        check("foreign-child-reparented", forwarded(second, framed));
        popup = create(cls.lpszClassName, WS_POPUP, root, 10);
        route_commit(popup);
        check("foreign-owned-popup-independent", calls.local == 1 && calls.local_target == popup && !calls.posted);
        DestroyWindow(popup);
        DestroyWindow(child);
        return failures ? 1 : 0;
    }
    if (argc != 2) return 2;
    framed = atoi(argv[1]);
    root = create(cls.lpszClassName, WS_POPUP | WS_THICKFRAME | WS_CLIPCHILDREN, NULL, 150);
    second = create(cls.lpszClassName, WS_POPUP | WS_THICKFRAME | WS_CLIPCHILDREN, NULL, 750);
    ShowWindow(root, SW_SHOW);
    ShowWindow(second, SW_SHOW);
    cls.lpszClassName = "CommitRoutingDecoration";
    RegisterClassA(&cls);
    HWND decoration = CreateWindowExA(WS_EX_LAYERED | WS_EX_TOOLWINDOW, cls.lpszClassName, "",
                                      WS_POPUP, 150, 160, 320, 20, root, NULL, cls.hInstance, NULL);
    SetLayeredWindowAttributes(decoration, 0, 255, LWA_ALPHA);
    ShowWindow(decoration, SW_SHOWNOACTIVATE);
    DWORD started = GetTickCount();
    do { pump(); Sleep(1); } while (GetTickCount() - started < 400);
    if (has_frame(root) != framed || has_frame(second) != framed) return 4;
    child = create("CommitRoutingRoot", WS_CHILD | WS_VISIBLE, root, 10);
    nested = create("CommitRoutingRoot", WS_CHILD | WS_VISIBLE, child, 10);
    route_commit(root);
    check("local-root", calls.local == 1 && calls.local_target == root && !calls.posted);
    route_commit(nested);
    check("local-nested-child", calls.local == 1 && (!framed || calls.local_target == root) && !calls.posted);
    popup = create("CommitRoutingRoot", WS_POPUP, root, 10);
    route_commit(popup);
    check("local-owned-popup-independent", calls.local == 1 && calls.local_target == popup && !calls.posted);
    if (framed)
    {
        LRESULT result = route_owner_notification(root, 1);
        check("owner-dirty-notification", !result && calls.local == 1 && calls.local_target == root);
        owner_data.frame_resize_pending = TRUE;
        result = route_owner_notification(root, 1);
        check("owner-native-completed", !result && calls.local == 1 && calls.completed == 1);
        owner_data.frame_resize_pending = TRUE;
        owner_data.first_present_depth = 1;
        result = route_owner_notification(root, 1);
        check("owner-paint-in-progress", !result && calls.local == 1 && !calls.completed);
        owner_data.frame_resize_pending = owner_data.has_surface = TRUE;
        result = route_owner_notification(root, 1);
        check("owner-memory-surface", !result && calls.local == 1 && !calls.completed);
        result = route_owner_notification(root, 0);
        check("internal-dispatch-preserved", result == -1 && !calls.local && !calls.posted);
    }
    char self[MAX_PATH], command[2 * MAX_PATH];
    STARTUPINFOA startup = {.cb = sizeof(startup)};
    PROCESS_INFORMATION peer;
    GetModuleFileNameA(NULL, self, sizeof(self));
    snprintf(command, sizeof(command), "\"%s\" --child %llx %llx %d", self,
             (unsigned long long)(ULONG_PTR)root, (unsigned long long)(ULONG_PTR)second, framed);
    if (!CreateProcessA(self, command, NULL, NULL, TRUE, 0, NULL, NULL, &startup, &peer)) return 5;
    CloseHandle(peer.hThread);
    started = GetTickCount();
    while (WaitForSingleObject(peer.hProcess, 0) == WAIT_TIMEOUT && GetTickCount() - started < 10000)
    {
        pump();
        Sleep(1);
    }
    DWORD exit_code;
    GetExitCodeProcess(peer.hProcess, &exit_code);
    CloseHandle(peer.hProcess);
    if (exit_code == STILL_ACTIVE) return 6;
    DestroyWindow(popup);
    DestroyWindow(root);
    DestroyWindow(second);
    return failures || exit_code ? 1 : 0;
}
