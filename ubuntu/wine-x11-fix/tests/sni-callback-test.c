#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <stdio.h>
#include <stdlib.h>

static HWND owner;
static unsigned version;

static LRESULT CALLBACK window_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam)
{
    if (message == WM_APP || message == WM_APP + 1)
    {
        POINT point;
        /* Check the driver position after the shared cursor cache expires. */
        if (message == WM_APP + 1) Sleep(120);
        GetCursorPos(&point);
        printf("{\"event\":\"%s\",\"message\":%u,\"cursor\":[%ld,%ld],\"packed\":[%d,%d]}\n",
               message == WM_APP ? "callback" : "outside", version ? LOWORD(lparam) : (unsigned)lparam,
               point.x, point.y, (short)LOWORD(wparam), (short)HIWORD(wparam));
        fflush(stdout);
        if (message == WM_APP) PostMessageA(window, WM_APP + 1, wparam, lparam);
        return 0;
    }
    if (message == WM_DESTROY)
    {
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcA(window, message, wparam, lparam);
}

static DWORD WINAPI read_quit(void *unused)
{
    char command[16];
    (void)unused;
    while (fgets(command, sizeof(command), stdin))
    {
        if (command[0] == 's') PostMessageA(owner, WM_APP + 1, 0, 0);
        else
        {
            PostMessageA(owner, WM_CLOSE, 0, 0);
            break;
        }
    }
    return 0;
}

int main(int argc, char **argv)
{
    WNDCLASSA cls = {.lpfnWndProc = window_proc, .lpszClassName = "WineSniCallbackProbe",
                    .hbrBackground = (HBRUSH)(COLOR_WINDOW + 1)};
    NOTIFYICONDATAA icon = {.cbSize = sizeof(icon), .uID = 1, .uFlags = NIF_ICON | NIF_MESSAGE,
                          .uCallbackMessage = WM_APP};
    MSG message;
    version = argc == 2 ? atoi(argv[1]) : 0;
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    cls.hInstance = GetModuleHandleA(NULL);
    RegisterClassA(&cls);
    owner = CreateWindowExA(0, cls.lpszClassName, "Wine tray callback test", WS_OVERLAPPEDWINDOW,
                            200, 140, 640, 480, NULL, NULL, cls.hInstance, NULL);
    if (!owner) return 1;
    ShowWindow(owner, SW_SHOW);
    icon.hWnd = owner;
    icon.hIcon = LoadIconA(NULL, IDI_APPLICATION);
    if (!Shell_NotifyIconA(NIM_ADD, &icon)) return 2;
    if (version)
    {
        icon.uVersion = NOTIFYICON_VERSION_4;
        if (!Shell_NotifyIconA(NIM_SETVERSION, &icon)) return 3;
    }
    printf("{\"event\":\"ready\",\"version\":%u,\"wm_xid\":%llu}\n", version,
           (unsigned long long)(UINT_PTR)GetPropA(owner, "__wine_x11_wm_window"));
    fflush(stdout);
    CloseHandle(CreateThread(NULL, 0, read_quit, NULL, 0, NULL));
    while (GetMessageA(&message, NULL, 0, 0) > 0)
    {
        TranslateMessage(&message);
        DispatchMessageA(&message);
    }
    Shell_NotifyIconA(NIM_DELETE, &icon);
    return 0;
}
