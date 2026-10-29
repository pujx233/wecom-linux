#define _WIN32_WINNT 0x0a00
#define WIN32_LEAN_AND_MEAN
#define WM_WINE_UPDATEWINDOWSTATE 0x8000000b /* Pinned Wine internal message. */
#include <windows.h>
#include <stdio.h>
#include <string.h>

static HWND main_window, shadow, helper;
static unsigned display_changes, position_changes;
static HANDLE resume_event;

static void json_string(const char *value)
{
    putchar('"');
    for (; *value; ++value)
    {
        if (*value == '\\' || *value == '"') putchar('\\');
        putchar(*value);
    }
    putchar('"');
}

static BOOL CALLBACK monitor_state(HMONITOR handle, HDC dc, RECT *rect, LPARAM argument)
{
    MONITORINFOEXA info = {.cbSize = sizeof(info)};
    unsigned *count = (unsigned *)argument;
    (void)dc;
    (void)rect;
    GetMonitorInfoA(handle, (MONITORINFO *)&info);
    printf("%s{\"handle\":%llu,\"device\":", (*count)++ ? "," : "", (unsigned long long)(ULONG_PTR)handle);
    json_string(info.szDevice);
    printf(",\"rect\":[%ld,%ld,%ld,%ld]}", info.rcMonitor.left, info.rcMonitor.top,
           info.rcMonitor.right, info.rcMonitor.bottom);
    return TRUE;
}

static void display_bindings(void)
{
    const char *machine = "\\Registry\\Machine\\";
    HKEY video, link, source, monitor;
    DWORD index, count = 0;
    putchar('[');
    if (!RegOpenKeyExA(HKEY_LOCAL_MACHINE, "HARDWARE\\DEVICEMAP\\VIDEO", 0, KEY_READ, &video))
    {
        for (index = 0;; ++index)
        {
            char name[128], value[512], target_utf8[1536] = {0}, monitor_id[512] = {0}, path[1024];
            WCHAR target[512] = {0};
            DWORD name_size = sizeof(name), value_size = sizeof(value), type, size;
            LONG status = RegEnumValueA(video, index, name, &name_size, NULL, &type, (BYTE *)value, &value_size);
            BOOL monitor_exists = FALSE;
            if (status == ERROR_NO_MORE_ITEMS) break;
            if (status || type != REG_SZ || strncmp(value, machine, strlen(machine))) continue;
            snprintf(path, sizeof(path), "System\\CurrentControlSet\\Hardware Profiles\\Current\\%s",
                     value + strlen(machine));
            if (!RegOpenKeyExA(HKEY_LOCAL_MACHINE, path, REG_OPTION_OPEN_LINK, KEY_READ, &link))
            {
                size = sizeof(target) - sizeof(WCHAR);
                if (!RegQueryValueExW(link, L"SymbolicLinkValue", NULL, &type, (BYTE *)target, &size))
                    WideCharToMultiByte(CP_UTF8, 0, target, -1, target_utf8, sizeof(target_utf8), NULL, NULL);
                RegCloseKey(link);
            }
            if (!RegOpenKeyExA(HKEY_LOCAL_MACHINE, path, 0, KEY_READ, &source))
            {
                size = sizeof(monitor_id);
                RegQueryValueExA(source, "MonitorID0", NULL, &type, (BYTE *)monitor_id, &size);
                RegCloseKey(source);
                snprintf(path, sizeof(path), "System\\CurrentControlSet\\Enum\\%s", monitor_id);
                if (monitor_id[0] && !RegOpenKeyExA(HKEY_LOCAL_MACHINE, path, 0, KEY_READ, &monitor))
                {
                    monitor_exists = TRUE;
                    RegCloseKey(monitor);
                }
            }
            printf("%s{\"device\":", count++ ? "," : "");
            json_string(name);
            printf(",\"link\":"); json_string(value);
            printf(",\"target\":"); json_string(target_utf8);
            printf(",\"monitor_id\":"); json_string(monitor_id);
            printf(",\"monitor_exists\":%s}", monitor_exists ? "true" : "false");
        }
        RegCloseKey(video);
    }
    putchar(']');
}

static void window_state(const char *name, HWND hwnd)
{
    RECT rect, region_box = {0};
    HRGN region = CreateRectRgn(0, 0, 0, 0);
    int region_type = GetWindowRgn(hwnd, region);
    GetWindowRect(hwnd, &rect);
    if (region_type != ERROR) GetRgnBox(region, &region_box);
    DeleteObject(region);
    printf("\"%s\":{\"rect\":[%ld,%ld,%ld,%ld],\"body\":%lu,\"frame\":%lu,"
           "\"iconic\":%d,\"region_type\":%d,\"region_box\":[%ld,%ld,%ld,%ld]}",
           name, rect.left, rect.top, rect.right, rect.bottom,
           (unsigned long)(ULONG_PTR)GetPropA(hwnd, "__wine_x11_whole_window"),
           (unsigned long)(ULONG_PTR)GetPropA(hwnd, "__wine_x11_wm_window"), IsIconic(hwnd), region_type,
           region_box.left, region_box.top, region_box.right, region_box.bottom);
}

static void state(void)
{
    typedef ULONG_PTR (WINAPI *call_two_type)(ULONG_PTR, ULONG_PTR, ULONG);
    call_two_type call_two = (call_two_type)GetProcAddress(GetModuleHandleA("win32u.dll"), "NtUserCallTwoParam");
    RECT raw = {0};
    unsigned count = 0;
    printf("{\"origin\":[%d,%d],\"monitors\":%d,\"display_changes\":%u,\"position_changes\":%u,",
           GetSystemMetrics(SM_XVIRTUALSCREEN), GetSystemMetrics(SM_YVIRTUALSCREEN),
           GetSystemMetrics(SM_CMONITORS), display_changes, position_changes);
    window_state("main", main_window);
    putchar(',');
    window_state("shadow", shadow);
    putchar(',');
    window_state("helper", helper);
    /* The pinned Wine source defines GetVirtualScreenRect=8 and MDT_RAW_DPI=2. */
    if (call_two) call_two((ULONG_PTR)&raw, 2, 8);
    printf(",\"raw_rect\":[%ld,%ld,%ld,%ld],\"enumerated_monitors\":[", raw.left, raw.top, raw.right, raw.bottom);
    EnumDisplayMonitors(NULL, NULL, monitor_state, (LPARAM)&count);
    printf("],\"bindings\":");
    display_bindings();
    puts("}");
    fflush(stdout);
}

static LRESULT CALLBACK proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    if (msg == WM_NCCALCSIZE) return 0;
    if (msg == WM_DISPLAYCHANGE) ++display_changes;
    if (msg == WM_WINDOWPOSCHANGED) ++position_changes;
    if (hwnd == main_window && shadow && (msg == WM_MOVE || msg == WM_SIZE))
    {
        RECT rect;
        GetWindowRect(hwnd, &rect);
        SetWindowPos(shadow, HWND_BOTTOM, rect.left - 8, rect.top - 8,
                     rect.right - rect.left + 16, rect.bottom - rect.top + 16,
                     SWP_NOACTIVATE | SWP_SHOWWINDOW);
    }
    if (msg == WM_PAINT)
    {
        PAINTSTRUCT paint;
        HDC dc = BeginPaint(hwnd, &paint);
        FillRect(dc, &paint.rcPaint, (HBRUSH)(COLOR_WINDOW + 1));
        EndPaint(hwnd, &paint);
        return 0;
    }
    if (msg == WM_APP)
    {
        if (wp == 's') state();
        else if (wp == 'e' || wp == 'n')
        {
            RECT rect;
            GetWindowRect(helper, &rect);
            SetWindowPos(helper, NULL, rect.left + (wp == 'n'), rect.top, 1, 1,
                         SWP_NOACTIVATE | SWP_NOZORDER);
        }
        else if (wp == 'i') ShowWindow(main_window, SW_MINIMIZE);
        else if (wp == 'm') ShowWindow(main_window, SW_MAXIMIZE);
        else if (wp == 'r') ShowWindow(main_window, SW_RESTORE);
        else if (wp == 'l')
            SetWindowPos(main_window, NULL, -2900, 180, 1000, 700, SWP_NOACTIVATE | SWP_NOZORDER);
        else if (wp == 'b' || wp == 'p' || wp == 'v')
        {
            RECT rect;
            unsigned flags = SWP_NOACTIVATE | SWP_NOZORDER;
            GetWindowRect(main_window, &rect);
            ResetEvent(resume_event);
            if (wp == 'b')
            {
                SetWindowPos(main_window, NULL, 0, 0, 1120, 740, flags | SWP_NOMOVE);
                SetWindowPos(main_window, NULL, 0, 0, 1160, 780, flags | SWP_NOMOVE);
            }
            else if (wp == 'p')
            {
                SetWindowPos(main_window, NULL, rect.left + 40, rect.top + 20, 0, 0, flags | SWP_NOSIZE);
                SetWindowPos(main_window, NULL, rect.left + 80, rect.top + 40, 0, 0, flags | SWP_NOSIZE);
            }
            else if (!PostMessageA(main_window, WM_WINE_UPDATEWINDOWSTATE, 0, 0)) ExitProcess(2);
            state();
            WaitForSingleObject(resume_event, INFINITE);
        }
        else if (wp == 'q') PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcA(hwnd, msg, wp, lp);
}

static DWORD WINAPI commands(void *unused)
{
    char line[16];
    (void)unused;
    while (fgets(line, sizeof(line), stdin))
    {
        if (line[0] == 'u' || line[0] == 'q') SetEvent(resume_event);
        if (line[0] != 'u') PostMessageA(main_window, WM_APP, line[0], 0);
    }
    return 0;
}

int main(void)
{
    WNDCLASSA wc = {.lpfnWndProc = proc, .hInstance = GetModuleHandleA(NULL), .lpszClassName = "DisplayRemoval"};
    WNDCLASSA decoration = {.lpfnWndProc = DefWindowProcA, .hInstance = wc.hInstance,
                           .lpszClassName = "DisplayRemovalShadow"};
    RECT rect;
    MSG msg;
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    RegisterClassA(&wc);
    RegisterClassA(&decoration);
    main_window = CreateWindowExA(0, wc.lpszClassName, "Display removal main",
                                  WS_POPUP | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU,
                                  200, 200, 1000, 700, NULL, NULL, wc.hInstance, NULL);
    shadow = CreateWindowExA(WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT,
                             decoration.lpszClassName, "", WS_POPUP, 0, 0, 1, 1,
                             main_window, NULL, wc.hInstance, NULL);
    SetLayeredWindowAttributes(shadow, 0, 100, LWA_ALPHA);
    ShowWindow(main_window, SW_SHOW);
    GetWindowRect(main_window, &rect);
    SetWindowPos(shadow, HWND_BOTTOM, rect.left - 8, rect.top - 8,
                 rect.right - rect.left + 16, rect.bottom - rect.top + 16, SWP_NOACTIVATE | SWP_SHOWWINDOW);
    helper = CreateWindowExA(WS_EX_NOACTIVATE | WS_EX_LAYERED | WS_EX_TOOLWINDOW,
                             wc.lpszClassName, "Display removal helper", WS_POPUP | WS_DISABLED | WS_CLIPSIBLINGS,
                             -2, 64, 1, 1, NULL, NULL, wc.hInstance, NULL);
    SetLayeredWindowAttributes(helper, 0, 255, LWA_ALPHA);
    ShowWindow(helper, SW_SHOWNOACTIVATE);
    resume_event = CreateEventA(NULL, TRUE, FALSE, NULL);
    state();
    CloseHandle(CreateThread(NULL, 0, commands, NULL, 0, NULL));
    while (GetMessageA(&msg, NULL, 0, 0)) { TranslateMessage(&msg); DispatchMessageA(&msg); }
    DestroyWindow(helper);
    DestroyWindow(shadow);
    DestroyWindow(main_window);
    CloseHandle(resume_event);
    return 0;
}
