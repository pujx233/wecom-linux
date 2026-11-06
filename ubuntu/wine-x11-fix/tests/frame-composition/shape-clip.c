#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <string.h>

static HWND body, decoration;
static COLORREF color = RGB(0, 255, 0);

static LRESULT CALLBACK procedure(HWND hwnd, UINT message, WPARAM wp, LPARAM lp)
{
    if (message == WM_NCCALCSIZE || message == WM_ERASEBKGND) return 0;
    if (message == WM_PAINT)
    {
        PAINTSTRUCT ps;
        HDC dc = BeginPaint(hwnd, &ps);
        SetDCBrushColor(dc, hwnd == body ? color : RGB(255, 0, 0));
        FillRect(dc, &ps.rcPaint, GetStockObject(DC_BRUSH));
        EndPaint(hwnd, &ps);
        return 0;
    }
    return DefWindowProcW(hwnd, message, wp, lp);
}

static void pump(void)
{
    DWORD start = GetTickCount();
    MSG message;
    do
    {
        while (PeekMessageW(&message, NULL, 0, 0, PM_REMOVE)) DispatchMessageW(&message);
        Sleep(1);
    } while (GetTickCount() - start < 200);
}

static void state(const char *phase)
{
    printf("{\"phase\":\"%s\",\"body\":%llu,\"frame\":%llu,\"decoration\":%llu}\n", phase,
           (unsigned long long)(UINT_PTR)GetPropW(body, L"__wine_x11_whole_window"),
           (unsigned long long)(UINT_PTR)GetPropW(body, L"__wine_x11_wm_window"),
           (unsigned long long)(UINT_PTR)GetPropW(decoration, L"__wine_x11_whole_window"));
    fflush(stdout);
}

int main(void)
{
    WNDCLASSW cls = {.lpfnWndProc = procedure, .lpszClassName = L"ShapeClipBody"};
    BITMAPINFO info = {.bmiHeader = {.biSize = sizeof(BITMAPINFOHEADER), .biWidth = 416, .biHeight = -336,
                                   .biPlanes = 1, .biBitCount = 32, .biCompression = BI_RGB}};
    BLENDFUNCTION blend = {AC_SRC_OVER, 0, 255, AC_SRC_ALPHA};
    SIZE size = {416, 336};
    POINT position, origin = {0};
    HDC dc;
    HBITMAP bitmap, previous;
    DWORD *pixels;
    int x, y;
    RECT rect;
    char command[32];

    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    if (!RegisterClassW(&cls)) return 2;
    cls.lpszClassName = L"ShapeClipDecoration";
    if (!RegisterClassW(&cls)) return 2;
    body = CreateWindowExW(0, L"ShapeClipBody", L"Window shape composition", WS_POPUP | WS_THICKFRAME,
                          400, 300, 320, 240, NULL, NULL, NULL, NULL);
    if (!body) return 3;
    ShowWindow(body, SW_SHOW);
    UpdateWindow(body);
    pump();
    GetWindowRect(body, &rect);
    decoration = CreateWindowExW(WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
                                 L"ShapeClipDecoration", L"", WS_POPUP, rect.left - 48, rect.top - 48,
                                 416, 336, body, NULL, NULL, NULL);
    if (!decoration) return 3;
    dc = CreateCompatibleDC(NULL);
    bitmap = CreateDIBSection(dc, &info, DIB_RGB_COLORS, (void **)&pixels, NULL, 0);
    if (!dc || !bitmap) return 4;
    for (y = 0; y < size.cy; y++)
        for (x = 0; x < size.cx; x++) pixels[y * size.cx + x] = x < 16 ? 0xffff0000 : 0;
    previous = SelectObject(dc, bitmap);
    position.x = rect.left - 48;
    position.y = rect.top - 48;
    if (!UpdateLayeredWindow(decoration, NULL, &position, &size, dc, &origin, 0, &blend, ULW_ALPHA)) return 5;
    SelectObject(dc, previous);
    DeleteObject(bitmap);
    DeleteDC(dc);
    ShowWindow(decoration, SW_SHOWNOACTIVATE);
    pump();
    state("ready");
    while (fgets(command, sizeof(command), stdin))
    {
        command[strcspn(command, "\r\n")] = 0;
        if (!strcmp(command, "quit")) break;
        color = color == RGB(0, 255, 0) ? RGB(0, 0, 255) : RGB(0, 255, 0);
        InvalidateRect(body, NULL, FALSE);
        UpdateWindow(body);
        pump();
        state(command);
    }
    DestroyWindow(decoration);
    DestroyWindow(body);
    return 0;
}
