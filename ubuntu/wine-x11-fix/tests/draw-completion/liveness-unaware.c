#ifndef UNICODE
#define UNICODE
#endif
#include <windows.h>
#include <stdio.h>
#include <string.h>

#define WM_CONTENT (WM_APP + 1)

static HWND control_window, test_window;
static const WCHAR *control_path;
static unsigned sequence, current_case, paint_count;
static BOOL content, boundary, inside_paint, pure_dc, dc_pump, busy_end;
static HANDLE dc_gate;

static void record(const char *event)
{
    FILETIME time;
    ULARGE_INTEGER value;
    RECT rect = {0};
    GetSystemTimePreciseAsFileTime(&time);
    value.LowPart = time.dwLowDateTime;
    value.HighPart = time.dwHighDateTime;
    if (test_window) GetWindowRect(test_window, &rect);
    printf("{\"event\":\"%s\",\"time_us\":%llu,\"sequence\":%u,\"case\":%u,\"hwnd\":%llu,"
        "\"visible\":%s,\"pending_paint\":%s,\"paint_count\":%u,\"content\":%s,"
        "\"rect\":[%ld,%ld,%ld,%ld]}\n", event,
        (value.QuadPart - 116444736000000000ULL) / 10, sequence, current_case,
        (unsigned long long)(ULONG_PTR)test_window, IsWindowVisible(test_window) ? "true" : "false",
        GetUpdateRect(test_window, NULL, FALSE) ? "true" : "false", paint_count,
        content ? "true" : "false", rect.left, rect.top, rect.right, rect.bottom);
    fflush(stdout);
}

static void busy_record(const char *event)
{
    FILETIME time;
    ULARGE_INTEGER value;
    GetSystemTimePreciseAsFileTime(&time);
    value.LowPart = time.dwLowDateTime;
    value.HighPart = time.dwHighDateTime;
    printf("{\"event\":\"%s\",\"time_us\":%llu,\"sequence\":%u,\"case\":%u}\n",
        event, (value.QuadPart - 116444736000000000ULL) / 10, sequence, current_case);
    fflush(stdout);
}

static void draw(HDC dc, RECT rect)
{
    HBRUSH brush = CreateSolidBrush(content ? RGB(48, 176, 96) : RGB(255, 255, 255));
    FillRect(dc, &rect, brush);
    DeleteObject(brush);
    if (content)
    {
        rect.right = rect.left + 48;
        brush = CreateSolidBrush(RGB(64, 96, 192));
        FillRect(dc, &rect, brush);
        DeleteObject(brush);
    }
}

static LRESULT CALLBACK test_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam)
{
    if (boundary && current_case == 1 && inside_paint &&
        (message == WM_NCPAINT || message == WM_ERASEBKGND))
    {
        ValidateRect(window, NULL);
        record(message == WM_NCPAINT ? "validate-in-ncpaint" : "validate-in-erase");
        return message == WM_ERASEBKGND;
    }
    if (message == WM_PAINT)
    {
        PAINTSTRUCT paint;
        RECT rect;
        record("paint-enter");
        inside_paint = TRUE;
        if (boundary && current_case == 1)
        {
            RedrawWindow(window, NULL, NULL, RDW_INVALIDATE | RDW_ERASE | RDW_FRAME);
            BeginPaint(window, NULL);
            record("null-begin-returned");
            RedrawWindow(window, NULL, NULL, RDW_INVALIDATE | RDW_ERASE | RDW_FRAME);
        }
        BeginPaint(window, &paint);
        record("begin-paint-returned");
        GetClientRect(window, &rect);
        draw(paint.hdc, rect);
        record("draw-complete");
        EndPaint(window, &paint);
        if (busy_end && current_case == 1 && !paint_count)
        {
            busy_record("busy-before-sleep");
            Sleep(1500); /* No User32/GDI call after EndPaint until this returns. */
            busy_record("busy-after-sleep");
        }
        inside_paint = FALSE;
        paint_count++;
        record("end-paint-returned");
        return 0;
    }
    if (message == WM_CONTENT)
    {
        content = TRUE;
        record("async-content-message");
        InvalidateRect(window, NULL, FALSE);
        return 0;
    }
    return DefWindowProcW(window, message, wparam, lparam);
}

static void command(void)
{
    FILE *file = _wfopen(control_path, L"r");
    unsigned next_sequence, next_case;
    char action[32];
    if (!file) return;
    if (fscanf(file, "%u %31s %u", &next_sequence, action, &next_case) != 3 || next_sequence <= sequence)
    {
        fclose(file);
        return;
    }
    fclose(file);
    sequence = next_sequence;
    if (!strcmp(action, "show"))
    {
        WCHAR title[64];
        if (test_window) DestroyWindow(test_window);
        current_case = next_case;
        content = current_case == 1 || current_case == 4;
        paint_count = 0;
        swprintf(title, 64, L"First frame case %u", current_case);
        test_window = CreateWindowExW(WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW, L"FirstFrameFixture", title,
            WS_POPUP | WS_CLIPSIBLINGS | WS_CLIPCHILDREN, 0, 0, 0, 0, NULL, NULL, NULL, NULL);
        record("created-zero-hidden");
        SetWindowPos(test_window, NULL, 200, 160, 320, 240,
            SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOSENDCHANGING);
        record("resized-hidden");
        if (current_case >= 3 && !(pure_dc && current_case == 4)) ValidateRect(test_window, NULL);
        record("before-show");
        ShowWindow(test_window, SW_SHOWNOACTIVATE);
        record("after-show");
        if (current_case >= 3 && !(pure_dc && current_case == 4))
        {
            ValidateRect(test_window, NULL);
            record("validated-no-paint");
        }
        if (current_case == 4)
        {
            RECT rect;
            HDC dc = GetDC(test_window);
            record("direct-getdc");
            GetClientRect(test_window, &rect);
            draw(dc, rect);
            ReleaseDC(test_window, dc);
            record("direct-releasedc");
            if (pure_dc)
            {
                record("direct-gate-enter");
                if (dc_pump)
                {
                    DWORD start = GetTickCount();
                    MSG queued;
                    while (WaitForSingleObject(dc_gate, 10) == WAIT_TIMEOUT && GetTickCount() - start < 10000)
                    {
                        while (PeekMessageW(&queued, NULL, 0, WM_PAINT - 1, PM_REMOVE) ||
                            PeekMessageW(&queued, NULL, WM_PAINT + 1, 0xffff, PM_REMOVE))
                        {
                            if (queued.message != WM_TIMER) DispatchMessageW(&queued);
                        }
                    }
                }
                else WaitForSingleObject(dc_gate, 10000);
                record("direct-gate-returned");
            }
        }
    }
    else if (!strcmp(action, "content")) PostMessageW(test_window, WM_CONTENT, 0, 0);
    else if (!strcmp(action, "hide"))
    {
        DestroyWindow(test_window);
        test_window = NULL;
        record("destroyed");
    }
    else if (!strcmp(action, "exit")) DestroyWindow(control_window);
    record("command-complete");
}

static LRESULT CALLBACK control_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam)
{
    if (message == WM_TIMER)
    {
        if (wparam == 1) command();
        else DestroyWindow(window);
        return 0;
    }
    if (message == WM_DESTROY)
    {
        if (test_window) DestroyWindow(test_window);
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(window, message, wparam, lparam);
}

int wmain(int argc, WCHAR **argv)
{
    WNDCLASSW cls = {.style = CS_HREDRAW | CS_VREDRAW, .lpfnWndProc = test_proc,
        .hbrBackground = (HBRUSH)(COLOR_WINDOW + 1), .lpszClassName = L"FirstFrameFixture"};
    MSG message;
    if (argc == 2 && !wcscmp(argv[1], L"--release-dc"))
    {
        HANDLE gate = OpenEventW(EVENT_MODIFY_STATE, FALSE, L"FirstPresentDirectGate");
        if (!gate) return 3;
        SetEvent(gate);
        CloseHandle(gate);
        return 0;
    }
    if (argc != 3 || wcscmp(argv[1], L"--control-file")) return 2;
    control_path = argv[2];
    busy_end = GetEnvironmentVariableW(L"QA_FIRST_PRESENT_BUSY_END", NULL, 0) > 0;
    boundary = GetEnvironmentVariableW(L"QA_FIRST_PRESENT_BOUNDARY", NULL, 0) > 0;
    pure_dc = GetEnvironmentVariableW(L"QA_FIRST_PRESENT_PURE_DC", NULL, 0) > 0;
    dc_pump = GetEnvironmentVariableW(L"QA_FIRST_PRESENT_DC_PUMP", NULL, 0) > 0;
    if (pure_dc) dc_gate = CreateEventW(NULL, TRUE, FALSE, L"FirstPresentDirectGate");
    SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_UNAWARE);
    if (!RegisterClassW(&cls)) return 1;
    cls.style = 0;
    cls.lpfnWndProc = control_proc;
    cls.lpszClassName = L"FirstFrameControl";
    if (!RegisterClassW(&cls)) return 1;
    control_window = CreateWindowW(cls.lpszClassName, L"First frame control", 0,
        0, 0, 0, 0, HWND_MESSAGE, NULL, NULL, NULL);
    if (!control_window) return 1;
    SetTimer(control_window, 1, 10, NULL);
    SetTimer(control_window, 2, 45000, NULL);
    record("ready");
    while (GetMessageW(&message, NULL, 0, 0) > 0)
    {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    record("exit");
    if (dc_gate) CloseHandle(dc_gate);
    return 0;
}
