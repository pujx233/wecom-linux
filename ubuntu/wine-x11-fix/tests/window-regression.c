#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static HWND owner, empty, layered, keyed, onepixel, palette, appwindow, resizable, edgemenu, bordered;

static void pump(DWORD duration)
{
    DWORD start = GetTickCount();
    MSG message;
    do {
        while (PeekMessageW(&message, NULL, 0, 0, PM_REMOVE)) {
            TranslateMessage(&message);
            DispatchMessageW(&message);
        }
        Sleep(1);
    } while (GetTickCount() - start < duration);
}

static void check(BOOL result, const char *operation)
{
    if (result) return;
    fprintf(stderr, "%s failed: %lu\n", operation, GetLastError());
    exit(2);
}

static void stage(const char *name, HWND window)
{
    pump(180);
    printf("{\"stage\":\"%s\",\"xid\":%lu,\"foreground\":%lu}\n", name,
           (unsigned long)GetPropA(window, "__wine_x11_whole_window"),
           (unsigned long)GetForegroundWindow());
}

static void update_layered(HWND window, int left, int top, int width, int height)
{
    BITMAPINFO info = {.bmiHeader = {.biSize = sizeof(BITMAPINFOHEADER), .biWidth = width, .biHeight = -height,
                                   .biPlanes = 1, .biBitCount = 32, .biCompression = BI_RGB}};
    DWORD *pixels;
    HDC screen = GetDC(NULL), memory = CreateCompatibleDC(screen);
    HBITMAP bitmap = CreateDIBSection(screen, &info, DIB_RGB_COLORS, (void **)&pixels, NULL, 0);
    HGDIOBJ previous;
    POINT position = {left, top}, source = {0, 0};
    SIZE size = {width, height};
    BLENDFUNCTION blend = {AC_SRC_OVER, 0, 255, AC_SRC_ALPHA};
    check(!!window && !!bitmap && !!memory, "create ARGB window");
    for (int y = 0; y < height; y++) {
        for (int x = 0; x < width; x++) {
            int edge = min(min(x, y), min(width - 1 - x, height - 1 - y));
            unsigned alpha = edge >= 4 && edge < 24 ? (edge - 3) * 8 : 0;
            pixels[y * width + x] = (alpha << 24) | alpha;
        }
    }
    previous = SelectObject(memory, bitmap);
    check(UpdateLayeredWindow(window, screen, &position, &size, memory, &source, 0, &blend, ULW_ALPHA),
          "UpdateLayeredWindow");
    SelectObject(memory, previous);
    DeleteObject(bitmap);
    DeleteDC(memory);
    ReleaseDC(NULL, screen);
}

static HWND make_layered(void)
{
    HWND window = CreateWindowExA(WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
                                  "WineNativeRegression", "ARGB input regression", WS_POPUP | WS_SYSMENU,
                                  100, 100, 128, 128, owner, NULL, GetModuleHandleA(NULL), NULL);
    check(!!window, "create layered window");
    update_layered(window, 100, 100, 128, 128);
    ShowWindow(window, SW_SHOWNOACTIVATE);
    return window;
}

static DWORD WINAPI update_worker(void *unused)
{
    (void)unused;
    for (int i = 0; i < 40; i++) update_layered(layered, 100, 100, 128, 128);
    return 0;
}

static void transparent(BOOL enabled)
{
    LONG style = GetWindowLongA(layered, GWL_EXSTYLE);
    SetWindowLongA(layered, GWL_EXSTYLE, enabled ? style | WS_EX_TRANSPARENT : style & ~WS_EX_TRANSPARENT);
    check(SetWindowPos(layered, NULL, 0, 0, 0, 0,
                       SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED),
          "change transparent style");
}

int main(void)
{
    WNDCLASSA cls = {.lpfnWndProc = DefWindowProcA, .hInstance = GetModuleHandleA(NULL),
                    .hbrBackground = (HBRUSH)(COLOR_WINDOW + 1), .lpszClassName = "WineNativeRegression"};
    char command[64];

    setvbuf(stdout, NULL, _IONBF, 0);
    SetProcessDPIAware();
    check(RegisterClassA(&cls), "RegisterClass");
    owner = CreateWindowExA(0, cls.lpszClassName, "Wine regression owner", WS_OVERLAPPEDWINDOW,
                            450, 120, 600, 500, NULL, NULL, cls.hInstance, NULL);
    check(!!owner, "create owner");
    ShowWindow(owner, SW_SHOWNOACTIVATE);
    empty = CreateWindowExA(WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, cls.lpszClassName, "Empty popup",
                            WS_POPUP, 600, 150, 320, 0, owner, NULL, cls.hInstance, NULL);
    check(!!empty, "create empty popup");
    ShowWindow(empty, SW_SHOWNOACTIVATE);
    stage("empty", empty);
    while (fgets(command, sizeof(command), stdin)) {
        command[strcspn(command, "\r\n")] = 0;
        if (!strcmp(command, "onepixel")) {
            onepixel = CreateWindowExA(WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, cls.lpszClassName, "One pixel",
                                       WS_POPUP, 800, 400, 1, 1, owner, NULL, cls.hInstance, NULL);
            check(!!onepixel, "create one pixel popup");
            ShowWindow(onepixel, SW_SHOWNOACTIVATE);
            stage("onepixel", onepixel);
        } else if (!strcmp(command, "palette")) {
            palette = CreateWindowExA(WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, cls.lpszClassName, "Caption palette",
                                      WS_POPUP | WS_CAPTION | WS_SYSMENU, 900, 120, 220, 150,
                                      owner, NULL, cls.hInstance, NULL);
            check(!!palette, "create caption palette");
            ShowWindow(palette, SW_SHOWNOACTIVATE);
            stage("palette", palette);
        } else if (!strcmp(command, "appwindow")) {
            appwindow = CreateWindowExA(WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_APPWINDOW,
                                        cls.lpszClassName, "Explicit app window", WS_POPUP | WS_SYSMENU,
                                        1150, 120, 220, 150, owner, NULL, cls.hInstance, NULL);
            check(!!appwindow, "create explicit app window");
            ShowWindow(appwindow, SW_SHOWNOACTIVATE);
            stage("appwindow", appwindow);
        } else if (!strcmp(command, "resizable")) {
            resizable = CreateWindowExA(WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
                                        cls.lpszClassName, "Resizable palette", WS_POPUP | WS_THICKFRAME | WS_SYSMENU,
                                        1150, 320, 220, 150, owner, NULL, cls.hInstance, NULL);
            check(!!resizable, "create resizable palette");
            ShowWindow(resizable, SW_SHOWNOACTIVATE);
            stage("resizable", resizable);
        } else if (!strcmp(command, "edgemenu")) {
            edgemenu = CreateWindowExA(WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
                                       cls.lpszClassName, "Bottom-edge menu", WS_POPUP,
                                       648, 900, 320, 100, owner, NULL, cls.hInstance, NULL);
            check(!!edgemenu, "create bottom-edge menu");
            ShowWindow(edgemenu, SW_SHOWNOACTIVATE);
            stage("edgemenu", edgemenu);
        } else if (!strcmp(command, "bordered")) {
            bordered = CreateWindowExA(WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT,
                                       cls.lpszClassName, "Bordered menu shadow", WS_POPUP | WS_BORDER | WS_SYSMENU,
                                       600, 852, 416, 196, edgemenu, NULL, cls.hInstance, NULL);
            check(!!bordered, "create bordered menu shadow");
            update_layered(bordered, 600, 852, 416, 196);
            ShowWindow(bordered, SW_SHOWNOACTIVATE);
            stage("bordered", bordered);
        } else if (!strcmp(command, "resize")) {
            check(SetWindowPos(empty, HWND_TOP, 600, 150, 320, 120, SWP_NOACTIVATE), "resize empty popup");
            check(SetWindowRgn(empty, CreateRoundRectRgn(0, 0, 320, 120, 8, 8), TRUE), "rounded region");
            UpdateWindow(empty);
            stage("resized", empty);
        } else if (!strcmp(command, "layered")) {
            layered = make_layered();
            stage("layered", layered);
        } else if (!strcmp(command, "plain") || !strcmp(command, "retagged")) {
            LONG ex_style = GetWindowLongA(layered, GWL_EXSTYLE);
            SetWindowLongA(layered, GWL_EXSTYLE, !strcmp(command, "plain") ?
                           ex_style & ~WS_EX_TOOLWINDOW : ex_style | WS_EX_TOOLWINDOW);
            check(SetWindowPos(layered, NULL, 0, 0, 0, 0,
                               SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED),
                  "toggle tool style on owned shadow");
            stage(command, layered);
        } else if (!strcmp(command, "transparent")) {
            transparent(TRUE);
            stage("transparent", layered);
        } else if (!strcmp(command, "interactive")) {
            transparent(FALSE);
            stage("interactive", layered);
        } else if (!strcmp(command, "remap")) {
            ShowWindow(layered, SW_HIDE);
            pump(40);
            ShowWindow(layered, SW_SHOWNOACTIVATE);
            stage("remapped", layered);
        } else if (!strcmp(command, "region")) {
            check(SetWindowRgn(layered, CreateRectRgn(0, 0, 64, 128), TRUE), "explicit ARGB region");
            stage("region", layered);
        } else if (!strcmp(command, "colorkey")) {
            HDC dc;
            RECT outer = {0, 0, 128, 128}, inner = {8, 8, 120, 120};
            HBRUSH clear = CreateSolidBrush(RGB(255, 0, 255)), solid = CreateSolidBrush(RGB(0, 255, 0));
            keyed = CreateWindowExA(WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
                                    cls.lpszClassName, "Color key regression", WS_POPUP,
                                    270, 100, 128, 128, owner, NULL, cls.hInstance, NULL);
            check(!!keyed, "create color key window");
            check(SetLayeredWindowAttributes(keyed, RGB(255, 0, 255), 255, LWA_COLORKEY), "set color key");
            ShowWindow(keyed, SW_SHOWNOACTIVATE);
            dc = GetDC(keyed);
            FillRect(dc, &outer, clear);
            FillRect(dc, &inner, solid);
            ReleaseDC(keyed, dc);
            DeleteObject(clear);
            DeleteObject(solid);
            GdiFlush();
            stage("colorkey", keyed);
        } else if (!strcmp(command, "cycles")) {
            for (int i = 0; i < 20; i++) {
                DestroyWindow(layered);
                layered = make_layered();
                transparent(TRUE);
                transparent(FALSE);
                pump(10);
            }
            stage("cycles", layered);
        } else if (!strcmp(command, "stress")) {
            HANDLE worker = CreateThread(NULL, 0, update_worker, NULL, 0, NULL);
            DWORD start = GetTickCount();
            check(!!worker, "create update worker");
            for (int i = 0; i < 40; i++) {
                check(SetWindowPos(layered, NULL, 100, 100, 128, 0,
                                   SWP_NOACTIVATE | SWP_NOZORDER), "concurrent shrink");
                check(SetWindowPos(layered, NULL, 100, 100, 128, 128,
                                   SWP_NOACTIVATE | SWP_NOZORDER), "concurrent grow");
                pump(1);
            }
            while (WaitForSingleObject(worker, 0) == WAIT_TIMEOUT && GetTickCount() - start < 8000) pump(1);
            check(WaitForSingleObject(worker, 0) == WAIT_OBJECT_0, "concurrent update completion");
            CloseHandle(worker);
            update_layered(layered, 100, 100, 128, 128);
            stage("stress", layered);
        } else if (!strcmp(command, "activate")) {
            SetActiveWindow(layered);
            check(SetWindowPos(layered, HWND_TOP, 0, 0, 0, 0,
                               SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED), "activate tool popup");
            stage("activated", layered);
        } else if (!strcmp(command, "quit")) break;
        else return 3;
    }
    if (keyed) DestroyWindow(keyed);
    if (onepixel) DestroyWindow(onepixel);
    if (palette) DestroyWindow(palette);
    if (appwindow) DestroyWindow(appwindow);
    if (resizable) DestroyWindow(resizable);
    if (bordered) DestroyWindow(bordered);
    if (edgemenu) DestroyWindow(edgemenu);
    if (layered) DestroyWindow(layered);
    DestroyWindow(empty);
    DestroyWindow(owner);
    return 0;
}
