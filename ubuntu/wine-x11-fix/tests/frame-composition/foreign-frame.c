#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>
#include <string.h>

static HWND main_window, child;
static HANDLE redraw, paint_done;
static BOOL armed;
static unsigned int sequence;

static void draw(HWND hwnd)
{
    HDC dc = GetDC(hwnd);
    COLORREF pixel;
    RECT rect;
    HBRUSH brush = CreateSolidBrush(sequence & 1 ? RGB(255, 0, 0) : RGB(0, 0, 255));
    GetClientRect(hwnd, &rect);
    FillRect(dc, &rect, brush);
    DeleteObject(brush);
    pixel = GetPixel(dc, 100, 100);
    ReleaseDC(hwnd, dc);
    GdiFlush();
    printf("{\"event\":\"draw\",\"sequence\":%u,\"tick\":%lu,\"pixel\":%lu}\n", sequence, GetTickCount(), pixel);
    fflush(stdout);
    if (paint_done) SetEvent(paint_done);
}

static LRESULT CALLBACK proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    if (msg == WM_NCCREATE)
        SetWindowLongPtrA(hwnd, GWLP_USERDATA, (LONG_PTR)((CREATESTRUCTA *)lp)->lpCreateParams);
    if (msg == WM_NCCALCSIZE) return 0;
    if (msg == WM_PAINT)
    {
        PAINTSTRUCT ps;
        HDC dc = BeginPaint(hwnd, &ps);
        HBRUSH brush = CreateSolidBrush(GetWindowLongPtrA(hwnd, GWLP_USERDATA) ? RGB(0, 255, 0) : RGB(128, 128, 128));
        FillRect(dc, &ps.rcPaint, brush);
        DeleteObject(brush);
        EndPaint(hwnd, &ps);
        return 0;
    }
    if (hwnd == main_window && msg == WM_APP + 1)
    {
        armed = TRUE;
        puts("{\"event\":\"armed\"}"); fflush(stdout);
        return 0;
    }
    if (hwnd == main_window && msg == WM_WINDOWPOSCHANGED && armed)
    {
        MSG nested;
        DWORD deadline;
        armed = FALSE;
        DefWindowProcW(hwnd, msg, wp, lp);
        InvalidateRect(hwnd, NULL, FALSE);
        UpdateWindow(hwnd);
        ResetEvent(paint_done);
        SetEvent(redraw);
        if (WaitForSingleObject(paint_done, 3000) != WAIT_OBJECT_0) ExitProcess(3);
        deadline = GetTickCount() + 250;
        do {
            while (PeekMessageW(&nested, NULL, 0, 0, PM_REMOVE))
            { TranslateMessage(&nested); DispatchMessageW(&nested); }
            Sleep(1);
        } while ((LONG)(GetTickCount() - deadline) < 0);
        puts("{\"event\":\"nested\"}"); fflush(stdout);
        return 0;
    }
    if (msg == WM_DESTROY) { PostQuitMessage(0); return 0; }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

static DWORD WINAPI commands(void *unused)
{
    char line[64];
    while (fgets(line, sizeof(line), stdin))
    {
        if (line[0] == 'a') PostMessageW(main_window, WM_APP + 1, 0, 0);
        else if (line[0] == 'd') SetEvent(redraw);
        else { PostMessageW(main_window, WM_CLOSE, 0, 0); break; }
    }
    (void)unused;
    return 0;
}

int main(int argc, char **argv)
{
    WNDCLASSA wc = {0};
    MSG msg;
    char event_name[80];
    SetProcessDPIAware();
    wc.lpfnWndProc = proc;
    wc.hInstance = GetModuleHandleA(NULL);
    wc.lpszClassName = "ForeignFrameRegression";
    RegisterClassA(&wc);
    if (argc > 1)
    {
        HWND parent = (HWND)(ULONG_PTR)strtoull(argv[1], NULL, 16);
        sprintf(event_name, "Local\\ForeignFrame-%lx", (unsigned long)(ULONG_PTR)parent);
        redraw = OpenEventA(SYNCHRONIZE, FALSE, event_name);
        strcat(event_name, "-done");
        paint_done = OpenEventA(EVENT_MODIFY_STATE, FALSE, event_name);
        child = CreateWindowExA(0, wc.lpszClassName, "foreign renderer", WS_CHILD | WS_VISIBLE,
                                20, 80, 600, 300, parent, NULL, wc.hInstance, NULL);
        UpdateWindow(child);
        draw(child);
        for (;;)
        {
            DWORD result = MsgWaitForMultipleObjects(1, &redraw, FALSE, INFINITE, QS_ALLINPUT);
            if (result == WAIT_FAILED) return 2;
            if (result == WAIT_OBJECT_0) { ++sequence; draw(child); }
            while (PeekMessageA(&msg, NULL, 0, 0, PM_REMOVE))
            {
                if (msg.message == WM_QUIT) return 0;
                TranslateMessage(&msg); DispatchMessageA(&msg);
            }
            if (!IsWindow(parent)) return 0;
        }
        return 0;
    }
    main_window = CreateWindowExA(0, wc.lpszClassName, "foreign rendering regression", WS_POPUP | WS_THICKFRAME,
                                  200, 100, 800, 600, NULL, NULL, wc.hInstance, NULL);
    ShowWindow(main_window, SW_SHOW);
    UpdateWindow(main_window);
    child = CreateWindowExA(WS_EX_LAYERED | WS_EX_TOOLWINDOW, wc.lpszClassName, "decoration",
                            WS_POPUP | WS_SYSMENU, 200, 100, 800, 40, main_window, NULL, wc.hInstance, (void *)1);
    SetLayeredWindowAttributes(child, 0, 255, LWA_ALPHA);
    ShowWindow(child, SW_SHOWNOACTIVATE);
    UpdateWindow(child);
    sprintf(event_name, "Local\\ForeignFrame-%lx", (unsigned long)(ULONG_PTR)main_window);
    redraw = CreateEventA(NULL, FALSE, FALSE, event_name);
    strcat(event_name, "-done");
    paint_done = CreateEventA(NULL, FALSE, FALSE, event_name);
    {
        STARTUPINFOW startup = {0};
        PROCESS_INFORMATION process;
        WCHAR exe[MAX_PATH], command[2 * MAX_PATH];
        GetModuleFileNameW(NULL, exe, MAX_PATH);
        startup.cb = sizeof(startup);
        swprintf(command, 2 * MAX_PATH, L"\"%ls\" %lx", exe, (unsigned long)(ULONG_PTR)main_window);
        if (!CreateProcessW(NULL, command, NULL, NULL, TRUE, 0, NULL, NULL, &startup, &process)) return 2;
        CloseHandle(process.hThread); CloseHandle(process.hProcess);
    }
    printf("{\"event\":\"ready\",\"body\":%lu,\"frame\":%lu}\n",
           (unsigned long)(ULONG_PTR)GetPropA(main_window, "__wine_x11_whole_window"),
           (unsigned long)(ULONG_PTR)GetPropA(main_window, "__wine_x11_wm_window"));
    fflush(stdout);
    CreateThread(NULL, 0, commands, NULL, 0, NULL);
    while (GetMessageA(&msg, NULL, 0, 0) > 0) { TranslateMessage(&msg); DispatchMessageA(&msg); }
    return 0;
}
