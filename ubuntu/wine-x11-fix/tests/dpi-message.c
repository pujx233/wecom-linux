#define _WIN32_WINNT 0x0a00
#include <windows.h>
#include <stdio.h>
#include <wchar.h>

static const RECT suggested = {-1100, 37, -140, 677};

static LRESULT CALLBACK receive(HWND window, UINT msg, WPARAM wp, LPARAM lp)
{
    if (msg == WM_DPICHANGED)
    {
        if (!lp || LOWORD(wp) != 144 || HIWORD(wp) != 144 || !EqualRect((const RECT *)lp, &suggested)) return 0;
        SetRectEmpty((RECT *)lp);
        return 1;
    }
    if (msg == WM_TIMER || msg == WM_CLOSE)
    {
        DestroyWindow(window);
        return 0;
    }
    if (msg == WM_DESTROY)
    {
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(window, msg, wp, lp);
}

static int run_receiver(const WCHAR *name)
{
    WNDCLASSW wc = {.lpfnWndProc = receive, .hInstance = GetModuleHandleW(NULL), .lpszClassName = name};
    if (!RegisterClassW(&wc)) return 2;
    HWND window = CreateWindowExW(0, name, NULL, 0, 0, 0, 0, 0, HWND_MESSAGE, NULL, wc.hInstance, NULL);
    if (!window || !SetTimer(window, 1, 10000, NULL)) return 2;
    MSG msg;
    int result;
    while ((result = GetMessageW(&msg, NULL, 0, 0)) > 0) DispatchMessageW(&msg);
    return result < 0 ? 2 : 0;
}

int wmain(int argc, WCHAR **argv)
{
    if (argc == 3 && !wcscmp(argv[1], L"--receive")) return run_receiver(argv[2]);
    if (argc != 2)
    {
        fputs("usage: dpi-message.exe PATH_TO_RECEIVER_EXE\n", stderr);
        return 2;
    }
    WCHAR name[64], command[MAX_PATH + 100];
    swprintf(name, ARRAYSIZE(name), L"WeComTestDpiMessage%lu", GetCurrentProcessId());
    if (swprintf(command, ARRAYSIZE(command), L"\"%ls\" --receive %ls", argv[1], name) < 0) return 2;
    PROCESS_INFORMATION child;
    STARTUPINFOW startup = {.cb = sizeof(startup)};
    if (!CreateProcessW(argv[1], command, NULL, NULL, FALSE, 0, NULL, NULL, &startup, &child)) return 2;
    CloseHandle(child.hThread);
    HWND window = NULL;
    DWORD pid = 0;
    ULONGLONG end = GetTickCount64() + 8000;
    while (GetTickCount64() < end && WaitForSingleObject(child.hProcess, 20) == WAIT_TIMEOUT)
    {
        window = FindWindowExW(HWND_MESSAGE, NULL, name, NULL);
        if (window && GetWindowThreadProcessId(window, &pid) && pid == child.dwProcessId) break;
    }
    int status = 2;
    if (window && pid == child.dwProcessId)
    {
        SetLastError(0);
        BOOL rejected = !PostMessageW(window, WM_DPICHANGED, 0, 0) && GetLastError() == ERROR_MESSAGE_SYNC_ONLY;
        RECT input = suggested;
        DWORD_PTR reply = 0;
        BOOL delivered = rejected && SendMessageTimeoutW(window, WM_DPICHANGED, MAKELONG(144, 144),
                (LPARAM)&input, SMTO_ABORTIFHUNG, 3000, &reply) && reply == 1;
        BOOL input_only = delivered && EqualRect(&input, &suggested);
        printf("async_rejected=%d rect_delivered=%d input_only=%d\n", rejected, delivered, input_only);
        status = input_only ? 0 : 1;
        PostMessageW(window, WM_CLOSE, 0, 0);
    }
    if (WaitForSingleObject(child.hProcess, 11000) != WAIT_OBJECT_0) status = 2;
    CloseHandle(child.hProcess);
    return status;
}
