#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>

static HWND window, shadow;
static HANDLE draw, finish;
static BOOL armed;
static COLORREF color = RGB(0, 255, 0);

static void state(const char *phase)
{
    RECT client;
    GetClientRect(window, &client);
    printf("{\"phase\":\"%s\",\"client\":[%ld,%ld],\"body\":%lu,\"frame\":%lu}\n",
           phase, client.right, client.bottom,
           (unsigned long)(UINT_PTR)GetPropA(window, "__wine_x11_whole_window"),
           (unsigned long)(UINT_PTR)GetPropA(window, "__wine_x11_wm_window"));
    fflush(stdout);
}

static LRESULT CALLBACK procedure(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam)
{
    if (message == WM_NCCALCSIZE || message == WM_ERASEBKGND) return 0;
    if (message == WM_GETMINMAXINFO && hwnd == window)
    {
        MONITORINFO info = {.cbSize = sizeof(info)};
        MINMAXINFO *limits = (MINMAXINFO *)lparam;
        GetMonitorInfoA(MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST), &info);
        limits->ptMaxPosition.x = info.rcWork.left - info.rcMonitor.left;
        limits->ptMaxPosition.y = info.rcWork.top - info.rcMonitor.top;
        limits->ptMaxSize.x = info.rcWork.right - info.rcWork.left;
        limits->ptMaxSize.y = info.rcWork.bottom - info.rcWork.top;
        return 0;
    }
    if (message == WM_SIZE && hwnd == window && armed && wparam == SIZE_MAXIMIZED)
    {
        RECT client;
        HDC dc;
        state("before-draw");
        WaitForSingleObject(draw, INFINITE);
        color = RGB(0, 0, 255);
        GetClientRect(window, &client);
        dc = GetDC(window);
        SetDCBrushColor(dc, color);
        FillRect(dc, &client, GetStockObject(DC_BRUSH));
        ReleaseDC(window, dc);
        GdiFlush();
        state("after-draw");
        WaitForSingleObject(finish, INFINITE);
    }
    if (message == WM_PAINT)
    {
        PAINTSTRUCT paint;
        HDC dc = BeginPaint(hwnd, &paint);
        SetDCBrushColor(dc, hwnd == window ? color : RGB(60, 60, 60));
        FillRect(dc, &paint.rcPaint, GetStockObject(DC_BRUSH));
        EndPaint(hwnd, &paint);
        return 0;
    }
    if (message == WM_APP)
    {
        if (wparam == 'm')
        {
            armed = TRUE;
            ShowWindow(window, SW_MAXIMIZE);
            armed = FALSE;
            state("done");
        }
        if (wparam == 'q') PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcA(hwnd, message, wparam, lparam);
}

static DWORD WINAPI commands(void *unused)
{
    char line[32];
    (void)unused;
    while (fgets(line, sizeof(line), stdin))
    {
        if (line[0] == 'd') SetEvent(draw);
        else if (line[0] == 'f') SetEvent(finish);
        else
        {
            if (line[0] == 'q')
            {
                SetEvent(draw);
                SetEvent(finish);
            }
            PostMessageA(window, WM_APP, line[0], 0);
        }
    }
    return 0;
}

int main(void)
{
    WNDCLASSA cls = {.lpfnWndProc = procedure, .lpszClassName = "ResizeDrawable"};
    MSG message;
    DWORD started;
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    RegisterClassA(&cls);
    cls.lpszClassName = "ResizeDrawableShadow";
    RegisterClassA(&cls);
    draw = CreateEventA(NULL, FALSE, FALSE, NULL);
    finish = CreateEventA(NULL, FALSE, FALSE, NULL);
    window = CreateWindowExA(0, "ResizeDrawable", "Resize drawable ordering",
                             WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX,
                             200, 200, 1000, 700, NULL, NULL, NULL, NULL);
    shadow = CreateWindowExA(WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
                             "ResizeDrawableShadow", "", WS_POPUP, 164, 164, 1072, 772,
                             window, NULL, NULL, NULL);
    SetLayeredWindowAttributes(shadow, 0, 255, LWA_ALPHA);
    ShowWindow(window, SW_SHOW);
    ShowWindow(shadow, SW_SHOWNOACTIVATE);
    UpdateWindow(window);
    UpdateWindow(shadow);
    started = GetTickCount();
    do
    {
        while (PeekMessageA(&message, NULL, 0, 0, PM_REMOVE)) DispatchMessageA(&message);
        Sleep(1);
    } while (GetTickCount() - started < 300);
    state("ready");
    CloseHandle(CreateThread(NULL, 0, commands, NULL, 0, NULL));
    while (GetMessageA(&message, NULL, 0, 0) > 0) DispatchMessageA(&message);
    DestroyWindow(shadow);
    DestroyWindow(window);
    CloseHandle(draw);
    CloseHandle(finish);
    return 0;
}
