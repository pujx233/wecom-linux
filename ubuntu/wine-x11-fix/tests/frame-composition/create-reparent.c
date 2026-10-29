#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static HWND owner, content, host;
static const char *phase;

struct enumeration
{
    HWND target;
    BOOL found;
};

static BOOL CALLBACK find_window(HWND hwnd, LPARAM param)
{
    struct enumeration *enumeration = (struct enumeration *)param;
    if (hwnd == enumeration->target) enumeration->found = TRUE;
    return TRUE;
}

static void state(HWND hwnd, const char *stage)
{
    RECT rect = {0};
    struct enumeration enumeration = {hwnd, FALSE};
    BOOL enumerated = EnumWindows(find_window, (LPARAM)&enumeration);
    GetWindowRect(hwnd, &rect);
    printf("{\"stage\":\"%s\",\"phase\":\"%s\",\"hwnd\":%llu,\"listed\":%s,\"enum_ok\":%s,"
           "\"body\":%lu,\"frame\":%lu,\"owner_frame\":%lu,\"host_frame\":%lu,"
           "\"owner_parent_is_host\":%s,\"width\":%ld,\"height\":%ld}\n",
           stage, phase, (unsigned long long)(ULONG_PTR)hwnd, enumeration.found ? "true" : "false",
           enumerated ? "true" : "false",
           (unsigned long)(ULONG_PTR)GetPropA(hwnd, "__wine_x11_whole_window"),
           (unsigned long)(ULONG_PTR)GetPropA(hwnd, "__wine_x11_wm_window"),
           (unsigned long)(ULONG_PTR)GetPropA(owner, "__wine_x11_wm_window"),
           (unsigned long)(ULONG_PTR)GetPropA(host, "__wine_x11_wm_window"),
           host && GetAncestor(owner, GA_PARENT) == host ? "true" : "false",
           rect.right - rect.left, rect.bottom - rect.top);
}

static LRESULT CALLBACK proc(HWND hwnd, UINT message, WPARAM wp, LPARAM lp)
{
    if (message == WM_NCCREATE)
        SetWindowLongPtrA(hwnd, GWLP_USERDATA, (LONG_PTR)((CREATESTRUCTA *)lp)->lpCreateParams);
    if ((message == WM_NCCREATE && GetWindowLongPtrA(hwnd, GWLP_USERDATA) == 1) ||
        (message == WM_CREATE && GetWindowLongPtrA(hwnd, GWLP_USERDATA) == 2))
    {
        state(hwnd, "before-style");
        SetWindowLongPtrA(hwnd, GWL_EXSTYLE, GetWindowLongPtrA(hwnd, GWL_EXSTYLE) | WS_EX_LAYERED);
        state(hwnd, "after-style");
    }
    if ((message == WM_NCCREATE && GetWindowLongPtrA(hwnd, GWLP_USERDATA) == 3) ||
        (message == WM_CREATE && GetWindowLongPtrA(hwnd, GWLP_USERDATA) == 4))
    {
        state(hwnd, "before-parent");
        SetParent(owner, host);
        state(hwnd, "after-parent");
    }
    if (message == WM_NCCALCSIZE) return 0;
    if (message == WM_PAINT)
    {
        PAINTSTRUCT paint;
        HDC dc = BeginPaint(hwnd, &paint);
        HBRUSH brush = CreateSolidBrush(hwnd == owner ? RGB(255, 255, 255) : RGB(0, 0, 255));
        FillRect(dc, &paint.rcPaint, brush);
        DeleteObject(brush);
        EndPaint(hwnd, &paint);
        return 0;
    }
    if (message == WM_APP)
    {
        if (wp) PostQuitMessage(0);
        else state(content, "state");
        return 0;
    }
    return DefWindowProcA(hwnd, message, wp, lp);
}

static DWORD WINAPI commands(void *unused)
{
    char line[32];
    (void)unused;
    while (fgets(line, sizeof(line), stdin))
    {
        BOOL quit = !strncmp(line, "quit", 4);
        if (!PostMessageA(owner, WM_APP, quit, 0) || quit) break;
    }
    return 0;
}

int main(int argc, char **argv)
{
    WNDCLASSA wc = {0};
    MSG message;
    DWORD error;
    INT_PTR mode;
    if (argc != 2) return 2;
    phase = argv[1];
    if (!strcmp(phase, "none")) mode = 0;
    else if (!strcmp(phase, "nccreate")) mode = 1;
    else if (!strcmp(phase, "create")) mode = 2;
    else if (!strcmp(phase, "owner-nccreate")) mode = 3;
    else if (!strcmp(phase, "owner-create")) mode = 4;
    else return 2;
    setvbuf(stdout, NULL, _IONBF, 0);
    SetProcessDPIAware();
    wc.lpfnWndProc = proc;
    wc.hInstance = GetModuleHandleA(NULL);
    wc.lpszClassName = "CreateReparent";
    if (!RegisterClassA(&wc)) return 3;
    if (mode >= 3)
    {
        host = CreateWindowExA(0, wc.lpszClassName, "synthetic host", WS_POPUP | WS_THICKFRAME,
                              100, 50, 800, 650, NULL, NULL, wc.hInstance, NULL);
        if (!host) return 4;
        ShowWindow(host, SW_SHOW);
        UpdateWindow(host);
    }
    owner = CreateWindowExA(0, wc.lpszClassName, "synthetic owner", WS_POPUP | WS_THICKFRAME,
                            200, 100, 640, 500, NULL, NULL, wc.hInstance, NULL);
    if (!owner) return 4;
    ShowWindow(owner, SW_SHOW);
    UpdateWindow(owner);
    content = CreateWindowExA(WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | (mode >= 3 ? WS_EX_LAYERED : 0),
                              wc.lpszClassName, "synthetic content",
                              WS_POPUP | WS_THICKFRAME, 300, 200, 200, 200, owner, NULL, wc.hInstance, (void *)mode);
    error = GetLastError();
    printf("{\"stage\":\"create-return\",\"phase\":\"%s\",\"hwnd\":%llu,\"last_error\":%lu}\n",
           phase, (unsigned long long)(ULONG_PTR)content, error);
    if (!content) return 5;
    if (mode) SetLayeredWindowAttributes(content, 0, 255, LWA_ALPHA);
    ShowWindow(content, SW_SHOWNOACTIVATE);
    UpdateWindow(content);
    state(content, "ready");
    CreateThread(NULL, 0, commands, NULL, 0, NULL);
    while (GetMessageA(&message, NULL, 0, 0) > 0)
    {
        TranslateMessage(&message);
        DispatchMessageA(&message);
    }
    DestroyWindow(content);
    DestroyWindow(owner);
    if (host) DestroyWindow(host);
    return 0;
}
