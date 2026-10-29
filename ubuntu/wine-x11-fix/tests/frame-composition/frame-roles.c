#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

static HWND owner, content, peer;
static unsigned sequence;
static LRESULT CALLBACK proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    if (msg == WM_NCCREATE)
        SetWindowLongPtrA(hwnd, GWLP_USERDATA, (LONG_PTR)((CREATESTRUCTA *)lp)->lpCreateParams);
    if (msg == WM_NCCALCSIZE) return 0;
    if (msg == WM_PAINT)
    {
        PAINTSTRUCT ps;
        HDC dc = BeginPaint(hwnd, &ps);
        HBRUSH brush = CreateSolidBrush((COLORREF)GetWindowLongPtrA(hwnd, GWLP_USERDATA));
        FillRect(dc, &ps.rcPaint, brush);
        DeleteObject(brush);
        EndPaint(hwnd, &ps);
        return 0;
    }
    if (msg == WM_APP)
    {
        char *command = (char *)lp;
        if (!strcmp(command, "normal"))
            SetWindowPos(content, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
        else if (!strcmp(command, "promote"))
            SetWindowPos(content, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
        else if (!strcmp(command, "resize"))
            SetWindowPos(content, NULL, 0, 0, 200, 200, SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE);
        else if (!strcmp(command, "state"))
        {
            RECT rect;
            GetWindowRect(content, &rect);
            printf("{\"sequence\":%u,\"owner_frame\":%lu,\"frame\":%lu,\"body\":%lu,\"exstyle\":%lu,"
                   "\"width\":%ld,\"height\":%ld}\n",
                   sequence, (unsigned long)(ULONG_PTR)GetPropA(owner, "__wine_x11_wm_window"),
                   (unsigned long)(ULONG_PTR)GetPropA(content, "__wine_x11_wm_window"),
                   (unsigned long)(ULONG_PTR)GetPropA(content, "__wine_x11_whole_window"),
                   (unsigned long)GetWindowLongA(content, GWL_EXSTYLE),
                   rect.right - rect.left, rect.bottom - rect.top);
            fflush(stdout);
        }
        else if (!strcmp(command, "peer"))
        {
            ShowWindow(peer, SW_SHOW);
            SetWindowPos(peer, HWND_TOP, 400, 300, 200, 200, SWP_NOACTIVATE);
            UpdateWindow(peer);
        }
        else if (!strcmp(command, "quit")) PostQuitMessage(0);
        else
        {
            DWORD ex = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE;
            DWORD style = WS_POPUP;
            int size = !strcmp(command, "zero") ? 0 : 200;
            BOOL decoration = !strcmp(command, "decoration");
            if (content) DestroyWindow(content);
            ShowWindow(peer, SW_HIDE);
            if (decoration || !strcmp(command, "content")) style |= WS_THICKFRAME;
            if (!strcmp(command, "topmost")) ex |= WS_EX_TOPMOST;
            content = CreateWindowExA(ex, decoration ? "FrameRoleDecoration" : "FrameRoleContent", command,
                                      style, 400, 300, size, size, owner, NULL, GetModuleHandleA(NULL),
                                      (void *)(ULONG_PTR)RGB(0, 0, 255));
            SetLayeredWindowAttributes(content, 0, 255, LWA_ALPHA);
            ShowWindow(content, SW_SHOWNOACTIVATE);
            UpdateWindow(content);
            ++sequence;
        }
        free(command);
        return 0;
    }
    return DefWindowProcA(hwnd, msg, wp, lp);
}
static DWORD WINAPI commands(void *unused)
{
    char line[40];
    (void)unused;
    while (fgets(line, sizeof(line), stdin))
    {
        line[strcspn(line, "\r\n")] = 0;
        char *copy = strdup(line);
        if (!PostMessageA(owner, WM_APP, 0, (LPARAM)copy)) { free(copy); break; }
        if (!strcmp(line, "quit")) break;
    }
    return 0;
}
int main(void)
{
    WNDCLASSA wc = {0};
    MSG msg;
    SetProcessDPIAware();
    wc.lpfnWndProc = proc;
    wc.hInstance = GetModuleHandleA(NULL);
    wc.lpszClassName = "FrameRoleContent";
    RegisterClassA(&wc);
    wc.lpszClassName = "FrameRoleDecoration";
    RegisterClassA(&wc);
    owner = CreateWindowExA(0, "FrameRoleContent", "frame owner", WS_POPUP | WS_THICKFRAME,
                            300, 200, 640, 500, NULL, NULL, wc.hInstance, (void *)(ULONG_PTR)RGB(255, 255, 255));
    peer = CreateWindowExA(0, "FrameRoleContent", "unrelated peer", WS_POPUP | WS_THICKFRAME,
                           400, 300, 200, 200, NULL, NULL, wc.hInstance, (void *)(ULONG_PTR)RGB(255, 0, 0));
    ShowWindow(owner, SW_SHOW);
    UpdateWindow(owner);
    puts("{\"ready\":true}"); fflush(stdout);
    CreateThread(NULL, 0, commands, NULL, 0, NULL);
    while (GetMessageA(&msg, NULL, 0, 0) > 0) { TranslateMessage(&msg); DispatchMessageA(&msg); }
    return 0;
}
