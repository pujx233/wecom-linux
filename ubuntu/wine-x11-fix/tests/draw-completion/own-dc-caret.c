/* Exercise completion ownership through nested Win32 caret and erase APIs. */
#define UNICODE
#include <windows.h>
#include <stdio.h>
#include <string.h>

static HWND window, rebind_window, source_window;
static HDC held, erase_dc;
static BOOL track_erase, erase_dc_matches, paint_erase, erase_drawn, destroy_erase, same_dc_reused;
static BOOL check_erase_release, erase_dc_released;
static UINT erase_calls;

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
    POINT erase_point = {10, 10};
    ClientToScreen(window, &point);
    ClientToScreen(window, &erase_point);
    printf("{\"phase\":\"%s\",\"point\":[%ld,%ld],\"erase_calls\":%u,"
           "\"erase_dc_matches\":%s,\"erase_drawn\":%s,\"same_dc_reused\":%s,\"erase_point\":[%ld,%ld],"
           "\"erase_dc_released\":%s}\n",
           phase, point.x, point.y, erase_calls, erase_dc_matches ? "true" : "false",
           erase_drawn ? "true" : "false", same_dc_reused ? "true" : "false", erase_point.x, erase_point.y,
           erase_dc_released ? "true" : "false");
    fflush(stdout);
}

static BOOL acquire_same_dc(HDC previous)
{
    HDC borrowed[64];
    UINT count = 0;
    /* Retain other cache entries until the callback's exact DC is reused. */
    while (count < sizeof(borrowed) / sizeof(borrowed[0]))
    {
        held = GetDC(window);
        if (held == previous) break;
        borrowed[count++] = held;
    }
    same_dc_reused = held == previous;
    while (count) ReleaseDC(window, borrowed[--count]);
    return same_dc_reused;
}

static LRESULT CALLBACK proc(HWND hwnd, UINT message, WPARAM wp, LPARAM lp)
{
    if (message == WM_ERASEBKGND && track_erase)
    {
        erase_calls++;
        if (check_erase_release)
        {
            erase_dc = (HDC)wp;
            return 1;
        }
        if (rebind_window)
        {
            if (destroy_erase && !DestroyWindow(hwnd)) ExitProcess(11);
            window = rebind_window;
            if (!acquire_same_dc((HDC)wp)) ExitProcess(13);
            fill(held, RGB(64, 96, 192));
            return 1; /* The new window's DC remains held after the old callback returns. */
        }
        erase_dc_matches &= (HDC)wp == held;
        if (paint_erase)
        {
            RECT rect = {0, 0, 32, 32};
            HBRUSH brush = CreateSolidBrush(RGB(192, 64, 48));
            erase_drawn = FillRect((HDC)wp, &rect, brush) && GetPixel((HDC)wp, 10, 10) == RGB(192, 64, 48);
            DeleteObject(brush);
        }
        return 1;
    }
    if (message == WM_PAINT || message == WM_ERASEBKGND) return 0;
    return DefWindowProcW(hwnd, message, wp, lp);
}

static BOOL reset_window(UINT style, int x)
{
    PAINTSTRUCT paint;
    if (window) { DestroyCaret(); DestroyWindow(window); }
    window = CreateWindowExW(WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
        style == CS_CLASSDC ? L"ClassDcCaretCompletion" : style ? L"OwnDcCaretCompletion" : L"CachedDcCaretCompletion",
        L"DC drawing completion", WS_POPUP, x, 160, 320, 240, NULL, NULL, NULL, NULL);
    if (!window) return FALSE;
    ShowWindow(window, SW_SHOWNOACTIVATE);
    pump();
    InvalidateRect(window, NULL, FALSE);
    BeginPaint(window, &paint);
    fill(paint.hdc, RGB(48, 176, 96));
    EndPaint(window, &paint);
    pump();
    return TRUE;
}

int main(void)
{
    WNDCLASSW cls = {.style = CS_OWNDC, .lpfnWndProc = proc, .lpszClassName = L"OwnDcCaretCompletion"};
    char command[64], guard[8];
    if (!GetEnvironmentVariableA("WECOM_DC_FIXTURE", guard, sizeof(guard)) || strcmp(guard, "1")) return 2;
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    if (!RegisterClassW(&cls)) return 3;
    cls.style = 0;
    cls.lpszClassName = L"CachedDcCaretCompletion";
    if (!RegisterClassW(&cls)) return 3;
    cls.style = CS_CLASSDC;
    cls.lpszClassName = L"ClassDcCaretCompletion";
    if (!RegisterClassW(&cls)) return 3;
    while (fgets(command, sizeof(command), stdin))
    {
        command[strcspn(command, "\r\n")] = 0;
        if (!strcmp(command, "quit")) break;
        if (!strcmp(command, "reset") || !strcmp(command, "reset-cache") || !strcmp(command, "reset-class"))
        {
            erase_calls = 0;
            erase_dc_matches = TRUE;
            erase_drawn = FALSE;
            same_dc_reused = FALSE;
            erase_dc = NULL;
            erase_dc_released = FALSE;
            if (!reset_window(!strcmp(command, "reset-class") ? CS_CLASSDC :
                              !strcmp(command, "reset-cache") ? 0 : CS_OWNDC, 200)) return 4;
        }
        else if (!strncmp(command, "update-", 7))
        {
            BOOL shortened = strstr(command, "-short") != NULL;
            HWND target = shortened ? (HWND)(ULONG_PTR)LOWORD(window) : window;
            if (shortened && target == window) return 14;
            InvalidateRect(window, NULL, TRUE);
            track_erase = check_erase_release = TRUE;
            if (!strncmp(command, "update-rect-", 12))
            {
                if (!GetUpdateRect(target, NULL, TRUE)) return 15;
            }
            else
            {
                HRGN region = CreateRectRgn(0, 0, 0, 0);
                if (GetUpdateRgn(target, region, TRUE) == ERROR) return 15;
                DeleteObject(region);
            }
            track_erase = check_erase_release = FALSE;
            erase_dc_released = erase_dc && !WindowFromDC(erase_dc);
            ValidateRect(window, NULL);
            pump();
        }
        else if (!strcmp(command, "prepare-rebind-cache") || !strcmp(command, "prepare-rebind-class"))
        {
            source_window = window;
            window = NULL;
            if (!reset_window(!strcmp(command, "prepare-rebind-cache") ? 0 : CS_CLASSDC, 700)) return 4;
        }
        else if (!strcmp(command, "erase-rebind-cache") || !strcmp(command, "erase-rebind-class"))
        {
            BOOL cached = !strcmp(command, "erase-rebind-cache");
            SetWindowPos(window, NULL, 700, 160, 440, 320, SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOCOPYBITS);
            ValidateRect(window, NULL);
            pump();
            rebind_window = window;
            window = source_window;
            track_erase = TRUE;
            destroy_erase = cached;
            RedrawWindow(source_window, NULL, NULL, RDW_INVALIDATE | RDW_ERASE | RDW_ERASENOW);
            track_erase = destroy_erase = FALSE;
            rebind_window = NULL;
            if (erase_calls != 1 || !same_dc_reused) return 12;
            if (!cached) DestroyWindow(source_window);
            source_window = NULL;
            pump();
        }
        else if (!strcmp(command, "precreated") || !strcmp(command, "created-during") ||
                 !strcmp(command, "caret-only") || !strcmp(command, "readback-only") ||
                 !strcmp(command, "erase-now") || !strcmp(command, "erase-now-only") ||
                 !strcmp(command, "erase-paint") || !strcmp(command, "erase-paint-only"))
        {
            BOOL create_during = !strcmp(command, "created-during");
            BOOL erase = !strncmp(command, "erase-", 6);
            BOOL draw = !strcmp(command, "precreated") || create_during ||
                        !strcmp(command, "erase-now") || !strcmp(command, "erase-paint");
            if (!create_during && !erase)
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
            if (erase)
            {
                paint_erase = !strncmp(command, "erase-paint", 11);
                track_erase = TRUE;
                if (!RedrawWindow(window, NULL, NULL, RDW_INVALIDATE | RDW_ERASE | RDW_ERASENOW)) return 10;
                track_erase = FALSE;
                ValidateRect(window, NULL);
            }
            else if (strcmp(command, "readback-only") && !ShowCaret(window)) return 8;
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
