#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef MARGIN
#define MARGIN 24
#endif
#ifndef BODY_WIDTH
#define BODY_WIDTH 640
#endif
#ifndef BODY_HEIGHT
#define BODY_HEIGHT 480
#endif
#ifndef BODY_X
#define BODY_X 200
#endif
#ifndef BODY_Y
#define BODY_Y 140
#endif

static HWND owner, shadow, extra, control;
static HDC memory;
static HBITMAP bitmap;
static HANDLE command_done;
static HANDLE shadow_thread, shadow_ready, shadow_frozen, shadow_resume;
static DWORD shadow_thread_id;
static BOOL suppress_shadow_updates;
static unsigned move_delay;
static unsigned clicks, body_clicks;
static unsigned extra_activations, hide_extra_before, hide_extra_after;
static DWORD owner_error;
static HWND previous_owner;
static HWND active_at_call, hide_before, hide_after, hide_next, hide_foreground;
static HWND stack_before, stack_after;
static LONGLONG stack_microseconds;
static char command[128] = "ready";

static void position_shadow(void)
{
    RECT rect;
    POINT source = {0, 0}, position;
    SIZE size = {BODY_WIDTH + 2 * MARGIN, BODY_HEIGHT + 2 * MARGIN};
    BLENDFUNCTION blend = {AC_SRC_OVER, 0, 255, AC_SRC_ALPHA};

    if (!shadow || !GetWindowRect(owner, &rect)) return;
    position.x = rect.left - MARGIN;
    position.y = rect.top - MARGIN;
    UpdateLayeredWindow(shadow, NULL, &position, &size, memory, &source, 0, &blend, ULW_ALPHA);
}

static LRESULT CALLBACK owner_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam)
{
    if (window == owner && message == WM_WINDOWPOSCHANGING && move_delay && IsWindowVisible(window) &&
        !(((WINDOWPOS *)lparam)->flags & SWP_NOMOVE)) Sleep(move_delay);
    if (message == WM_NCCALCSIZE) return 0;
    if (message == WM_NCHITTEST)
    {
        RECT rect;
        GetWindowRect(window, &rect);
        return (short)HIWORD(lparam) - rect.top < 32 ? HTCAPTION : HTCLIENT;
    }
    if (message == WM_LBUTTONDOWN) body_clicks++;
    if (window == owner && message == WM_WINDOWPOSCHANGED && !IsIconic(window) && !suppress_shadow_updates)
        position_shadow();
    if (message == WM_PAINT)
    {
        PAINTSTRUCT paint;
        RECT rect;
        HDC dc = BeginPaint(window, &paint);
        GetClientRect(window, &rect);
        FillRect(dc, &rect, (HBRUSH)(COLOR_WINDOW + 1));
        EndPaint(window, &paint);
        return 0;
    }
    return DefWindowProcA(window, message, wparam, lparam);
}

static LRESULT CALLBACK shadow_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam)
{
    if (message == WM_APP + 2)
    {
        SetEvent(shadow_frozen);
        WaitForSingleObject(shadow_resume, 8000);
        return 0;
    }
    if (window == extra && message == WM_ACTIVATE && LOWORD(wparam) != WA_INACTIVE) extra_activations++;
    if (message == WM_LBUTTONDOWN) clicks++;
    if (message == WM_NCHITTEST) return HTCLIENT;
    return DefWindowProcA(window, message, wparam, lparam);
}

static void create_shadow(void)
{
    shadow = CreateWindowExA(WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_WINDOWEDGE,
                             "PlacementShadow", "Owned layered border",
                             WS_POPUP | WS_BORDER | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX |
                             WS_CLIPCHILDREN | WS_CLIPSIBLINGS, BODY_X - MARGIN, BODY_Y - MARGIN,
                             BODY_WIDTH + 2 * MARGIN, BODY_HEIGHT + 2 * MARGIN,
                             owner, NULL, GetModuleHandleA(NULL), NULL);
    if (getenv("QA_SHADOW_SHOW_BEFORE_ARGB")) ShowWindow(shadow, SW_SHOWNOACTIVATE);
    position_shadow();
}

static DWORD WINAPI run_shadow(void *unused)
{
    MSG message;
    (void)unused;
    create_shadow();
    ShowWindow(shadow, SW_SHOWNOACTIVATE);
    SetEvent(shadow_ready);
    while (GetMessageA(&message, NULL, 0, 0) > 0)
    {
        TranslateMessage(&message);
        DispatchMessageA(&message);
    }
    if (IsWindow(shadow)) DestroyWindow(shadow);
    return 0;
}

static void describe(const char *name, HWND window)
{
    RECT rect = {0};
    GetWindowRect(window, &rect);
    printf("\"%s\":{\"hwnd\":\"%p\",\"xid\":%llu,\"wm_xid\":%llu,\"rect\":[%ld,%ld,%ld,%ld],"
           "\"owner\":\"%p\",\"style\":\"%08lx\",\"ex_style\":\"%08lx\","
           "\"visible\":%d,\"iconic\":%d}", name, window,
           (unsigned long long)(UINT_PTR)GetPropA(window, "__wine_x11_whole_window"),
           (unsigned long long)(UINT_PTR)GetPropA(window, "__wine_x11_wm_window"),
           rect.left, rect.top, rect.right, rect.bottom, GetWindow(window, GW_OWNER), GetWindowLongA(window, GWL_STYLE),
           GetWindowLongA(window, GWL_EXSTYLE), !!IsWindowVisible(window), !!IsIconic(window));
}

static void report(void)
{
    POINT pointer;
    MONITORINFO monitor = {.cbSize = sizeof(monitor)};
    GetCursorPos(&pointer);
    GetMonitorInfoA(MonitorFromWindow(owner, MONITOR_DEFAULTTONEAREST), &monitor);
    printf("{\"pointer\":[%ld,%ld],\"button\":%d,", pointer.x, pointer.y,
           !!(GetAsyncKeyState(VK_LBUTTON) & 0x8000));
    printf("\"workarea\":[%ld,%ld,%ld,%ld],", monitor.rcWork.left, monitor.rcWork.top,
           monitor.rcWork.right, monitor.rcWork.bottom);
    printf("\"stage\":\"%s\",\"clicks\":%u,\"body_clicks\":%u,\"foreground\":\"%p\","
           "\"active\":\"%p\",", command, clicks, body_clicks, GetForegroundWindow(), GetActiveWindow());
    printf("\"active_at_call\":\"%p\",\"hide_before\":\"%p\",\"hide_after\":\"%p\",",
           active_at_call, hide_before, hide_after);
    printf("\"owner_error\":%lu,\"previous_owner\":\"%p\",", owner_error, previous_owner);
    printf("\"hide_next\":\"%p\",\"hide_foreground\":\"%p\",", hide_next, hide_foreground);
    printf("\"hide_extra_before\":%u,\"hide_extra_after\":%u,", hide_extra_before, hide_extra_after);
    printf("\"stack_before\":\"%p\",\"stack_after\":\"%p\",\"stack_microseconds\":%lld,",
           stack_before, stack_after, stack_microseconds);
    describe("owner", owner);
    putchar(',');
    describe("shadow", shadow);
    putchar(',');
    describe("extra", extra);
    puts("}");
}

static DWORD WINAPI read_commands(void *unused)
{
    (void)unused;
    while (fgets(command, sizeof(command), stdin))
    {
        command[strcspn(command, "\r\n")] = 0;
        PostMessageA(control, WM_APP, 0, 0);
        WaitForSingleObject(command_done, INFINITE);
    }
    PostMessageA(control, WM_CLOSE, 0, 0);
    return 0;
}

static void execute(void)
{
    DWORD flags = SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE;
    DWORD ex = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE;
    DWORD style = WS_POPUP | WS_SYSMENU | WS_THICKFRAME;
    HWND parent = owner;

    if (!strcmp(command, "bottom"))
    {
        MONITORINFO info = {.cbSize = sizeof(info)};
        GetMonitorInfoA(MonitorFromWindow(owner, MONITOR_DEFAULTTONEAREST), &info);
        SetWindowPos(owner, NULL, info.rcWork.left + 200, info.rcWork.bottom - BODY_HEIGHT, 0, 0, flags);
    }
    else if (!strcmp(command, "top")) SetWindowPos(owner, NULL, 200, 140, 0, 0, flags);
    else if (!strcmp(command, "minimize")) ShowWindow(owner, SW_MINIMIZE);
    else if (!strcmp(command, "restore")) ShowWindow(owner, SW_RESTORE);
    else if (!strcmp(command, "maximize")) ShowWindow(owner, SW_MAXIMIZE);
    else if (!strcmp(command, "detach-shadow") || !strcmp(command, "reattach-shadow"))
    {
        SetLastError(0);
        previous_owner = (HWND)SetWindowLongPtrA(shadow, GWLP_HWNDPARENT,
                                               !strcmp(command, "detach-shadow") ? 0 : (LONG_PTR)owner);
        owner_error = GetLastError();
        SetWindowPos(shadow, NULL, 0, 0, 0, 0, flags | SWP_NOMOVE | SWP_FRAMECHANGED);
    }
    else if (!strcmp(command, "close-shadow"))
    {
        DestroyWindow(shadow);
        shadow = NULL;
    }
    else if (!strcmp(command, "create-shadow"))
    {
        create_shadow();
        ShowWindow(shadow, SW_SHOWNOACTIVATE);
    }
    else if (!strcmp(command, "freeze-shadow"))
    {
        suppress_shadow_updates = TRUE;
        PostMessageA(shadow, WM_APP + 2, 0, 0);
        if (WaitForSingleObject(shadow_frozen, 5000) != WAIT_OBJECT_0) ExitProcess(4);
    }
    else if (!strcmp(command, "wake-shadow")) SetEvent(shadow_resume);
    else if (!strcmp(command, "detach-bare")) SetWindowLongPtrA(shadow, GWLP_HWNDPARENT, 0);
    else if (!strcmp(command, "dock-owner"))
    {
        extra = CreateWindowExA(0, "PlacementHost", "Owned placement host", WS_OVERLAPPEDWINDOW,
                                1000, 300, 900, 700, NULL, NULL, GetModuleHandleA(NULL), NULL);
        ShowWindow(extra, SW_SHOW);
        SetWindowLongPtrA(owner, GWL_STYLE, GetWindowLongPtrA(owner, GWL_STYLE) | WS_CHILD);
        SetParent(owner, extra);
        SetWindowPos(owner, NULL, 20, 20, BODY_WIDTH, BODY_HEIGHT,
                     SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED);
    }
    else if (!strcmp(command, "undock-owner"))
    {
        SetParent(owner, NULL);
        SetWindowLongPtrA(owner, GWL_STYLE, GetWindowLongPtrA(owner, GWL_STYLE) & ~WS_CHILD);
        SetWindowPos(owner, NULL, 200, 140, BODY_WIDTH, BODY_HEIGHT,
                     SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED);
        ShowWindow(owner, SW_SHOW);
        DestroyWindow(extra);
        extra = NULL;
    }
    else if (!strcmp(command, "owner-argb"))
    {
        RECT rect;
        POINT source = {0, 0}, position;
        SIZE size = {BODY_WIDTH, BODY_HEIGHT};
        BLENDFUNCTION blend = {AC_SRC_OVER, 0, 255, AC_SRC_ALPHA};
        GetWindowRect(owner, &rect);
        position.x = rect.left;
        position.y = rect.top;
        SetWindowLongPtrA(owner, GWL_EXSTYLE, GetWindowLongPtrA(owner, GWL_EXSTYLE) | WS_EX_LAYERED);
        UpdateLayeredWindow(owner, NULL, &position, &size, memory, &source, 0, &blend, ULW_ALPHA);
    }
    else if (!strcmp(command, "owner-plain"))
    {
        SetWindowLongPtrA(owner, GWL_EXSTYLE, GetWindowLongPtrA(owner, GWL_EXSTYLE) & ~WS_EX_LAYERED);
        SetWindowPos(owner, NULL, 0, 0, 0, 0, flags | SWP_NOMOVE | SWP_FRAMECHANGED);
        RedrawWindow(owner, NULL, NULL, RDW_INVALIDATE | RDW_UPDATENOW | RDW_FRAME | RDW_ALLCHILDREN);
    }
    else if (!strcmp(command, "hide"))
    {
        SetWindowLongPtrA(extra, GWLP_HWNDPARENT, 0);
        SetForegroundWindow(owner);
        SetActiveWindow(owner);
        SetWindowPos(extra, owner, 0, 0, 0, 0, flags & ~SWP_NOZORDER);
        hide_next = GetWindow(owner, GW_HWNDNEXT);
        hide_foreground = GetForegroundWindow();
        hide_before = GetActiveWindow();
        hide_extra_before = extra_activations;
        ShowWindow(owner, SW_HIDE);
        hide_after = GetActiveWindow();
        hide_extra_after = extra_activations;
    }
    else if (!strcmp(command, "show")) ShowWindow(owner, SW_SHOWNOACTIVATE);
    else if (!strcmp(command, "minimize-shadow")) ShowWindow(shadow, SW_SHOWMINNOACTIVE);
    else if (!strcmp(command, "restore-shadow")) ShowWindow(shadow, SW_SHOWNOACTIVATE);
    else if (!strcmp(command, "focus")) SetForegroundWindow(owner);
    else if (!strcmp(command, "raise-body"))
        SetWindowPos(owner, HWND_TOP, 0, 0, 0, 0, flags | SWP_NOMOVE | SWP_NOOWNERZORDER);
    else if (!strcmp(command, "frameless-shadow"))
    {
        SetWindowLongPtrA(shadow, GWL_STYLE, GetWindowLongPtrA(shadow, GWL_STYLE) & ~WS_THICKFRAME);
        SetWindowPos(shadow, NULL, 0, 0, 0, 0, flags | SWP_NOMOVE | SWP_FRAMECHANGED);
    }
    else if (!strcmp(command, "fixed"))
    {
        SetWindowLongPtrA(owner, GWL_STYLE, GetWindowLongPtrA(owner, GWL_STYLE) & ~WS_THICKFRAME);
        SetWindowPos(owner, NULL, 0, 0, 0, 0,
                     SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED);
    }
    else if (!strcmp(command, "destroy")) DestroyWindow(owner);
    else if (!strcmp(command, "transparent"))
    {
        SetWindowLongPtrA(shadow, GWL_EXSTYLE, GetWindowLongPtrA(shadow, GWL_EXSTYLE) | WS_EX_TRANSPARENT);
        SetWindowPos(shadow, NULL, 0, 0, 0, 0,
                     SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE);
    }
    else if (!strcmp(command, "interactive"))
        SetWindowLongPtrA(shadow, GWL_EXSTYLE, GetWindowLongPtrA(shadow, GWL_EXSTYLE) & ~WS_EX_TRANSPARENT);
    else if (!strcmp(command, "sample")) return;
    else if (!strcmp(command, "solid-layer"))
    {
        DIBSECTION section;
        GetObjectA(bitmap, sizeof(section), &section);
        DWORD *pixels = section.dsBm.bmBits;
        for (int i = 0; i < section.dsBm.bmWidth * section.dsBm.bmHeight; i++) pixels[i] = 0xc80064c8;
        position_shadow();
    }
    else if (!strcmp(command, "stack-prepare"))
        SetWindowPos(shadow, extra, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
    else if (!strcmp(command, "stack-real"))
        SetWindowPos(extra, shadow, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
    else if (!strcmp(command, "stack-noop"))
    {
        LARGE_INTEGER before, after, frequency;
        stack_before = GetWindow(shadow, GW_HWNDPREV);
        QueryPerformanceFrequency(&frequency);
        QueryPerformanceCounter(&before);
        for (unsigned i = 0; i < 256; i++)
            SetWindowPos(shadow, owner, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER | SWP_NOSENDCHANGING);
        QueryPerformanceCounter(&after);
        stack_microseconds = (after.QuadPart - before.QuadPart) * 1000000 / frequency.QuadPart;
        stack_after = GetWindow(shadow, GW_HWNDPREV);
    }
    else
    {
        if (extra) DestroyWindow(extra);
        if (!strcmp(command, "palette")) ex &= ~WS_EX_LAYERED;
        else if (!strcmp(command, "caption")) style |= WS_CAPTION;
        else if (!strcmp(command, "unowned")) parent = NULL;
        else if (!strcmp(command, "appwindow")) ex |= WS_EX_APPWINDOW;
        else if (strcmp(command, "active")) return;
        extra = CreateWindowExA(ex, "PlacementExtra", command, style,
                               900, 180, 220, 160, parent, NULL, GetModuleHandleA(NULL), NULL);
        if (ex & WS_EX_LAYERED) SetLayeredWindowAttributes(extra, 0, 255, LWA_ALPHA);
        ShowWindow(extra, !strcmp(command, "active") ? SW_SHOW : SW_SHOWNOACTIVATE);
        if (!strcmp(command, "active"))
        {
            SetActiveWindow(extra);
            active_at_call = GetActiveWindow();
        }
    }
}

static LRESULT CALLBACK control_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam)
{
    if (message == WM_APP)
    {
        execute();
        SetTimer(window, 1, 250, NULL);
        return 0;
    }
    if (message == WM_TIMER)
    {
        KillTimer(window, 1);
        report();
        if (!strcmp(command, "ready")) CloseHandle(CreateThread(NULL, 0, read_commands, NULL, 0, NULL));
        else SetEvent(command_done);
        return 0;
    }
    if (message == WM_CLOSE)
    {
        move_delay = 0;
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcA(window, message, wparam, lparam);
}

int main(void)
{
    const int width = BODY_WIDTH + 2 * MARGIN, height = BODY_HEIGHT + 2 * MARGIN;
    BITMAPINFO info = {.bmiHeader = {.biSize = sizeof(BITMAPINFOHEADER), .biWidth = width,
                                   .biHeight = -height, .biPlanes = 1, .biBitCount = 32}};
    WNDCLASSA cls = {.lpfnWndProc = owner_proc, .hInstance = GetModuleHandleA(NULL),
                    .hCursor = LoadCursorA(NULL, IDC_ARROW), .lpszClassName = "PlacementOwner"};
    DWORD *pixels;
    MSG message;

    setvbuf(stdout, NULL, _IONBF, 0);
    if (getenv("QA_OWNER_MOVE_DELAY_MS")) move_delay = atoi(getenv("QA_OWNER_MOVE_DELAY_MS"));
    SetProcessDPIAware();
    RegisterClassA(&cls);
    cls.lpszClassName = "PlacementHost";
    RegisterClassA(&cls);
    cls.lpfnWndProc = shadow_proc;
    cls.lpszClassName = "PlacementShadow";
    RegisterClassA(&cls);
    cls.lpfnWndProc = shadow_proc;
    cls.lpszClassName = "PlacementExtra";
    RegisterClassA(&cls);
    cls.lpfnWndProc = control_proc;
    cls.lpszClassName = "PlacementControl";
    RegisterClassA(&cls);
    control = CreateWindowExA(0, cls.lpszClassName, NULL, 0, 0, 0, 0, 0,
                              HWND_MESSAGE, NULL, cls.hInstance, NULL);
    memory = CreateCompatibleDC(NULL);
    bitmap = CreateDIBSection(memory, &info, DIB_RGB_COLORS, (void **)&pixels, NULL, 0);
    if (!memory || !bitmap) return 1;
    SelectObject(memory, bitmap);
    for (int y = 0; y < height; y++)
        for (int x = 0; x < width; x++)
            pixels[y * width + x] = x < MARGIN || y < MARGIN || x >= width - MARGIN || y >= height - MARGIN ?
                                    0xc80064c8 : 0;
    owner = CreateWindowExA(WS_EX_WINDOWEDGE, "PlacementOwner", "Owned layered placement",
                            WS_SYSMENU | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX |
                            WS_CLIPCHILDREN | WS_CLIPSIBLINGS, BODY_X, BODY_Y, BODY_WIDTH, BODY_HEIGHT,
                            NULL, NULL, cls.hInstance, NULL);
    SetWindowLongPtrA(owner, GWL_STYLE, GetWindowLongPtrA(owner, GWL_STYLE) & ~WS_CAPTION);
    SetWindowPos(owner, NULL, 0, 0, 0, 0,
                 SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE);
    if (getenv("QA_SHADOW_THREAD"))
    {
        shadow_ready = CreateEventA(NULL, FALSE, FALSE, NULL);
        shadow_frozen = CreateEventA(NULL, FALSE, FALSE, NULL);
        shadow_resume = CreateEventA(NULL, TRUE, FALSE, NULL);
        shadow_thread = CreateThread(NULL, 0, run_shadow, NULL, 0, &shadow_thread_id);
        if (WaitForSingleObject(shadow_ready, 5000) != WAIT_OBJECT_0) return 4;
    }
    else create_shadow();
    if (!owner || !shadow) return 1;
    position_shadow();
    if (getenv("WECOM_QA_PREMAP_HINT"))
    {
        strcpy(command, "premap");
        report();
        if (!fgets(command, sizeof(command), stdin)) return 1;
        strcpy(command, "ready");
    }
    ShowWindow(owner, SW_SHOW);
    ShowWindow(shadow, SW_SHOWNOACTIVATE);
    command_done = CreateEventA(NULL, FALSE, FALSE, NULL);
    SetTimer(control, 1, 500, NULL);
    while (GetMessageA(&message, NULL, 0, 0) > 0)
    {
        TranslateMessage(&message);
        DispatchMessageA(&message);
    }
    if (IsWindow(owner)) DestroyWindow(owner);
    if (shadow_thread)
    {
        SetEvent(shadow_resume);
        PostThreadMessageA(shadow_thread_id, WM_QUIT, 0, 0);
        WaitForSingleObject(shadow_thread, 5000);
        CloseHandle(shadow_thread);
        CloseHandle(shadow_ready);
        CloseHandle(shadow_frozen);
        CloseHandle(shadow_resume);
    }
    DeleteDC(memory);
    DeleteObject(bitmap);
    CloseHandle(command_done);
    return 0;
}
