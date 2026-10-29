/* Hold the message loop after painting a resized, reused backing surface. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <string.h>

static HWND window;

static LRESULT CALLBACK proc(HWND hwnd, UINT message, WPARAM wp, LPARAM lp)
{
    if (message == WM_NCCALCSIZE || message == WM_ERASEBKGND) return 0;
    if (message == WM_PAINT) { ValidateRect(hwnd, NULL); return 0; }
    return DefWindowProcW(hwnd, message, wp, lp);
}

static void paint(COLORREF color)
{
    PAINTSTRUCT ps;
    RECT rect;
    HBRUSH brush = CreateSolidBrush(color);
    InvalidateRect(window, NULL, FALSE);
    BeginPaint(window, &ps);
    GetClientRect(window, &rect);
    FillRect(ps.hdc, &rect, brush);
    DeleteObject(brush);
    EndPaint(window, &ps);
}

static void pump(void)
{
    MSG message;
    DWORD start = GetTickCount();
    do
    {
        while (PeekMessageW(&message, NULL, 0, 0, PM_REMOVE)) DispatchMessageW(&message);
        Sleep(5);
    } while (GetTickCount() - start < 300);
}

int main(void)
{
    WNDCLASSW cls = {.lpfnWndProc = proc, .lpszClassName = L"FrameSyncCompletion"};
    HWND decoration;
    char command[32], guard[8];
    POINT point = {100, 100};
    if (!GetEnvironmentVariableA("WECOM_FRAME_SYNC_FIXTURE", guard, sizeof(guard)) || strcmp(guard, "1"))
        return 2;
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    if (!RegisterClassW(&cls)) return 3;
    window = CreateWindowExW(0, cls.lpszClassName, L"Frame sync completion", WS_POPUP | WS_THICKFRAME,
                            200, 160, 320, 240, NULL, NULL, NULL, NULL);
    if (!window) return 4;
    ShowWindow(window, SW_SHOW);
    decoration = CreateWindowExW(WS_EX_LAYERED | WS_EX_TOOLWINDOW, cls.lpszClassName, L"Frame decoration",
                                  WS_POPUP, 200, 160, 320, 20, window, NULL, NULL, NULL);
    if (!decoration) return 6;
    SetLayeredWindowAttributes(decoration, 0, 255, LWA_ALPHA);
    ShowWindow(decoration, SW_SHOWNOACTIVATE);
    pump();
    paint(RGB(48, 176, 96));
    pump();
    ClientToScreen(window, &point);
    printf("{\"phase\":\"ready\",\"frame\":%llu,\"decoration_frame\":%llu,\"point\":[%ld,%ld]}\n",
           (unsigned long long)(UINT_PTR)GetPropW(window, L"__wine_x11_wm_window"),
           (unsigned long long)(UINT_PTR)GetPropW(decoration, L"__wine_x11_wm_window"), point.x, point.y);
    fflush(stdout);
    while (fgets(command, sizeof(command), stdin))
    {
        command[strcspn(command, "\r\n")] = 0;
        if (!strcmp(command, "quit")) break;
        if (!strcmp(command, "paint"))
        {
            /* 320 and 328 use the same 384-pixel backing surface. */
            fputs("FRAME_SYNC_RESIZE_BEGIN\n", stderr);
            fflush(stderr);
            InvalidateRect(window, NULL, FALSE);
            SetWindowPos(window, NULL, 0, 0, 328, 240, SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE);
            paint(RGB(64, 96, 192));
            fputs("FRAME_SYNC_RESIZE_END\n", stderr);
            fflush(stderr);
            /* No message dispatch here: the frame copy is still queued. */
        }
        else if (!strcmp(command, "dispatch")) pump();
        else return 5;
        printf("{\"phase\":\"%s\"}\n", command);
        fflush(stdout);
    }
    DestroyWindow(window);
    return 0;
}
