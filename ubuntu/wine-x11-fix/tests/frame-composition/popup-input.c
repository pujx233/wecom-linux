#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>

static HWND window, previews[2];
static void state(const char *event)
{
    HWND current;
    int top = -1;
    for (current = GetTopWindow(NULL); current; current = GetWindow(current, GW_HWNDNEXT))
    {
        if (current == previews[0]) { top = 0; break; }
        if (current == previews[1]) { top = 1; break; }
    }
    printf("{\"event\":\"%s\",\"body\":%lu,\"frame\":%lu,\"top_preview\":%d}\n", event,
           (unsigned long)(ULONG_PTR)GetPropA(window, "__wine_x11_whole_window"),
           (unsigned long)(ULONG_PTR)GetPropA(window, "__wine_x11_wm_window"), top);
    fflush(stdout);
}
static LRESULT CALLBACK proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    if (msg == WM_NCCREATE)
        SetWindowLongPtrA(hwnd, GWLP_USERDATA, (LONG_PTR)((CREATESTRUCTA *)lp)->lpCreateParams);
    if (msg == WM_NCCALCSIZE) return 0;
    if (msg == WM_PAINT)
    {
        PAINTSTRUCT ps;
        HDC dc = BeginPaint(hwnd, &ps);
        LONG_PTR color = GetWindowLongPtrA(hwnd, GWLP_USERDATA);
        HBRUSH brush = CreateSolidBrush(color == 1 ? RGB(0, 0, 255) :
                                       color == 2 ? RGB(255, 0, 0) : RGB(255, 255, 255));
        FillRect(dc, &ps.rcPaint, brush);
        DeleteObject(brush);
        EndPaint(hwnd, &ps);
        return 0;
    }
    if (msg == WM_MOUSEACTIVATE) return MA_ACTIVATE;
    if (msg == WM_LBUTTONDOWN)
    {
        /* Some non-activating cards explicitly request focus after their first press. */
        LONG ex_style = GetWindowLongA(hwnd, GWL_EXSTYLE);
        SetWindowLongA(hwnd, GWL_EXSTYLE, ex_style & ~WS_EX_NOACTIVATE);
        SetWindowPos(hwnd, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE);
        SetForegroundWindow(hwnd);
        SetActiveWindow(hwnd);
        SetWindowLongA(hwnd, GWL_EXSTYLE, ex_style);
        state("down"); return 0;
    }
    if (msg == WM_LBUTTONUP) { state("up"); return 0; }
    if (msg == WM_APP) { state("state"); return 0; }
    if (msg == WM_APP + 1 || msg == WM_APP + 2)
    {
        unsigned int index = msg - WM_APP - 1;
        HWND preview = CreateWindowExA(WS_EX_TOOLWINDOW, "PopupInputRegression", "owned preview",
                                       WS_POPUP | WS_THICKFRAME, 450, 300, 200, 200, hwnd,
                                       NULL, GetModuleHandleA(NULL), (void *)(ULONG_PTR)(index + 1));
        HWND decoration;
        previews[index] = preview;
        ShowWindow(preview, SW_SHOW);
        UpdateWindow(preview);
        decoration = CreateWindowExA(WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW,
                                      "PopupInputRegression", "preview decoration", WS_POPUP | WS_SYSMENU,
                                      450, 300, 200, 20, preview, NULL, GetModuleHandleA(NULL), NULL);
        SetLayeredWindowAttributes(decoration, 0, 255, LWA_ALPHA);
        ShowWindow(decoration, SW_SHOWNOACTIVATE);
        UpdateWindow(decoration);
        printf("{\"event\":\"preview\",\"index\":%u,\"body\":%lu,\"frame\":%lu}\n", index,
               (unsigned long)(ULONG_PTR)GetPropA(preview, "__wine_x11_whole_window"),
               (unsigned long)(ULONG_PTR)GetPropA(preview, "__wine_x11_wm_window"));
        fflush(stdout);
        return 0;
    }
    if (msg == WM_APP + 3 || msg == WM_APP + 4)
    {
        unsigned int index = msg - WM_APP - 3;
        SetWindowPos(previews[index], HWND_TOP, 0, 0, 0, 0,
                     SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
        printf("{\"event\":\"stack\",\"index\":%u}\n", index);
        fflush(stdout);
        return 0;
    }
    if (msg == WM_DESTROY) { PostQuitMessage(0); return 0; }
    return DefWindowProcA(hwnd, msg, wp, lp);
}
static DWORD WINAPI commands(void *unused)
{
    char line[40];
    while (fgets(line, sizeof(line), stdin))
    {
        if (line[0] == 's') PostMessageA(window, WM_APP, 0, 0);
        else if (line[0] == 'p') PostMessageA(window, WM_APP + 1, 0, 0);
        else if (line[0] == 'r') PostMessageA(window, WM_APP + 2, 0, 0);
        else if (line[0] == 'b') PostMessageA(window, WM_APP + 3, 0, 0);
        else if (line[0] == 't') PostMessageA(window, WM_APP + 4, 0, 0);
        else { PostMessageA(window, WM_CLOSE, 0, 0); break; }
    }
    (void)unused;
    return 0;
}
int main(int argc, char **argv)
{
    WNDCLASSA wc = {0};
    MSG msg;
    DWORD ex = WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW;
    SetProcessDPIAware();
    if (argc > 1) ex |= strtoul(argv[1], NULL, 16);
    wc.lpfnWndProc = proc;
    wc.hInstance = GetModuleHandleA(NULL);
    wc.lpszClassName = "PopupInputRegression";
    RegisterClassA(&wc);
    {
        HWND peer = CreateWindowExA(0, wc.lpszClassName, "foreground peer", WS_OVERLAPPEDWINDOW,
                                    40, 40, 200, 120, NULL, NULL, wc.hInstance, NULL);
        ShowWindow(peer, SW_SHOW);
        SetForegroundWindow(peer);
    }
    window = CreateWindowExA(ex, wc.lpszClassName, "popup input regression",
                             WS_POPUP | WS_CLIPCHILDREN | WS_CLIPSIBLINGS | WS_GROUP,
                             300, 200, 640, 500, NULL, NULL, wc.hInstance, NULL);
    if (ex & WS_EX_LAYERED) SetLayeredWindowAttributes(window, 0, 255, LWA_ALPHA);
    ShowWindow(window, SW_SHOWNOACTIVATE);
    UpdateWindow(window);
    state("ready");
    CreateThread(NULL, 0, commands, NULL, 0, NULL);
    while (GetMessageA(&msg, NULL, 0, 0) > 0) { TranslateMessage(&msg); DispatchMessageA(&msg); }
    return 0;
}
