#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static HANDLE ready, draw, done;
static HBRUSH blue, green;
static BOOL child_process;

static void pump(DWORD delay)
{
    DWORD end = GetTickCount() + delay;
    do {
        MSG message;
        while (PeekMessageW(&message, NULL, 0, 0, PM_REMOVE)) DispatchMessageW(&message);
        MsgWaitForMultipleObjectsEx(0, NULL, 1, QS_ALLINPUT, MWMO_INPUTAVAILABLE);
    } while ((LONG)(GetTickCount() - end) < 0);
}

static LRESULT CALLBACK proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam)
{
    if (child_process && message == WM_ERASEBKGND) {
        RECT rect;
        GetClientRect(window, &rect);
        FillRect((HDC)wparam, &rect, green);
        return 1;
    }
    if (message == WM_PAINT) {
        PAINTSTRUCT paint;
        HDC dc = BeginPaint(window, &paint);
        if (!child_process) FillRect(dc, &paint.rcPaint, blue);
        if (!child_process) GetPixel(dc, 5, 5); /* complete the parent paint before native sampling */
        EndPaint(window, &paint);
        return 0;
    }
    return DefWindowProcW(window, message, wparam, lparam);
}

static void paint_child(HWND window)
{
    RECT rect = {0, 0, 180, 100};
    HDC dc = GetDC(window);
    RECT clip, screen;
    int region = GetClipBox(dc, &clip);
    GetWindowRect(window, &screen);
    int filled = FillRect(dc, &rect, green);
    fprintf(stderr, "draw hwnd=%p visible=%d rect=%ld,%ld,%ld,%ld dc=%p "
                    "clip=%d %ld,%ld,%ld,%ld fill=%d pixel=%lx\n",
            window, IsWindowVisible(window), screen.left, screen.top, screen.right, screen.bottom, dc,
            region, clip.left, clip.top, clip.right, clip.bottom, filled, GetPixel(dc, 40, 40));
    ReleaseDC(window, dc);
    GdiFlush();
    pump(100);
}

int main(int argc, char **argv)
{
    SetProcessDPIAware();
    child_process = argc == 2;
    setvbuf(stdout, NULL, _IONBF, 0);
    blue = CreateSolidBrush(RGB(0, 0, 255));
    green = CreateSolidBrush(RGB(0, 255, 0));
    HWND host = argc == 2 ? (HWND)(ULONG_PTR)strtoul(argv[1], NULL, 0) : NULL;
    WNDCLASSW cls = {.lpfnWndProc = proc, .hInstance = GetModuleHandleW(NULL), .lpszClassName = L"ForeignDcTest"};
    RegisterClassW(&cls);
    HWND top = NULL;
    if (!host) {
        top = CreateWindowW(cls.lpszClassName, L"", WS_POPUP | WS_VISIBLE | WS_CLIPCHILDREN,
                            10, 10, 400, 300, NULL, NULL, cls.hInstance, NULL);
        host = CreateWindowW(L"STATIC", L"", WS_CHILD | WS_VISIBLE | WS_CLIPCHILDREN,
                             20, 20, 180, 100, top, NULL, cls.hInstance, NULL);
        pump(100);
    }
    HANDLE *events[] = {&ready, &draw, &done};
    for (int i = 0; i < 3; i++) {
        char name[80];
        snprintf(name, sizeof(name), "Local\\ForeignDcTest-%lx-%d", (unsigned long)host, i);
        *events[i] = CreateEventA(NULL, TRUE, FALSE, name);
    }
    if (argc == 2) {
        HWND child = CreateWindowW(cls.lpszClassName, L"", WS_CHILD | WS_VISIBLE,
                                   0, 0, 180, 100, host, NULL, cls.hInstance, NULL);
        pump(100);
        paint_child(child);
        SetEvent(ready);
        while (WaitForSingleObject(draw, 10) != WAIT_FAILED) {
            pump(1);
            if (WaitForSingleObject(draw, 0) != WAIT_OBJECT_0) continue;
            ResetEvent(draw);
            paint_child(child);
            SetEvent(done);
        }
        return 0;
    }
    char exe[MAX_PATH], command[MAX_PATH + 80];
    GetModuleFileNameA(NULL, exe, sizeof(exe));
    snprintf(command, sizeof(command), "\"%s\" 0x%lx", exe, (unsigned long)host);
    STARTUPINFOA startup = {.cb = sizeof(startup)};
    PROCESS_INFORMATION process;
    if (!CreateProcessA(exe, command, NULL, NULL, FALSE, 0, NULL, NULL, &startup, &process)) return 2;
    while (WaitForSingleObject(ready, 0) != WAIT_OBJECT_0) pump(5);
    printf("{\"stage\":\"visible\",\"xid\":%lu}\n", (unsigned long)GetPropA(top, "__wine_x11_whole_window"));
    while (fgets(command, sizeof(command), stdin)) {
        command[strcspn(command, "\r\n")] = 0;
        if (!strcmp(command, "quit")) break;
        if (!strcmp(command, "expose")) {
            pump(400);
            printf("{\"stage\":\"expose\",\"xid\":%lu}\n",
                   (unsigned long)GetPropA(top, "__wine_x11_whole_window"));
            continue;
        }
        if (!strcmp(command, "hide")) ShowWindow(host, SW_HIDE);
        else if (!strcmp(command, "show")) ShowWindow(host, SW_SHOWNOACTIVATE);
        else if (!strcmp(command, "move")) SetWindowPos(host, NULL, 150, 130, 0, 0,
                                                       SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE);
        else if (strcmp(command, "repaint")) return 3;
        RedrawWindow(top, NULL, NULL, RDW_INVALIDATE | RDW_ERASE | RDW_UPDATENOW);
        ResetEvent(done);
        SetEvent(draw);
        while (WaitForSingleObject(done, 0) != WAIT_OBJECT_0) pump(5);
        if (!strcmp(command, "repaint"))
            RedrawWindow(top, NULL, NULL, RDW_INVALIDATE | RDW_ERASE | RDW_UPDATENOW);
        pump(80);
        printf("{\"stage\":\"%s\",\"xid\":%lu}\n", command,
               (unsigned long)GetPropA(top, "__wine_x11_whole_window"));
    }
    TerminateProcess(process.hProcess, 0);
    WaitForSingleObject(process.hProcess, 5000);
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    DestroyWindow(top);
    for (int i = 0; i < 3; i++) CloseHandle(*events[i]);
    DeleteObject(blue);
    DeleteObject(green);
    return 0;
}
