#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <string.h>

static HWND owner, shadow, title, popup;
static BOOL changing, moving, entered;

static void state(const char *phase)
{
    RECT rect;
    POINT cursor;
    GetWindowRect(owner, &rect);
    GetCursorPos(&cursor);
    printf("{\"phase\":\"%s\",\"owner_rect\":[%ld,%ld,%ld,%ld],\"frame\":%llu,\"body\":%llu,"
           "\"shadow\":%llu,\"title\":%llu,\"shadow_frame\":%llu,\"title_frame\":%llu,"
           "\"popup\":%llu,\"popup_frame\":%llu,\"cursor\":[%ld,%ld]}\n", phase,
           rect.left, rect.top, rect.right, rect.bottom,
           (unsigned long long)(UINT_PTR)GetPropA(owner, "__wine_x11_wm_window"),
           (unsigned long long)(UINT_PTR)GetPropA(owner, "__wine_x11_whole_window"),
           (unsigned long long)(UINT_PTR)GetPropA(shadow, "__wine_x11_whole_window"),
           (unsigned long long)(UINT_PTR)GetPropA(title, "__wine_x11_whole_window"),
           (unsigned long long)(UINT_PTR)GetPropA(shadow, "__wine_x11_wm_window"),
           (unsigned long long)(UINT_PTR)GetPropA(title, "__wine_x11_wm_window"),
           popup ? (unsigned long long)(UINT_PTR)GetPropA(popup, "__wine_x11_whole_window") : 0,
           popup ? (unsigned long long)(UINT_PTR)GetPropA(popup, "__wine_x11_wm_window") : 0,
           cursor.x, cursor.y);
    fflush(stdout);
}

static LRESULT CALLBACK proc(HWND hwnd, UINT message, WPARAM wp, LPARAM lp)
{
    if (message == WM_NCCALCSIZE || message == WM_ERASEBKGND) return 0;
    if (message == WM_PAINT)
    {
        PAINTSTRUCT ps;
        RECT rect;
        HBRUSH brush = CreateSolidBrush(hwnd == owner ? RGB(48, 176, 96) :
                                       hwnd == title ? RGB(40, 80, 220) : RGB(255, 255, 255));
        BeginPaint(hwnd, &ps);
        GetClientRect(hwnd, &rect);
        FillRect(ps.hdc, &rect, brush);
        DeleteObject(brush);
        EndPaint(hwnd, &ps);
        return 0;
    }
    if (hwnd == owner && moving && !entered &&
        message == (changing ? WM_WINDOWPOSCHANGING : WM_WINDOWPOSCHANGED))
    {
        WINDOWPOS *pos = (WINDOWPOS *)lp;
        char command[32];
        entered = TRUE;
        if (!SetWindowPos(shadow, NULL, pos->x - 36, pos->y - 36, 0, 0,
                          SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE) ||
            !SetWindowPos(title, NULL, pos->x, pos->y, 0, 0,
                          SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)) ExitProcess(7);
        state("callback");
        if (!fgets(command, sizeof(command), stdin) || strcmp(command, "continue\n")) ExitProcess(8);
    }
    return DefWindowProcA(hwnd, message, wp, lp);
}

static void pump(void)
{
    MSG message;
    DWORD start = GetTickCount();
    do
    {
        while (PeekMessageA(&message, NULL, 0, 0, PM_REMOVE)) DispatchMessageA(&message);
        Sleep(5);
    } while (GetTickCount() - start < 300);
}

int main(int argc, char **argv)
{
    WNDCLASSA cls = {.lpfnWndProc = proc, .lpszClassName = "AnchorOrderOwner"};
    DWORD ex = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE;
    char command[32], guard[8];

    if (argc != 2 || (strcmp(argv[1], "before") && strcmp(argv[1], "after") &&
                     strcmp(argv[1], "native") && strcmp(argv[1], "popup"))) return 1;
    if (!GetEnvironmentVariableA("WECOM_ANCHOR_ORDER_FIXTURE", guard, sizeof(guard)) || strcmp(guard, "1"))
        return 2;
    changing = !strcmp(argv[1], "before");
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    if (!RegisterClassA(&cls)) return 3;
    owner = CreateWindowExA(0, cls.lpszClassName, "Anchor order fixture", WS_POPUP | WS_THICKFRAME,
                            200, 200, 320, 240, NULL, NULL, NULL, NULL);
    if (!owner) return 4;
    ShowWindow(owner, SW_SHOW);
    UpdateWindow(owner);
    cls.lpszClassName = "AnchorOrderShadow";
    if (!RegisterClassA(&cls)) return 3;
    shadow = CreateWindowExA(ex, cls.lpszClassName, "shadow", WS_POPUP,
                             164, 164, 392, 312, owner, NULL, NULL, NULL);
    cls.lpszClassName = "AnchorOrderTitle";
    if (!RegisterClassA(&cls)) return 3;
    title = CreateWindowExA(ex, cls.lpszClassName, "title", WS_POPUP,
                            200, 200, 300, 24, owner, NULL, NULL, NULL);
    if (!shadow || !title) return 5;
    SetLayeredWindowAttributes(shadow, 0, 255, LWA_ALPHA);
    SetLayeredWindowAttributes(title, 0, 255, LWA_ALPHA);
    ShowWindow(shadow, SW_SHOWNOACTIVATE);
    ShowWindow(title, SW_SHOWNOACTIVATE);
    UpdateWindow(shadow);
    UpdateWindow(title);
    pump();
    UpdateWindow(owner);
    pump();
    state("ready");
    while (fgets(command, sizeof(command), stdin))
    {
        command[strcspn(command, "\r\n")] = 0;
        if (!strcmp(command, "quit")) break;
        if (!strcmp(command, "move"))
        {
            moving = TRUE;
            if (!SetWindowPos(owner, NULL, 500, 300, 0, 0,
                              SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)) return 6;
            moving = FALSE;
            if (!entered) return 9;
        }
        else if (!strcmp(command, "move-owner"))
        {
            if (!SetWindowPos(owner, NULL, 500, 300, 0, 0,
                              SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)) return 6;
        }
        else if (!strcmp(command, "native-follow"))
        {
            RECT rect;
            GetWindowRect(owner, &rect);
            if (!SetWindowPos(shadow, NULL, rect.left - 36, rect.top - 36, 0, 0,
                              SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE) ||
                !SetWindowPos(title, NULL, rect.left, rect.top, 0, 0,
                              SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)) return 7;
            state(command);
            continue;
        }
        else if (!strcmp(command, "popup"))
        {
            POINT cursor;
            cls.lpszClassName = "AnchorOrderIndependent";
            if (!RegisterClassA(&cls) || !GetCursorPos(&cursor)) return 11;
            popup = CreateWindowExA(ex, cls.lpszClassName, "independent popup", WS_POPUP | WS_THICKFRAME,
                                    cursor.x, cursor.y, 80, 60, owner, NULL, NULL, NULL);
            if (!popup) return 12;
            SetLayeredWindowAttributes(popup, 0, 255, LWA_ALPHA);
            ShowWindow(popup, SW_SHOWNOACTIVATE);
            UpdateWindow(popup);
        }
        else if (strcmp(command, "dispatch")) return 10;
        pump();
        state(command);
    }
    DestroyWindow(owner);
    return 0;
}
