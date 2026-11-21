#define _WIN32_WINNT 0x0a00
#include <windows.h>
#include <stdio.h>

static HWND main_window, helper_window;
static unsigned stage;
static BOOL foreground_first;

static LRESULT CALLBACK proc(HWND hwnd, UINT message, WPARAM wp, LPARAM lp)
{
    if (hwnd == main_window && message == WM_TIMER)
    {
        if (!stage++)
        {
            ShowWindow(main_window, SW_MINIMIZE);
            puts("{\"event\":\"minimized\"}");
        }
        else if (stage == 2)
        {
            if (foreground_first) SetForegroundWindow(main_window);
            ShowWindow(main_window, SW_RESTORE);
            SetForegroundWindow(main_window);
            SetFocus(main_window);
            puts("{\"event\":\"restored\"}");
        }
        else if (stage == 3)
        {
            printf("{\"event\":\"result\",\"foreground\":%llu,\"expected\":%llu}\n",
                   (unsigned long long)(ULONG_PTR)GetForegroundWindow(),
                   (unsigned long long)(ULONG_PTR)main_window);
        }
        else { DestroyWindow(helper_window); DestroyWindow(main_window); }
        fflush(stdout);
        return 0;
    }
    if (hwnd == main_window && message == WM_DESTROY) { PostQuitMessage(0); return 0; }
    return DefWindowProcW(hwnd, message, wp, lp);
}

int main(int argc, char **argv)
{
    WNDCLASSW cls = {.lpfnWndProc = proc, .hInstance = GetModuleHandleW(NULL),
                     .lpszClassName = L"RestoreFocusRegression"};
    MSG message;

    (void)argv;
    foreground_first = argc > 1;
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_UNAWARE);
    if (!RegisterClassW(&cls)) return 2;
    helper_window = CreateWindowExW(WS_EX_TOOLWINDOW, cls.lpszClassName, L"restore focus helper",
                                    WS_POPUP, 0, 0, 1, 1, NULL, NULL, cls.hInstance, NULL);
    main_window = CreateWindowExW(0, cls.lpszClassName, L"restore focus main", WS_OVERLAPPEDWINDOW,
                                  100, 100, 600, 400, NULL, NULL, cls.hInstance, NULL);
    if (!helper_window || !main_window) return 3;
    ShowWindow(helper_window, SW_SHOWNOACTIVATE);
    ShowWindow(main_window, SW_SHOW);
    SetForegroundWindow(main_window);
    SetFocus(main_window);
    printf("{\"event\":\"ready\",\"body\":%lu,\"frame\":%lu,\"helper\":%lu}\n",
           (unsigned long)(ULONG_PTR)GetPropW(main_window, L"__wine_x11_whole_window"),
           (unsigned long)(ULONG_PTR)GetPropW(main_window, L"__wine_x11_wm_window"),
           (unsigned long)(ULONG_PTR)GetPropW(helper_window, L"__wine_x11_whole_window"));
    fflush(stdout);
    SetTimer(main_window, 1, 1500, NULL);
    while (GetMessageW(&message, NULL, 0, 0) > 0)
    {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    return 0;
}
