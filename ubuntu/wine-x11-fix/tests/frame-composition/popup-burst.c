#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <string.h>

static HWND owner, popup, shadow;

static LRESULT CALLBACK proc(HWND hwnd, UINT message, WPARAM wp, LPARAM lp)
{
    if (message == WM_NCCALCSIZE || message == WM_ERASEBKGND) return 0;
    if (message == WM_PAINT)
    {
        PAINTSTRUCT ps;
        HBRUSH brush = CreateSolidBrush(hwnd == popup ? RGB(0, 255, 0) :
                                       hwnd == owner ? RGB(96, 96, 96) : RGB(0, 0, 255));
        HDC dc = BeginPaint(hwnd, &ps);
        FillRect(dc, &ps.rcPaint, brush);
        DeleteObject(brush);
        EndPaint(hwnd, &ps);
        return 0;
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
        Sleep(1);
    } while (GetTickCount() - start < 300);
}

static void state(const char *phase)
{
    RECT rect = {0};
    if (popup) GetWindowRect(popup, &rect);
    printf("{\"phase\":\"%s\",\"frame\":%llu,\"body\":%llu,\"shadow\":%llu,\"rect\":[%ld,%ld,%ld,%ld]}\n",
           phase, (unsigned long long)(UINT_PTR)GetPropA(popup, "__wine_x11_wm_window"),
           (unsigned long long)(UINT_PTR)GetPropA(popup, "__wine_x11_whole_window"),
           (unsigned long long)(UINT_PTR)GetPropA(shadow, "__wine_x11_whole_window"),
           rect.left, rect.top, rect.right, rect.bottom);
    fflush(stdout);
}

int main(void)
{
    WNDCLASSA cls = {.lpfnWndProc = proc, .lpszClassName = "PopupShadowBody"};
    char command[32];
    SetProcessDPIAware();
    RegisterClassA(&cls);
    cls.lpszClassName = "PopupShadowDecoration";
    RegisterClassA(&cls);
    owner = CreateWindowExA(0, "PopupShadowBody", "owner", WS_POPUP | WS_THICKFRAME,
                            200, 150, 900, 650, NULL, NULL, NULL, NULL);
    ShowWindow(owner, SW_SHOW);
    UpdateWindow(owner);
    pump();
    state("ready");
    while (fgets(command, sizeof(command), stdin))
    {
        command[strcspn(command, "\r\n")] = 0;
        if (!strcmp(command, "quit")) break;
        if (!strcmp(command, "popup") || !strcmp(command, "both"))
        {
            popup = CreateWindowExA(0, "PopupShadowBody", "popup", WS_POPUP | WS_SYSMENU,
                                    500, 300, 640, 960, owner, NULL, NULL, NULL);
            ShowWindow(popup, SW_SHOW);
            UpdateWindow(popup);
            shadow = CreateWindowExA(WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
                                      "PopupShadowDecoration", "shadow", 0x868a0000,
                                      452, 252, 736, 1056, popup, NULL, NULL, NULL);
            SetLayeredWindowAttributes(shadow, 0, 255, LWA_ALPHA);
        }
        if (!strcmp(command, "shadow") || !strcmp(command, "both"))
        {
            ShowWindow(shadow, SW_SHOWNOACTIVATE);
            UpdateWindow(shadow);
        }
        if (!strcmp(command, "close"))
        {
            DestroyWindow(popup);
            popup = shadow = NULL;
        }
        if (!strcmp(command, "shadow"))
        {
            MSG message;
            /* Dispatch the queued frame update, then leave its native acknowledgement pending. */
            if (PeekMessageA(&message, popup, 0x80001006, 0x80001006, PM_REMOVE))
                DispatchMessageA(&message);
        }
        else pump();
        state(command);
    }
    DestroyWindow(owner);
    return 0;
}
