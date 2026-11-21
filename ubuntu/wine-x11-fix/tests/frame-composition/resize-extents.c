#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <string.h>
static HWND window, shadow, child;
static BOOL armed;
static BOOL direct_dc, dc_active, foreign_dc;
static COLORREF color = RGB(0, 255, 0);
static void state(const char *phase)
{
    RECT rect;
    GetWindowRect(window, &rect);
    printf("{\"phase\":\"%s\",\"rect\":[%ld,%ld,%ld,%ld],\"frame\":%lu,\"body\":%lu}\n",
           phase, rect.left, rect.top, rect.right, rect.bottom,
           (unsigned long)(UINT_PTR)GetPropA(window, "__wine_x11_wm_window"),
           (unsigned long)(UINT_PTR)GetPropA(window, "__wine_x11_whole_window"));
    fflush(stdout);
}
static LRESULT CALLBACK procedure(HWND hwnd, UINT message, WPARAM wp, LPARAM lp)
{
    if (message == WM_NCCALCSIZE || message == WM_ERASEBKGND) return 0;
    if (message == WM_SIZE && hwnd == window && armed)
    {
        ShowWindow(shadow, SW_HIDE);
        color = RGB(0, 0, 255);
        if (direct_dc)
        {
            RECT rect;
            HWND target = child ? child : hwnd;
            HDC dc;
            dc_active = TRUE;
            GetClientRect(hwnd, &rect);
            if (child) SetWindowPos(child, NULL, 0, 0, rect.right, rect.bottom, SWP_NOZORDER | SWP_NOACTIVATE);
            if (foreign_dc)
            {
                char path[MAX_PATH], command[MAX_PATH + 80];
                PROCESS_INFORMATION process;
                STARTUPINFOA startup = {.cb = sizeof(startup)};
                DWORD status;
                GetModuleFileNameA(NULL, path, sizeof(path));
                snprintf(command, sizeof(command), "\"%s\" --draw %lu", path, (unsigned long)(UINT_PTR)target);
                if (!CreateProcessA(path, command, NULL, NULL, FALSE, 0, NULL, NULL, &startup, &process))
                    ExitProcess(2);
                CloseHandle(process.hThread);
                if (WaitForSingleObject(process.hProcess, 10000) != WAIT_OBJECT_0) ExitProcess(2);
                if (!GetExitCodeProcess(process.hProcess, &status) || status) ExitProcess(2);
                CloseHandle(process.hProcess);
                return 0;
            }
            dc = GetDC(target);
            SetDCBrushColor(dc, color);
            FillRect(dc, &rect, GetStockObject(DC_BRUSH));
            ReleaseDC(target, dc);
            return 0;
        }
        InvalidateRect(window, NULL, FALSE);
        UpdateWindow(window);
    }
    if (message == WM_PAINT)
    {
        /* Keep EndPaint and ValidateRect from completing the direct-DC presentation for us. */
        if ((hwnd == window || hwnd == child) && dc_active) return 0;
        PAINTSTRUCT ps;
        HDC dc = BeginPaint(hwnd, &ps);
        SetDCBrushColor(dc, hwnd == window ? color : RGB(60, 60, 60));
        FillRect(dc, &ps.rcPaint, GetStockObject(DC_BRUSH));
        EndPaint(hwnd, &ps);
        return 0;
    }
    if (message == WM_APP)
    {
        if (wp == 'g')
        {
            armed = TRUE;
            SetWindowPos(window, NULL, 0, 0, 416, 336, SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE);
            armed = FALSE;
            state("grown");
        }
        if (wp == 's') state("state");
        if (wp == 'q') PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcA(hwnd, message, wp, lp);
}
static void pump(void)
{
    MSG msg;
    DWORD start = GetTickCount();
    do
    {
        while (PeekMessageA(&msg, NULL, 0, 0, PM_REMOVE)) DispatchMessageA(&msg);
        Sleep(1);
    } while (GetTickCount() - start < 300);
}
static DWORD WINAPI commands(void *unused)
{
    char line[16];
    (void)unused;
    while (fgets(line, sizeof(line), stdin)) PostMessageA(window, WM_APP, line[0], 0);
    return 0;
}
int main(int argc, char **argv)
{
    if (argc == 3 && !strcmp(argv[1], "--draw"))
    {
        HWND target = (HWND)(UINT_PTR)strtoul(argv[2], NULL, 10);
        RECT area;
        HDC dc;
        SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
        if (!GetClientRect(target, &area) || !(dc = GetDC(target))) return 2;
        SetDCBrushColor(dc, RGB(0, 0, 255));
        FillRect(dc, &area, GetStockObject(DC_BRUSH));
        return ReleaseDC(target, dc) ? 0 : 2;
    }
    WNDCLASSA cls = {.lpfnWndProc = procedure, .lpszClassName = "ResizeExtents"};
    RECT rect;
    MSG msg;
    int padding = 48;
    BOOL child_dc = FALSE;
    for (int i = 1; i < argc; ++i)
    {
        if (!strcmp(argv[i], "--stationary")) padding = 0;
        if (!strcmp(argv[i], "--dc")) direct_dc = TRUE;
        if (!strcmp(argv[i], "--child-dc")) direct_dc = child_dc = TRUE;
        if (!strcmp(argv[i], "--foreign-dc")) direct_dc = foreign_dc = TRUE;
    }
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    RegisterClassA(&cls);
    cls.lpszClassName = "ResizeExtentsShadow";
    RegisterClassA(&cls);
    window = CreateWindowExA(0, "ResizeExtents", "Resize with matching outer size", WS_THICKFRAME | WS_SYSMENU,
                             400, 300, 320, 240, NULL, NULL, NULL, NULL);
    ShowWindow(window, SW_SHOW);
    UpdateWindow(window);
    pump();
    if (child_dc)
    {
        child = CreateWindowExA(0, "ResizeExtents", "", WS_CHILD | WS_VISIBLE, 0, 0, 320, 240,
                               window, NULL, NULL, NULL);
        if (!child) return 2;
        UpdateWindow(child);
    }
    GetWindowRect(window, &rect);
    shadow = CreateWindowExA(WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
                             "ResizeExtentsShadow", "", WS_POPUP, rect.left - padding, rect.top - padding,
                             416, 336, window, NULL, NULL, NULL);
    SetLayeredWindowAttributes(shadow, 0, 255, LWA_ALPHA);
    ShowWindow(shadow, SW_SHOWNOACTIVATE);
    UpdateWindow(shadow);
    pump();
    state("ready");
    CloseHandle(CreateThread(NULL, 0, commands, NULL, 0, NULL));
    while (GetMessageA(&msg, NULL, 0, 0) > 0) DispatchMessageA(&msg);
    DestroyWindow(shadow);
    DestroyWindow(window);
    return 0;
}
