#define _WIN32_WINNT 0x0a00
#include <windows.h>
#include <stdio.h>

static HWND owner, popup;
static unsigned samples, focused, lost;
static BOOL passed;

static LRESULT CALLBACK proc(HWND hwnd, UINT message, WPARAM wp, LPARAM lp)
{
    if (hwnd == popup && message == WM_KILLFOCUS)
    {
        lost++;
        ShowWindow(hwnd, SW_HIDE);
    }
    if (hwnd == owner && message == WM_TIMER && wp == 1)
    {
        KillTimer(owner, 1);
        popup = CreateWindowExW(WS_EX_TOOLWINDOW, L"PopupFocusRegression", L"unmanaged popup",
                                WS_POPUP, 200, 200, 300, 150, owner, NULL, GetModuleHandleW(NULL), NULL);
        if (!popup) ExitProcess(3);
        ShowWindow(popup, SW_SHOW);
        SetForegroundWindow(popup);
        SetActiveWindow(popup);
        SetFocus(popup);
        printf("{\"event\":\"popup\",\"body\":%lu,\"frame\":%lu}\n",
               (unsigned long)(ULONG_PTR)GetPropW(popup, L"__wine_x11_whole_window"),
               (unsigned long)(ULONG_PTR)GetPropW(popup, L"__wine_x11_wm_window"));
        fflush(stdout);
        SetTimer(owner, 2, 100, NULL);
        return 0;
    }
    if (hwnd == owner && message == WM_TIMER && wp == 2)
    {
        samples++;
        focused += GetForegroundWindow() == popup;
        if (samples == 20)
        {
            passed = focused == samples && !lost && IsWindowVisible(popup);
            printf("{\"event\":\"result\",\"samples\":%u,\"focused\":%u,\"lost\":%u,\"visible\":%s}\n",
                   samples, focused, lost, IsWindowVisible(popup) ? "true" : "false");
            fflush(stdout);
            DestroyWindow(owner);
        }
        return 0;
    }
    if (hwnd == owner && message == WM_DESTROY) { PostQuitMessage(0); return 0; }
    return DefWindowProcW(hwnd, message, wp, lp);
}

int main(void)
{
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_UNAWARE);
    WNDCLASSW cls = {.lpfnWndProc = proc, .hInstance = GetModuleHandleW(NULL),
                     .lpszClassName = L"PopupFocusRegression"};
    if (!RegisterClassW(&cls)) return 2;
    owner = CreateWindowExW(0, cls.lpszClassName, L"popup focus owner", WS_OVERLAPPEDWINDOW,
                            100, 100, 800, 600, NULL, NULL, cls.hInstance, NULL);
    if (!owner) return 2;
    ShowWindow(owner, SW_SHOW);
    SetForegroundWindow(owner);
    SetTimer(owner, 1, 1500, NULL);
    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0) > 0) { TranslateMessage(&msg); DispatchMessageW(&msg); }
    return passed ? 0 : 1;
}
