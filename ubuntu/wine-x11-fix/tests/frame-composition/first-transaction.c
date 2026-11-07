#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <string.h>

static HWND owner, popup, shadow;
static BOOL paint_popup, compact, odd_size;

static LRESULT CALLBACK proc(HWND hwnd, UINT message, WPARAM wp, LPARAM lp)
{
    if (message == WM_NCCALCSIZE || message == WM_ERASEBKGND) return 0;
    if (message == WM_PAINT)
    {
        PAINTSTRUCT paint;
        HBRUSH brush;
        HDC dc;

        if (hwnd == popup && !paint_popup) return 0;
        brush = CreateSolidBrush(hwnd == popup ? RGB(0, 255, 0) :
                                  hwnd == owner ? RGB(96, 96, 96) : compact ? RGB(0, 0, 0) : RGB(0, 0, 255));
        dc = BeginPaint(hwnd, &paint);
        FillRect(dc, &paint.rcPaint, brush);
        DeleteObject(brush);
        EndPaint(hwnd, &paint);
        return 0;
    }
    return DefWindowProcW(hwnd, message, wp, lp);
}

static void pump(void)
{
    MSG message;
    DWORD start = GetTickCount();

    do
    {
        while (PeekMessageW(&message, NULL, 0, WM_PAINT - 1, PM_REMOVE) ||
               PeekMessageW(&message, NULL, WM_PAINT + 1, ~0u, PM_REMOVE))
            DispatchMessageW(&message);
        Sleep(1);
    } while (GetTickCount() - start < 300);
}

static void state(const char *phase)
{
    RECT rect;
    GetWindowRect(popup, &rect);
    printf("{\"phase\":\"%s\",\"rect\":[%ld,%ld,%ld,%ld],\"frame\":%llu,\"body\":%llu}\n", phase,
           rect.left, rect.top, rect.right, rect.bottom,
           (unsigned long long)(UINT_PTR)GetPropW(popup, L"__wine_x11_wm_window"),
           (unsigned long long)(UINT_PTR)GetPropW(popup, L"__wine_x11_whole_window"));
    fflush(stdout);
}

int main(int argc, char **argv)
{
    WNDCLASSW cls = {.lpfnWndProc = proc, .lpszClassName = L"FirstTransactionBody"};
    char command[32];
    int i, width, height;

    for (i = 1; i < argc; i++)
    {
        if (!strcmp(argv[i], "--compact")) compact = TRUE;
        if (!strcmp(argv[i], "--odd-size")) odd_size = TRUE;
    }
    width = (compact ? 240 : 640) + odd_size;
    height = (compact ? 160 : 960) + odd_size;
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    if (!RegisterClassW(&cls)) return 2;
    cls.lpszClassName = L"FirstTransactionDecoration";
    if (!RegisterClassW(&cls)) return 2;
    owner = CreateWindowExW(0, L"FirstTransactionBody", L"Owner", WS_POPUP | WS_THICKFRAME,
                            200, 150, 1000, 700, NULL, NULL, NULL, NULL);
    if (!owner) return 3;
    ShowWindow(owner, SW_SHOW);
    UpdateWindow(owner);
    pump();
    popup = CreateWindowExW(0, L"FirstTransactionBody", L"First frame transaction", WS_POPUP | WS_SYSMENU,
                            0, 0, 0, 0, owner, NULL, NULL, NULL);
    if (!popup) return 3;
    shadow = CreateWindowExW(WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
                             L"FirstTransactionDecoration", L"Decoration", WS_POPUP,
                             0, 0, 0, 0, popup, NULL, NULL, NULL);
    if (!shadow) return 3;
    SetLayeredWindowAttributes(shadow, 0, 255, LWA_ALPHA);
    SetWindowPos(popup, NULL, compact ? 400 : 500, 300, width, height, SWP_NOZORDER | SWP_NOACTIVATE);
    InvalidateRect(popup, NULL, FALSE);
    ShowWindow(popup, SW_SHOW);
    SetWindowPos(shadow, NULL, compact ? 390 : 452, compact ? 290 : 252,
                 width + (compact ? 20 : 96), height + (compact ? 20 : 96), SWP_NOZORDER | SWP_NOACTIVATE);
    ShowWindow(shadow, SW_SHOWNOACTIVATE);
    UpdateWindow(shadow);
    pump();
    state("pending");
    while (fgets(command, sizeof(command), stdin))
    {
        command[strcspn(command, "\r\n")] = 0;
        if (!strcmp(command, "quit")) break;
        if (!strcmp(command, "paint"))
        {
            paint_popup = TRUE;
            UpdateWindow(popup);
        }
        if (!strcmp(command, "hide")) ShowWindow(popup, SW_HIDE);
        if (!strcmp(command, "show"))
        {
            paint_popup = FALSE;
            InvalidateRect(popup, NULL, FALSE);
            ShowWindow(popup, SW_SHOW);
            ShowWindow(shadow, SW_SHOWNOACTIVATE);
            UpdateWindow(shadow);
        }
        pump();
        state(command);
    }
    DestroyWindow(popup);
    DestroyWindow(owner);
    return 0;
}
