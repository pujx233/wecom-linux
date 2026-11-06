#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <string.h>
static HWND window, shadow;
static BOOL armed;
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
        InvalidateRect(window, NULL, FALSE);
        UpdateWindow(window);
    }
    if (message == WM_PAINT)
    {
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
    WNDCLASSA cls = {.lpfnWndProc = procedure, .lpszClassName = "ResizeExtents"};
    RECT rect;
    MSG msg;
    int padding = argc > 1 && !strcmp(argv[1], "--stationary") ? 0 : 48;
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    RegisterClassA(&cls);
    cls.lpszClassName = "ResizeExtentsShadow";
    RegisterClassA(&cls);
    window = CreateWindowExA(0, "ResizeExtents", "Resize with matching outer size", WS_THICKFRAME | WS_SYSMENU,
                             400, 300, 320, 240, NULL, NULL, NULL, NULL);
    ShowWindow(window, SW_SHOW);
    UpdateWindow(window);
    pump();
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
