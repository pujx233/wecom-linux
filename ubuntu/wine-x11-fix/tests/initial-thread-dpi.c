#define _WIN32_WINNT 0x0a00
#include <windows.h>
#include <shellscalingapi.h>
#include <stdio.h>
#include <string.h>

static const WCHAR class_name[] = L"InitialThreadDpiTest";

static LRESULT CALLBACK wndproc(HWND window, UINT message, WPARAM wp, LPARAM lp)
{
    if (message == WM_APP)
    {
        HWND created = CreateWindowW(class_name, NULL, WS_POPUP, 0, 0, 100, 100, NULL, NULL,
                                     GetModuleHandleW(NULL), NULL);
        if (!created) return 0;
        DPI_AWARENESS_CONTEXT context = GetWindowDpiAwarenessContext(created);
        DestroyWindow(created);
        return (LRESULT)context;
    }
    return DefWindowProcW(window, message, wp, lp);
}

int main(int argc, char **argv)
{
    if (argc != 2) return 2;
    BOOL early = !strcmp(argv[1], "early");
    BOOL legacy = !strcmp(argv[1], "legacy");
    DPI_AWARENESS_CONTEXT expected = early ? DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
                                          : DPI_AWARENESS_CONTEXT_UNAWARE;
    DPI_AWARENESS window_expected = early ? DPI_AWARENESS_PER_MONITOR_AWARE : DPI_AWARENESS_UNAWARE;
    PROCESS_DPI_AWARENESS process;
    if (GetProcessDpiAwareness(NULL, &process) != S_OK || process != PROCESS_DPI_UNAWARE ||
        !AreDpiAwarenessContextsEqual(GetThreadDpiAwarenessContext(), expected))
        return 1;

    WNDCLASSW cls = {.lpfnWndProc = wndproc, .hInstance = GetModuleHandleW(NULL), .lpszClassName = class_name};
    if (!RegisterClassW(&cls)) return 2;
    HWND message = CreateWindowW(class_name, NULL, WS_POPUP, 0, 0, 100, 100, NULL, NULL, cls.hInstance, NULL);
    if (!message) return 2;
    if (GetAwarenessFromDpiAwarenessContext(GetWindowDpiAwarenessContext(message)) != window_expected) return 1;
    SetLastError(0);
    BOOL set = SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    DWORD error = GetLastError();
    DPI_AWARENESS_CONTEXT child = (DPI_AWARENESS_CONTEXT)SendMessageW(message, WM_APP, 0, 0);
    DestroyWindow(message);

    BOOL window_matches = GetAwarenessFromDpiAwarenessContext(child) == window_expected;
    BOOL passed = (!!set == !legacy && (set || error == ERROR_ACCESS_DENIED) && window_matches &&
                   AreDpiAwarenessContextsEqual(GetThreadDpiAwarenessContext(),
                                                set ? DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 : expected));
    printf("process_set=%d error=%lu window_matches=%d passed=%d\n", set, error, window_matches, passed);
    return !passed;
}
