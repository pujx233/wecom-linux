/* Exercise completion ownership through the real Win32 caret APIs. */
#define UNICODE
#include <windows.h>
#include <stdio.h>
#include <string.h>

static HWND window;
static HDC held;

static void fill(HDC dc, COLORREF color)
{
    RECT rect;
    HBRUSH brush = CreateSolidBrush(color);
    GetClientRect(window, &rect);
    FillRect(dc, &rect, brush);
    DeleteObject(brush);
}

static void pump(void)
{
    MSG message;
    DWORD start = GetTickCount();
    do
    {
        /* Process native map/configure acknowledgements, but never rescue a
         * missing direct-DC completion through an unrelated WM_PAINT. */
        while (PeekMessageW(&message, NULL, 0, 0, PM_REMOVE))
        {
            if (message.message == WM_PAINT) ValidateRect(message.hwnd, NULL);
            else if (message.message != WM_TIMER) DispatchMessageW(&message);
        }
        Sleep(5);
    } while (GetTickCount() - start < 250);
}

static void report(const char *phase)
{
    POINT point = {150, 100};
    ClientToScreen(window, &point);
    printf("{\"phase\":\"%s\",\"point\":[%ld,%ld]}\n", phase, point.x, point.y);
    fflush(stdout);
}

static LRESULT CALLBACK proc(HWND hwnd, UINT message, WPARAM wp, LPARAM lp)
{
    if (message == WM_PAINT || message == WM_ERASEBKGND) return 0;
    return DefWindowProcW(hwnd, message, wp, lp);
}

int main(void)
{
    WNDCLASSW cls = {.style = CS_OWNDC, .lpfnWndProc = proc, .lpszClassName = L"OwnDcCaretCompletion"};
    char command[64], guard[8];
    if (!GetEnvironmentVariableA("WECOM_DC_FIXTURE", guard, sizeof(guard)) || strcmp(guard, "1")) return 2;
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    if (!RegisterClassW(&cls)) return 3;
    while (fgets(command, sizeof(command), stdin))
    {
        command[strcspn(command, "\r\n")] = 0;
        if (!strcmp(command, "quit")) break;
        if (!strcmp(command, "reset"))
        {
            if (window) { DestroyCaret(); DestroyWindow(window); }
            window = CreateWindowExW(WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, cls.lpszClassName,
                L"Own DC caret completion", WS_POPUP, 200, 160, 320, 240, NULL, NULL, NULL, NULL);
            if (!window) return 4;
            ShowWindow(window, SW_SHOWNOACTIVATE);
            pump();
            PAINTSTRUCT paint;
            InvalidateRect(window, NULL, FALSE);
            BeginPaint(window, &paint);
            fill(paint.hdc, RGB(48, 176, 96));
            EndPaint(window, &paint);
            pump();
        }
        else if (!strcmp(command, "precreated") || !strcmp(command, "created-during") ||
                 !strcmp(command, "caret-only") || !strcmp(command, "readback-only"))
        {
            BOOL create_during = !strcmp(command, "created-during");
            BOOL draw = !strcmp(command, "precreated") || create_during;
            if (!create_during)
            {
                if (!CreateCaret(window, NULL, 2, 30)) return 5;
                SetCaretPos(20, 20);
            }
            SetWindowPos(window, NULL, 200, 160, 440, 320, SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOCOPYBITS);
            ValidateRect(window, NULL); /* replacement surfaces must ignore this as completion */
            pump();
            held = GetDC(window);
            if (draw) fill(held, RGB(64, 96, 192));
            if (create_during)
            {
                if (!CreateCaret(window, NULL, 2, 30)) return 6;
                SetCaretPos(20, 20);
            }
            if (strcmp(command, "readback-only") && !ShowCaret(window)) return 8;
            pump();
        }
        else if (!strcmp(command, "release"))
        {
            /* Readback must execute successfully without counting as a new draw. */
            if (GetPixel(held, 150, 100) == CLR_INVALID) return 9;
            ReleaseDC(window, held);
            held = NULL;
            pump();
        }
        else if (!strcmp(command, "complete"))
        {
            HDC dc = GetDC(window);
            fill(dc, RGB(64, 96, 192));
            ReleaseDC(window, dc);
            pump();
        }
        else return 7;
        report(command);
    }
    if (window) DestroyWindow(window);
    return 0;
}
