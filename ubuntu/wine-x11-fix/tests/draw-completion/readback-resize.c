#define UNICODE
#define _UNICODE
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define WM_COMMAND_LINE (WM_APP + 19)
struct command { unsigned sequence; char action[20]; int width, height; };
static HWND main_window, title_window, shadow_window;
static unsigned sequence, generation, paints;
static int current_width, current_height;
static BOOL freeze_region;
static BOOL solid_color, foreign_child, corner_cut;
static BOOL retained_dc;

static void record(const char *event)
{
    RECT rect = {0}, client = {0}, box = {0};
    HRGN region = CreateRectRgn(0, 0, 0, 0);
    DWORD count = 0, size;
    RGNDATA *data = NULL;
    unsigned index;
    int type;

    GetWindowRect(main_window, &rect);
    GetClientRect(main_window, &client);
    type = GetWindowRgn(main_window, region);
    if (type != ERROR)
    {
        GetRgnBox(region, &box);
        size = GetRegionData(region, 0, NULL);
        if (size && (data = malloc(size)) && GetRegionData(region, size, data)) count = data->rdh.nCount;
    }
    printf("{\"event\":\"%s\",\"sequence\":%u,\"generation\":%u,\"paints\":%u,"
           "\"main\":%llu,\"main_xid\":%llu,\"title\":%llu,\"shadow\":%llu,"
           "\"title_owner\":%llu,\"shadow_owner\":%llu,"
           "\"window\":[%ld,%ld,%ld,%ld],\"client\":[%ld,%ld,%ld,%ld],\"region_type\":%d,"
           "\"region_box\":[%ld,%ld,%ld,%ld],\"region_frozen\":%s,\"maximized\":%s,"
           "\"foreign_child\":%s,\"region_rects\":[",
           event, sequence, generation, paints, (unsigned long long)(ULONG_PTR)main_window,
           (unsigned long long)(ULONG_PTR)GetPropW(main_window, L"__wine_x11_whole_window"),
           (unsigned long long)(ULONG_PTR)title_window, (unsigned long long)(ULONG_PTR)shadow_window,
           (unsigned long long)(ULONG_PTR)GetWindow(title_window, GW_OWNER),
           (unsigned long long)(ULONG_PTR)GetWindow(shadow_window, GW_OWNER),
           rect.left, rect.top, rect.right, rect.bottom, client.left, client.top, client.right, client.bottom,
           type, box.left, box.top, box.right, box.bottom, freeze_region ? "true" : "false",
           IsZoomed(main_window) ? "true" : "false", foreign_child ? "true" : "false");
    for (index = 0; index < count; index++)
    {
        RECT *r = (RECT *)data->Buffer + index;
        printf("%s[%ld,%ld,%ld,%ld]", index ? "," : "", r->left, r->top, r->right, r->bottom);
    }
    puts("]}");
    fflush(stdout);
    free(data);
    DeleteObject(region);
}

static void paint_layer(HWND window, BOOL shadow, const RECT *main_rect)
{
    int pad = shadow ? 20 : 0, width = main_rect->right - main_rect->left + pad * 2;
    int height = shadow ? main_rect->bottom - main_rect->top + pad * 2 : 64, x, y;
    BITMAPINFO info = {.bmiHeader = {.biSize = sizeof(BITMAPINFOHEADER), .biWidth = width,
        .biHeight = -height, .biPlanes = 1, .biBitCount = 32, .biCompression = BI_RGB}};
    HDC dc = CreateCompatibleDC(NULL);
    DWORD *pixels;
    HBITMAP bitmap = CreateDIBSection(dc, &info, DIB_RGB_COLORS, (void **)&pixels, NULL, 0);
    HGDIOBJ previous = SelectObject(dc, bitmap);
    POINT source = {0}, destination = {main_rect->left - pad, main_rect->top - pad};
    SIZE size = {width, height};
    BLENDFUNCTION blend = {AC_SRC_OVER, 0, 255, AC_SRC_ALPHA};

    if (!bitmap) ExitProcess(3);
    for (y = 0; y < height; y++)
        for (x = 0; x < width; x++)
            pixels[y * width + x] = shadow ?
                (x < pad || y < pad || x >= width - pad || y >= height - pad ? 0x40000000 : 0) :
                (y < 12 || (x > width - 160 && y < 40) ? 0xc0909090 : 0);
    if (!UpdateLayeredWindow(window, NULL, &destination, &size, dc, &source, 0, &blend, ULW_ALPHA))
        ExitProcess(4);
    SelectObject(dc, previous);
    DeleteObject(bitmap);
    DeleteDC(dc);
}

static void update_region(HWND window)
{
    RECT rect;
    HRGN region, cut;

    GetWindowRect(window, &rect);
    if (!freeze_region)
    {
        region = CreateRectRgn(0, 0, rect.right - rect.left, rect.bottom - rect.top);
        cut = CreateRectRgn(0, 0, 18, 18);
        CombineRgn(region, region, cut, RGN_DIFF);
        DeleteObject(cut);
        if (corner_cut)
        {
            cut = CreateRectRgn(0, rect.bottom - rect.top - 64, 80, rect.bottom - rect.top);
            CombineRgn(region, region, cut, RGN_DIFF);
            DeleteObject(cut);
        }
        if (!SetWindowRgn(window, region, TRUE)) ExitProcess(5);
    }
    if (title_window && shadow_window)
    {
        paint_layer(shadow_window, TRUE, &rect);
        paint_layer(title_window, FALSE, &rect);
    }
}

static void paint_main(HWND window)
{
    PAINTSTRUCT paint;
    RECT rect;
    BITMAPINFO info = {.bmiHeader = {.biSize = sizeof(BITMAPINFOHEADER), .biHeight = 0,
        .biPlanes = 1, .biBitCount = 32, .biCompression = BI_RGB}};
    HDC target = BeginPaint(window, &paint), dc = CreateCompatibleDC(target);
    DWORD *pixels, header[4], written;
    HBITMAP bitmap;
    HANDLE file;
    int x, y, width, height;

    GetClientRect(window, &rect);
    width = rect.right;
    height = rect.bottom;
    if (!width || !height) { DeleteDC(dc); EndPaint(window, &paint); return; }
    info.bmiHeader.biWidth = width;
    info.bmiHeader.biHeight = -height;
    bitmap = CreateDIBSection(dc, &info, DIB_RGB_COLORS, (void **)&pixels, NULL, 0);
    if (!bitmap) ExitProcess(6);
    for (y = 0; y < height; y++)
        for (x = 0; x < width; x++)
            pixels[y * width + x] = solid_color ? (x >= width - 160 ? 0xffff00ff : 0xff30b060) :
                0xff000000 | (((x * 3 + y * 5 + width + generation * 17) & 255) << 16) |
                (((x * 7 + y * 2 + height + generation * 29) & 255) << 8) | ((x + y * 11 + generation * 13) & 255);
    SetDIBitsToDevice(target, 0, 0, width, height, 0, 0, 0, height, pixels, &info, DIB_RGB_COLORS);
    GdiFlush();
    EndPaint(window, &paint);
    file = CreateFileW(L"qa-resize-frame.bin", GENERIC_WRITE, FILE_SHARE_READ, NULL,
                       CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) ExitProcess(7);
    header[0] = sequence; header[1] = generation; header[2] = width; header[3] = height;
    if (!WriteFile(file, header, sizeof(header), &written, NULL) || written != sizeof(header) ||
        !WriteFile(file, pixels, width * height * 4, &written, NULL) || written != (DWORD)(width * height * 4))
        ExitProcess(8);
    CloseHandle(file);
    DeleteObject(bitmap);
    DeleteDC(dc);
    paints++;
    record("paint-complete");
}

static LRESULT CALLBACK procedure(HWND window, UINT message, WPARAM wp, LPARAM lp)
{
    if (message == WM_NCCALCSIZE || message == WM_NCPAINT) return 0;
    if (message == WM_NCHITTEST)
    {
        RECT rect;
        POINT point = {(short)LOWORD(lp), (short)HIWORD(lp)};
        GetWindowRect(window, &rect);
        if (point.x >= rect.left + 32 && point.x < rect.right - 200 &&
            point.y >= rect.top + 12 && point.y < rect.top + 32) return HTCAPTION;
    }
    if (message == WM_MOVE && title_window && shadow_window)
    {
        RECT rect;
        GetWindowRect(window, &rect);
        paint_layer(shadow_window, TRUE, &rect);
        paint_layer(title_window, FALSE, &rect);
    }
    if (message == WM_GETMINMAXINFO)
    {
        MONITORINFO info = {.cbSize = sizeof(info)};
        MINMAXINFO *limits = (MINMAXINFO *)lp;
        GetMonitorInfoW(MonitorFromWindow(window, MONITOR_DEFAULTTONEAREST), &info);
        limits->ptMaxPosition = (POINT){info.rcWork.left - info.rcMonitor.left,
                                       info.rcWork.top - info.rcMonitor.top};
        limits->ptMaxSize = (POINT){info.rcWork.right - info.rcWork.left, info.rcWork.bottom - info.rcWork.top};
        return 0;
    }
    if (message == WM_SIZE && wp != SIZE_MINIMIZED)
    {
        RECT rect;
        GetClientRect(window, &rect);
        if (current_width != rect.right || current_height != rect.bottom)
        {
            current_width = rect.right; current_height = rect.bottom; generation++;
            update_region(window);
            InvalidateRect(window, NULL, FALSE);
        }
    }
    if (message == WM_PAINT) { paint_main(window); return 0; }
    if (message == WM_COMMAND_LINE)
    {
        struct command *command = (struct command *)lp;
        sequence = command->sequence;
        if (!strcmp(command->action, "resize"))
        {
            RECT dirty = {300, 200, 600, 500};
            HDC dc = retained_dc ? GetDC(window) : NULL, memory;
            HBITMAP bitmap;
            HGDIOBJ previous;
            HBRUSH brush;
            RECT rect;
            int saved;

            ShowWindow(window, SW_RESTORE);
            InvalidateRect(window, &dirty, FALSE);
            SetWindowPos(window, NULL, 100, 100, command->width, command->height, SWP_NOZORDER);
            if (!dc) dc = GetDC(window);
            GetClientRect(window, &rect);
            memory = CreateCompatibleDC(dc);
            bitmap = CreateCompatibleBitmap(dc, rect.right, rect.bottom);
            previous = SelectObject(memory, bitmap);
            if (!BitBlt(memory, 0, 0, rect.right, rect.bottom, dc, 0, 0, SRCCOPY)) ExitProcess(10);
            printf("{\"event\":\"readback\",\"sequence\":%u,\"memory_pixel\":%lu}\n",
                   sequence, GetPixel(memory, 400, 300));
            fflush(stdout);
            ValidateRect(window, NULL);
            saved = SaveDC(dc);
            IntersectClipRect(dc, 0, 0, 0, 0);
            PatBlt(dc, 0, 0, rect.right, rect.bottom, BLACKNESS);
            RestoreDC(dc, saved);
            record("resize-hold-start");
            Sleep(350);
            record("resize-hold-end");
            brush = CreateSolidBrush(RGB(48,176,96));
            FillRect(dc, &rect, brush);
            ReleaseDC(window, dc);
            DeleteObject(brush);
            SelectObject(memory, previous);
            DeleteObject(bitmap);
            DeleteDC(memory);
            record("draw-hold-start");
            Sleep(350);
            record("draw-hold-end");
        }
        else if (!strcmp(command->action, "maximize")) ShowWindow(window, SW_MAXIMIZE);
        else if (!strcmp(command->action, "restore")) ShowWindow(window, SW_RESTORE);
        else if (!strcmp(command->action, "freeze-region")) freeze_region = TRUE;
        else if (!strcmp(command->action, "dynamic-region")) { freeze_region = FALSE; update_region(window); }
        else if (!strcmp(command->action, "remove-foreign"))
        {
            HWND child = FindWindowExW(window, NULL, L"STATIC", NULL);
            DWORD started = GetTickCount();
            MSG message;
            if (!child || !PostMessageW(child, WM_CLOSE, 0, 0)) ExitProcess(15);
            while (IsWindow(child))
            {
                if (GetTickCount() - started > 5000) ExitProcess(16);
                MsgWaitForMultipleObjects(0, NULL, FALSE, 20, QS_ALLINPUT);
                while (PeekMessageW(&message, NULL, 0, 0, PM_REMOVE)) DispatchMessageW(&message);
            }
            foreign_child = FALSE;
            SetWindowPos(window, NULL, 0, 0, 0, 0,
                          SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED);
        }
        else if (!strcmp(command->action, "clear-region"))
        {
            freeze_region = TRUE;
            SetWindowRgn(window, NULL, TRUE);
        }
        else if (!strcmp(command->action, "quit")) DestroyWindow(window);
        if (IsWindow(window)) { InvalidateRect(window, NULL, FALSE); record("command-ack"); }
        free(command);
        return 0;
    }
    if (message == WM_DESTROY) { DestroyWindow(title_window); DestroyWindow(shadow_window); PostQuitMessage(0); }
    return DefWindowProcW(window, message, wp, lp);
}

static DWORD WINAPI commands(void *unused)
{
    char line[100];
    (void)unused;
    while (fgets(line, sizeof(line), stdin))
    {
        struct command *command = calloc(1, sizeof(*command));
        if (!command) return 1;
        if (sscanf(line, "%u %19s %d %d", &command->sequence, command->action,
                   &command->width, &command->height) < 2 ||
            !PostMessageW(main_window, WM_COMMAND_LINE, 0, (LPARAM)command))
            free(command);
    }
    return 0;
}

int main(int argc, char **argv)
{
    WNDCLASSW cls = {.lpfnWndProc = procedure, .lpszClassName = L"ShapedResizeProbe"};
    MSG message;
    HANDLE thread;
    PROCESS_INFORMATION process = {0};
    SetProcessDPIAware();
    if (argc == 3 && !strcmp(argv[1], "--foreign-child"))
    {
        HWND parent = (HWND)(ULONG_PTR)strtoull(argv[2], NULL, 0);
        HWND child = CreateWindowW(L"STATIC", L"Foreign child", WS_CHILD | WS_VISIBLE,
                                   100, 200, 180, 100, parent, NULL, NULL, NULL);
        char name[100];
        HANDLE ready;
        if (!child) return 11;
        snprintf(name, sizeof(name), "Local\\ResizeShapeReady-%llu", (unsigned long long)(ULONG_PTR)parent);
        ready = OpenEventA(EVENT_MODIFY_STATE, FALSE, name);
        if (!ready || !SetEvent(ready)) return 12;
        CloseHandle(ready);
        while (IsWindow(child))
        {
            MsgWaitForMultipleObjects(0, NULL, FALSE, 50, QS_ALLINPUT);
            while (PeekMessageW(&message, NULL, 0, 0, PM_REMOVE)) DispatchMessageW(&message);
        }
        return 0;
    }
    solid_color = GetEnvironmentVariableW(L"QA_RESIZE_SOLID", NULL, 0) > 0;
    corner_cut = GetEnvironmentVariableW(L"QA_RESIZE_CORNER_CUT", NULL, 0) > 0;
    retained_dc = GetEnvironmentVariableW(L"QA_RESIZE_RETAIN_DC", NULL, 0) > 0;
    cls.hCursor = LoadCursorW(NULL, IDC_ARROW);
    if (!RegisterClassW(&cls)) return 1;
    main_window = CreateWindowExW(0, cls.lpszClassName, L"Shaped resize main",
        WS_POPUP | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX,
        100, 100, 1972, 1520, NULL, NULL, NULL, NULL);
    cls.lpfnWndProc = DefWindowProcW; cls.lpszClassName = L"ShapedResizeLayer";
    if (!main_window || !RegisterClassW(&cls)) return 2;
    title_window = CreateWindowExW(WS_EX_TOOLWINDOW | WS_EX_LAYERED, cls.lpszClassName,
        L"Shaped resize title", WS_POPUP, 100, 100, 1972, 64, main_window, NULL, NULL, NULL);
    shadow_window = CreateWindowExW(WS_EX_TOOLWINDOW | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE,
        cls.lpszClassName, L"Shaped resize shadow", WS_POPUP, 80, 80, 2012, 1560, main_window, NULL, NULL, NULL);
    update_region(main_window);
    ShowWindow(main_window, SW_SHOW);
    ShowWindow(shadow_window, SW_SHOWNOACTIVATE);
    ShowWindow(title_window, SW_SHOWNOACTIVATE);
    SetWindowPos(title_window, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
    SetForegroundWindow(main_window);
    foreign_child = GetEnvironmentVariableW(L"QA_RESIZE_FOREIGN_CHILD", NULL, 0) > 0;
    if (foreign_child)
    {
        char path[MAX_PATH], command[MAX_PATH + 100], name[100];
        HANDLE ready;
        DWORD started = GetTickCount();
        STARTUPINFOA startup = {.cb = sizeof(startup)};
        snprintf(name, sizeof(name), "Local\\ResizeShapeReady-%llu", (unsigned long long)(ULONG_PTR)main_window);
        ready = CreateEventA(NULL, TRUE, FALSE, name);
        GetModuleFileNameA(NULL, path, sizeof(path));
        snprintf(command, sizeof(command), "\"%s\" --foreign-child %llu", path,
                  (unsigned long long)(ULONG_PTR)main_window);
        if (!ready || !CreateProcessA(path, command, NULL, NULL, FALSE, CREATE_NO_WINDOW,
                                      NULL, NULL, &startup, &process)) return 13;
        while (WaitForSingleObject(ready, 0) != WAIT_OBJECT_0)
        {
            if (GetTickCount() - started > 10000) return 14;
            MsgWaitForMultipleObjects(1, &ready, FALSE, 50, QS_ALLINPUT);
            while (PeekMessageW(&message, NULL, 0, 0, PM_REMOVE)) DispatchMessageW(&message);
        }
        CloseHandle(ready);
    }
    thread = CreateThread(NULL, 0, commands, NULL, 0, NULL);
    if (!thread) return 9;
    CloseHandle(thread);
    record("ready");
    InvalidateRect(main_window, NULL, FALSE);
    while (GetMessageW(&message, NULL, 0, 0) > 0) DispatchMessageW(&message);
    if (process.hProcess)
    {
        if (WaitForSingleObject(process.hProcess, 3000) == WAIT_TIMEOUT) TerminateProcess(process.hProcess, 0);
        CloseHandle(process.hThread);
        CloseHandle(process.hProcess);
    }
    return 0;
}
