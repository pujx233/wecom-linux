#define _WIN32_WINNT 0x0a00
#include <windows.h>
#include <stdio.h>
#include <string.h>

static RECT monitors[2];
static unsigned int count, failures;
static BOOL handshake, display_change, host_reply;

static BOOL CALLBACK add_monitor(HMONITOR monitor, HDC dc, RECT *rect, LPARAM unused)
{
    (void)monitor; (void)dc; (void)unused;
    if (count < 2) monitors[count++] = *rect;
    return TRUE;
}

static LRESULT CALLBACK procedure(HWND window, UINT message, WPARAM wparam, LPARAM lparam)
{
    if (message == WM_PAINT)
    {
        PAINTSTRUCT paint;
        HDC dc = BeginPaint(window, &paint);
        RECT rect;
        GetClientRect(window, &rect);
        FillRect(dc, &rect, GetStockObject(BLACK_BRUSH));
        EndPaint(window, &paint);
        return 0;
    }
    return DefWindowProcA(window, message, wparam, lparam);
}

static void settle(void)
{
    MSG message;
    ULONGLONG until = GetTickCount64() + 500;
    do
    {
        while (PeekMessageA(&message, NULL, 0, 0, PM_REMOVE))
        {
            TranslateMessage(&message);
            DispatchMessageA(&message);
        }
        Sleep(5);
    } while (GetTickCount64() < until);
}

static void show(HWND window, const RECT *target, unsigned int index, unsigned int round)
{
    RECT actual;
    SetWindowPos(window, HWND_TOPMOST, target->left, target->top,
                 target->right - target->left, target->bottom - target->top, 0);
    ShowWindow(window, SW_SHOW);
    settle();
    GetWindowRect(window, &actual);
    if (host_reply && !index && !round)
    {
        printf("{\"phase\":\"wm-paused\",\"xid\":%lu,\"origin\":[%d,%d],"
               "\"expected\":[%ld,%ld,%ld,%ld],\"actual\":[%ld,%ld,%ld,%ld]}\n",
               (unsigned long)(ULONG_PTR)GetPropA(window, "__wine_x11_whole_window"),
               GetSystemMetrics(SM_XVIRTUALSCREEN), GetSystemMetrics(SM_YVIRTUALSCREEN),
               target->left, target->top, target->right, target->bottom,
               actual.left, actual.top, actual.right, actual.bottom);
        fflush(stdout);
        if (getchar() == EOF) ExitProcess(4);
        settle();
        GetWindowRect(window, &actual);
    }
    BOOL passed = EqualRect(target, &actual);
    failures += !passed;
    printf("{\"case\":%u,\"round\":%u,\"xid\":%lu,\"origin\":[%d,%d],\"expected\":[%ld,%ld,%ld,%ld],"
           "\"actual\":[%ld,%ld,%ld,%ld],\"passed\":%s}\n", index, round,
           (unsigned long)(ULONG_PTR)GetPropA(window, "__wine_x11_whole_window"),
           GetSystemMetrics(SM_XVIRTUALSCREEN), GetSystemMetrics(SM_YVIRTUALSCREEN),
           target->left, target->top, target->right, target->bottom,
           actual.left, actual.top, actual.right, actual.bottom, passed ? "true" : "false");
    fflush(stdout);
    if (handshake && getchar() == EOF) ExitProcess(4);
    ShowWindow(window, SW_HIDE);
    settle();
}

int main(int argc, char **argv)
{
    WNDCLASSA cls = {.lpfnWndProc = procedure, .hInstance = GetModuleHandleA(NULL),
                    .lpszClassName = "FullscreenMapRegression"};
    RECT targets[3];
    unsigned int i, round;

    display_change = argc == 2 && !strcmp(argv[1], "--display-change");
    host_reply = argc == 2 && !strcmp(argv[1], "--host-reply");
    handshake = display_change || host_reply || (argc == 2 && !strcmp(argv[1], "--handshake"));
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    RegisterClassA(&cls);
    for (i = 0; i < (display_change ? 4 : 3); ++i)
    {
        count = 0;
        EnumDisplayMonitors(NULL, NULL, add_monitor, 0);
        if (count != 2) return 2;
        UnionRect(&targets[0], &monitors[0], &monitors[1]);
        targets[1] = monitors[0];
        targets[2] = monitors[1];
        HWND window = CreateWindowExA(WS_EX_TOOLWINDOW, cls.lpszClassName, "Fullscreen map regression",
                                       WS_POPUP | WS_CLIPCHILDREN | WS_CLIPSIBLINGS,
                                       0, 0, 600, 850, NULL, NULL, cls.hInstance, NULL);
        if (!window) return 3;
        for (round = 0; round < 3; ++round)
            show(window, &targets[display_change ? round : round == 2 ? (i + 1) % 3 : i], i, round);
        DestroyWindow(window);
    }
    return failures != 0;
}
