#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <imm.h>
#include <shellscalingapi.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define WM_APPLY (WM_APP + 1)
#define WM_COMMAND_READY (WM_APP + 3)
static HWND root_window, input_window, other_window;
static int caret_height = 24;
static BOOL quit;
static const char *awareness;
static POINT caret_point = {30, 40}, anchor_point = {30, 40};
static unsigned sequence;
struct monitor_selection { int index; RECT rect; BOOL found; };

static BOOL CALLBACK select_monitor(HMONITOR monitor, HDC dc, RECT *rect, LPARAM parameter)
{
    struct monitor_selection *selection = (struct monitor_selection *)parameter;
    (void)monitor;
    (void)dc;
    if (selection->index--) return TRUE;
    selection->rect = *rect;
    selection->found = TRUE;
    return FALSE;
}

static void pump(DWORD milliseconds)
{
    DWORD deadline = GetTickCount() + milliseconds;
    MSG msg;
    do
    {
        while (PeekMessageW(&msg, NULL, 0, 0, PM_REMOVE))
        {
            if (msg.message == WM_QUIT) quit = TRUE;
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        Sleep(5);
    } while (!quit && (INT)(deadline - GetTickCount()) > 0);
}

static void report(const char *event, HWND hwnd, BOOL ok, POINT point, RECT area)
{
    GUITHREADINFO info = {.cbSize = sizeof(info)};
    POINT physical = point, lower = {point.x, area.bottom};
    RECT root_rect, client_rect, root_client;
    POINT root_anchor_origin = {0, 0};
    DPI_AWARENESS_CONTEXT context;
    UINT raw_dpi_x = 0, raw_dpi_y = 0;
    HWND root = GetAncestor(hwnd, GA_ROOT);
    DWORD root_pid, pid;
    ok = GetGUIThreadInfo(GetCurrentThreadId(), &info) && ok;
    GetWindowThreadProcessId(root, &root_pid);
    GetWindowThreadProcessId(hwnd, &pid);
    ClientToScreen(hwnd, &physical);
    ClientToScreen(hwnd, &lower);
    LogicalToPhysicalPointForPerMonitorDPI(hwnd, &physical);
    LogicalToPhysicalPointForPerMonitorDPI(hwnd, &lower);
    GetWindowRect(root, &root_rect);
    GetClientRect(hwnd, &client_rect);
    GetClientRect(root, &root_client);
    ClientToScreen(root, &root_anchor_origin);
    LogicalToPhysicalPointForPerMonitorDPI(root, &root_anchor_origin);
    context = SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE);
    ok = SUCCEEDED(GetDpiForMonitor(MonitorFromWindow(root, MONITOR_DEFAULTTONEAREST), MDT_RAW_DPI,
                                   &raw_dpi_x, &raw_dpi_y)) && ok;
    SetThreadDpiAwarenessContext(context);
    printf("{\"event\":\"%s\",\"sequence\":%u,\"ok\":%d,\"pid\":%lu,\"root_pid\":%lu,"
           "\"hwnd\":%llu,\"root\":%llu,\"xid\":%llu,\"frame\":%llu,\"dpi\":%u,"
           "\"awareness\":\"%s\",\"client\":[%ld,%ld],\"physical\":[%ld,%ld],"
           "\"lower_physical\":[%ld,%ld],\"area\":[%ld,%ld,%ld,%ld],"
           "\"root_rect\":[%ld,%ld,%ld,%ld],\"client_size\":[%ld,%ld],"
           "\"root_client_size\":[%ld,%ld],\"root_dpi\":%u,\"root_raw_dpi\":[%u,%u],"
           "\"root_anchor_origin\":[%ld,%ld],\"focus\":%llu,\"caret\":%llu}\n",
           event, ++sequence, ok, pid, root_pid, (unsigned long long)(UINT_PTR)hwnd,
           (unsigned long long)(UINT_PTR)root,
           (unsigned long long)(UINT_PTR)GetPropA(root, "__wine_x11_whole_window"),
           (unsigned long long)(UINT_PTR)GetPropA(root, "__wine_x11_wm_window"), GetDpiForWindow(hwnd),
           awareness, point.x, point.y, physical.x, physical.y, lower.x, lower.y,
           area.left, area.top, area.right, area.bottom,
           root_rect.left, root_rect.top, root_rect.right, root_rect.bottom,
           client_rect.right, client_rect.bottom,
           root_client.right, root_client.bottom, GetDpiForWindow(root), raw_dpi_x, raw_dpi_y,
           root_anchor_origin.x, root_anchor_origin.y,
           (unsigned long long)(UINT_PTR)info.hwndFocus, (unsigned long long)(UINT_PTR)info.hwndCaret);
    fflush(stdout);
}

static void focus_input(HWND hwnd)
{
    SetForegroundWindow(GetAncestor(hwnd, GA_ROOT));
    SetFocus(hwnd);
}

static void apply(HWND hwnd, UINT operation, POINT point)
{
    RECT area = {point.x, point.y, point.x + 2, point.y + caret_height};
    BOOL ok = FALSE;
    const char *event = "unknown";
    HIMC context;
    focus_input(hwnd);
    switch (operation)
    {
    case 1:
    case 5:
        caret_height = operation == 5 ? 48 : 24;
        area.bottom = point.y + caret_height;
        DestroyCaret();
        ok = CreateCaret(hwnd, NULL, 2, caret_height);
        ok = SetCaretPos(point.x, point.y) && ok;
        ok = ShowCaret(hwnd) && ok;
        caret_point = point;
        event = operation == 5 ? "tall" : "caret";
        break;
    case 2:
    case 6:
    case 7:
    case 8:
    case 9:
    case 10:
    case 13:
    {
        if (operation == 6 || operation == 13)
        {
            if (!other_window)
            {
                other_window = CreateWindowW(L"ImePositionInput", NULL, WS_CHILD | WS_VISIBLE,
                                              40, 50, 550, 350, root_window, NULL, GetModuleHandleW(NULL), NULL);
                ImmAssociateContextEx(other_window, NULL, IACE_DEFAULT);
            }
            if (operation == 6) hwnd = other_window;
            focus_input(other_window);
        }
        if (operation == 7) DestroyCaret();
        COMPOSITIONFORM form = {CFS_POINT, point, {0, 0, 0, 0}};
        if (operation == 8 || operation == 9)
        {
            area.right = point.x + (operation == 8 ? 200 : 1);
            area.bottom = point.y + (operation == 8 ? 100 : 1);
            form.dwStyle = CFS_RECT;
            form.rcArea = area;
        }
        if (operation == 10) form.dwStyle = CFS_FORCE_POSITION;
        context = ImmGetContext(hwnd);
        ok = context && ImmSetCompositionWindow(context, &form);
        if (context) ImmReleaseContext(hwnd, context);
        event = operation == 6 ? "blur" : operation == 7 ? "destroy" :
                operation == 8 ? "area" : operation == 9 ? "small-area" :
                operation == 10 ? "force" : operation == 13 ? "stale" : "composition";
        break;
    }
    case 11:
    case 12:
    {
        CANDIDATEFORM form = {0, CFS_CANDIDATEPOS, point, {0, 0, 0, 0}};
        if (operation == 12)
        {
            area.left -= 4;
            area.right += 40;
            form.dwStyle = CFS_EXCLUDE;
            form.rcArea = area;
        }
        context = ImmGetContext(hwnd);
        ok = context && ImmSetCandidateWindow(context, &form);
        if (context) ImmReleaseContext(hwnd, context);
        event = operation == 11 ? "candidate" : "exclude";
        break;
    }
    default:
        event = "state";
        ok = TRUE;
        break;
    }
    anchor_point = point;
    report(event, hwnd, ok, point, area);
}

static LRESULT CALLBACK input_proc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam)
{
    if (message == WM_APPLY)
    {
        POINT point = {(SHORT)LOWORD(lparam), (SHORT)HIWORD(lparam)};
        apply(hwnd, (UINT)wparam, point);
        return 0;
    }
    return DefWindowProcW(hwnd, message, wparam, lparam);
}

static DWORD WINAPI read_commands(void *unused)
{
    char command[80];
    (void)unused;
    while (fgets(command, sizeof(command), stdin))
    {
        char *copy = malloc(strlen(command) + 1);
        if (!copy) break;
        strcpy(copy, command);
        if (!PostMessageW(root_window, WM_COMMAND_READY, 0, (LPARAM)copy)) { free(copy); break; }
        if (!strncmp(command, "quit", 4)) return 0;
    }
    PostMessageW(root_window, WM_CLOSE, 0, 0);
    return 0;
}

static LRESULT CALLBACK root_proc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam)
{
    if (message == WM_COMMAND_READY)
    {
        char operation[32], *command = (char *)lparam;
        int x = 30, y = 40;
        int count = sscanf(command, "%31s %d %d", operation, &x, &y);
        free(command);
        if (count < 1) return 0;
        if (!strcmp(operation, "quit")) { PostMessageW(hwnd, WM_CLOSE, 0, 0); return 0; }
        if (!strcmp(operation, "move") || !strcmp(operation, "screen"))
        {
            if (!strcmp(operation, "screen"))
            {
                struct monitor_selection selection = {.index = x};
                EnumDisplayMonitors(NULL, NULL, select_monitor, (LPARAM)&selection);
                if (!selection.found) return 0;
                x = selection.rect.left + 40;
                y = selection.rect.top + 40;
            }
            SetWindowPos(root_window, NULL, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE);
            pump(100);
            SendMessageW(input_window, WM_APPLY, 0, MAKELPARAM(anchor_point.x, anchor_point.y));
        }
        else if (!strcmp(operation, "maximize") || !strcmp(operation, "restore"))
        {
            ShowWindow(root_window, !strcmp(operation, "maximize") ? SW_MAXIMIZE : SW_RESTORE);
            pump(100);
            SendMessageW(input_window, WM_APPLY, 0, MAKELPARAM(anchor_point.x, anchor_point.y));
        }
        else
        {
            UINT code = !strcmp(operation, "caret") ? 1 : !strcmp(operation, "composition") ? 2 :
                        !strcmp(operation, "tall") ? 5 : !strcmp(operation, "blur") ? 6 :
                        !strcmp(operation, "destroy") ? 7 : !strcmp(operation, "area") ? 8 :
                        !strcmp(operation, "small-area") ? 9 : !strcmp(operation, "force") ? 10 :
                        !strcmp(operation, "candidate") ? 11 : !strcmp(operation, "exclude") ? 12 :
                        !strcmp(operation, "stale") ? 13 : 0;
            SendMessageW(input_window, WM_APPLY, code, MAKELPARAM(x, y));
        }
        return 0;
    }
    if (message == WM_CLOSE)
    {
        DestroyWindow(hwnd);
        return 0;
    }
    if (message == WM_DESTROY) PostQuitMessage(0);
    return DefWindowProcW(hwnd, message, wparam, lparam);
}

int main(int argc, char **argv)
{
    WNDCLASSW cls = {0};
    char guard[16], display[32];
    MSG msg;
    if (!GetEnvironmentVariableA("WECOM_IME_FIXTURE", guard, sizeof(guard)) || strcmp(guard, "1")) return 2;
    if (!GetEnvironmentVariableA("DISPLAY", display, sizeof(display)) || !strcmp(display, ":0")) return 3;
    awareness = argc > 1 ? argv[1] : "pm";
    if (!strcmp(awareness, "pm")) SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    else if (!strcmp(awareness, "system")) SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_SYSTEM_AWARE);
    else if (strcmp(awareness, "unaware")) return 4;
    cls.hInstance = GetModuleHandleW(NULL);
    cls.hbrBackground = GetSysColorBrush(COLOR_WINDOW);
    cls.lpszClassName = L"ImePositionInput";
    cls.lpfnWndProc = input_proc;
    if (!RegisterClassW(&cls)) return 5;
    cls.lpszClassName = L"ImePositionRoot";
    cls.lpfnWndProc = root_proc;
    if (!RegisterClassW(&cls)) return 6;
    root_window = CreateWindowW(cls.lpszClassName, L"Isolated IME position fixture", WS_OVERLAPPEDWINDOW,
                                160, 100, 700, 520, NULL, NULL, cls.hInstance, NULL);
    if (!root_window) return 7;
    ShowWindow(root_window, SW_SHOW);
    UpdateWindow(root_window);
    input_window = CreateWindowW(L"ImePositionInput", NULL, WS_CHILD | WS_VISIBLE | WS_TABSTOP,
                                40, 50, 550, 350, root_window, NULL, cls.hInstance, NULL);
    if (!input_window) return 9;
    ImmAssociateContextEx(input_window, NULL, IACE_DEFAULT);
    focus_input(input_window);
    pump(300);
    report("ready", input_window, TRUE, caret_point, (RECT){30, 40, 32, 64});
    HANDLE reader = CreateThread(NULL, 0, read_commands, NULL, 0, NULL);
    if (!reader) return 10;
    while (GetMessageW(&msg, NULL, 0, 0) > 0) { TranslateMessage(&msg); DispatchMessageW(&msg); }
    CloseHandle(reader);
    DestroyWindow(root_window);
    return 0;
}
