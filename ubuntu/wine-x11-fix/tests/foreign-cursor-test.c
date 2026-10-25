#include <windows.h>
#include <stdio.h>
#include <stdlib.h>

static BOOL foreign;

static LRESULT CALLBACK window_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam)
{
    if (message == WM_SETCURSOR && LOWORD(lparam) == HTCLIENT) {
        POINT point;
        GetCursorPos(&point);
        ScreenToClient(window, &point);
        SetCursor(LoadCursorA(NULL, foreign ? (point.x < 100 ? IDC_IBEAM : IDC_HAND) : IDC_ARROW));
        return TRUE;
    }
    return DefWindowProcA(window, message, wparam, lparam);
}

int main(int argc, char **argv)
{
    WNDCLASSA cls = {.lpfnWndProc = window_proc, .hInstance = GetModuleHandleA(NULL),
                    .hbrBackground = (HBRUSH)(COLOR_WINDOW + 1), .lpszClassName = "ForeignCursorTest"};
    HWND window;
    PROCESS_INFORMATION process = {0};
    STARTUPINFOA startup = {.cb = sizeof(startup)};
    char exe[MAX_PATH], command[MAX_PATH + 80];
    DWORD end;
    MSG message;

    SetProcessDPIAware();
    setvbuf(stdout, NULL, _IONBF, 0);
    foreign = argc == 2;
    if (!RegisterClassA(&cls)) return 1;
    window = CreateWindowExA(0, cls.lpszClassName, "Cursor regression",
                             (foreign ? WS_CHILD : WS_POPUP) | WS_VISIBLE,
                             foreign ? 20 : 10, foreign ? 20 : 10, foreign ? 200 : 400,
                             foreign ? 200 : 300,
                             foreign ? (HWND)(ULONG_PTR)strtoul(argv[1], NULL, 0) : NULL,
                             NULL, cls.hInstance, NULL);
    if (!window) return 2;
    if (!foreign) {
        GetModuleFileNameA(NULL, exe, sizeof(exe));
        snprintf(command, sizeof(command), "\"%s\" 0x%lx", exe, (unsigned long)window);
        if (!CreateProcessA(exe, command, NULL, NULL, FALSE, 0, NULL, NULL, &startup, &process)) return 3;
        printf("{\"xid\":%lu}\n", (unsigned long)GetPropA(window, "__wine_x11_whole_window"));
    }
    end = GetTickCount() + 15000;
    while ((LONG)(GetTickCount() - end) < 0) {
        while (PeekMessageA(&message, NULL, 0, 0, PM_REMOVE)) DispatchMessageA(&message);
        MsgWaitForMultipleObjectsEx(0, NULL, 10, QS_ALLINPUT, MWMO_INPUTAVAILABLE);
    }
    if (process.hProcess) {
        TerminateProcess(process.hProcess, 0);
        WaitForSingleObject(process.hProcess, 5000);
        CloseHandle(process.hThread);
        CloseHandle(process.hProcess);
    }
    DestroyWindow(window);
    return 0;
}
