#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static HWND main_window, card, sentinel, preview, peer, helper;
static BOOL foreign;
static unsigned card_clicks, main_clicks;

static unsigned long frame(HWND hwnd)
{
    return (unsigned long)(ULONG_PTR)GetPropA(hwnd, "__wine_x11_wm_window");
}

static void state(const char *event)
{
    HWND hwnd;
    int card_index = -1, main_index = -1, i = 0;
    for (hwnd = GetTopWindow(NULL); hwnd; hwnd = GetWindow(hwnd, GW_HWNDNEXT), ++i)
    {
        if (hwnd == card) card_index = i;
        if (hwnd == main_window) main_index = i;
    }
    printf("{\"event\":\"%s\",\"main\":%lu,\"card\":%lu,\"sentinel\":%lu,\"active\":%lu,"
           "\"card_above_main\":%d,\"card_owner\":%llu,\"card_exstyle\":%lu,\"main_maximized\":%d,"
           "\"preview\":%lu,\"card_clicks\":%u,\"main_clicks\":%u,\"peer_minimized\":%d,"
           "\"helper\":%lu,\"helper_owner\":%llu,\"helper_style\":%lu,\"helper_exstyle\":%lu,\"order\":[",
           event, frame(main_window), frame(card), frame(sentinel), frame(GetForegroundWindow()),
           card_index >= 0 && card_index < main_index, (unsigned long long)(ULONG_PTR)GetWindow(card, GW_OWNER),
           (unsigned long)GetWindowLongA(card, GWL_EXSTYLE), IsZoomed(main_window), frame(preview),
           card_clicks, main_clicks, IsIconic(peer), frame(helper),
           (unsigned long long)(ULONG_PTR)GetWindow(helper, GW_OWNER),
           (unsigned long)GetWindowLongA(helper, GWL_STYLE), (unsigned long)GetWindowLongA(helper, GWL_EXSTYLE));
    for (hwnd = GetTopWindow(NULL), i = 0; hwnd; hwnd = GetWindow(hwnd, GW_HWNDNEXT))
    {
        unsigned long window = frame(hwnd);
        if (window) printf("%s%lu", i++ ? "," : "", window);
    }
    puts("]}");
    fflush(stdout);
}

static LRESULT CALLBACK proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    if (msg == WM_NCCREATE)
        SetWindowLongPtrA(hwnd, GWLP_USERDATA, (LONG_PTR)((CREATESTRUCTA *)lp)->lpCreateParams);
    if (msg == WM_NCCALCSIZE) return 0;
    if (msg == WM_MOUSEACTIVATE && hwnd == card) return MA_NOACTIVATE;
    if (msg == WM_LBUTTONDOWN)
    {
        if (hwnd == card) ++card_clicks;
        if (hwnd == main_window) ++main_clicks;
    }
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
        if (!strcmp(command, "show"))
        {
            if (!card)
                card = CreateWindowExA(WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW, "CardStack", "no-activate card",
                                       WS_POPUP | WS_CLIPSIBLINGS | WS_CLIPCHILDREN | WS_MINIMIZEBOX,
                                       400, 300, 240, 240, NULL, NULL, GetModuleHandleA(NULL),
                                       (void *)(ULONG_PTR)RGB(0, 0, 255));
            SetWindowPos(card, HWND_TOP, 400, 300, 240, 240, SWP_NOACTIVATE | SWP_SHOWWINDOW);
            UpdateWindow(card);
        }
        else if (!strcmp(command, "hide")) ShowWindow(card, SW_HIDE);
        else if (!strcmp(command, "maximize")) ShowWindow(main_window, SW_MAXIMIZE);
        else if (!strcmp(command, "restore")) ShowWindow(main_window, SW_RESTORE);
        else if (!strcmp(command, "activate")) SetForegroundWindow(main_window);
        else if (!strcmp(command, "reshow-main"))
        {
            ShowWindow(main_window, SW_HIDE);
            ShowWindow(main_window, SW_SHOWNOACTIVATE);
        }
        else if (!strcmp(command, "helper"))
        {
            ShowWindow(card, SW_HIDE);
            ShowWindow(preview, SW_HIDE);
            if (!helper)
            {
                helper = CreateWindowExA(WS_EX_NOACTIVATE | WS_EX_LAYERED | WS_EX_TOOLWINDOW,
                                         "CardStack", "normal helper", WS_POPUP, 10, 12, 1, 1,
                                         NULL, NULL, GetModuleHandleA(NULL), NULL);
                SetLayeredWindowAttributes(helper, 0, 255, LWA_ALPHA);
            }
            SetWindowPos(helper, HWND_TOP, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW);
            UpdateWindow(helper);
        }
        else if (!strcmp(command, "repaint"))
        {
            InvalidateRect(card, NULL, FALSE);
            UpdateWindow(card);
        }
        else if (!strcmp(command, "owned") || !strcmp(command, "unowned"))
        {
            HWND owner = !strcmp(command, "owned") ? main_window : NULL;
            if (preview) DestroyWindow(preview);
            DestroyWindow(card);
            card = CreateWindowExA(WS_EX_NOACTIVATE, "CardStack", "owned card", WS_POPUP | WS_THICKFRAME,
                                   400, 300, 240, 240, owner, NULL, GetModuleHandleA(NULL),
                                   (void *)(ULONG_PTR)RGB(0, 0, 255));
            SetWindowPos(card, HWND_TOP, 400, 300, 240, 240, SWP_NOACTIVATE | SWP_SHOWWINDOW);
            UpdateWindow(card);
            preview = CreateWindowExA(WS_EX_NOACTIVATE, "CardStack", "owned preview", WS_POPUP | WS_THICKFRAME,
                                      400, 300, 240, 240, owner, NULL, GetModuleHandleA(NULL),
                                      (void *)(ULONG_PTR)RGB(0, 255, 0));
            SetWindowPos(preview, HWND_TOP, 400, 300, 240, 240, SWP_NOACTIVATE | SWP_SHOWWINDOW);
            UpdateWindow(preview);
        }
        else if (!strcmp(command, "minimize-peer"))
        {
            ShowWindow(card, SW_HIDE);
            peer = CreateWindowExA(WS_EX_NOACTIVATE, "CardStack", "minimized peer", WS_POPUP | WS_THICKFRAME,
                                   450, 350, 240, 240, NULL, NULL, GetModuleHandleA(NULL), NULL);
            ShowWindow(peer, SW_SHOWMINNOACTIVE);
            SetWindowPos(peer, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
        }
        else if (!strcmp(command, "state")) state("state");
        else if (!strcmp(command, "quit")) PostQuitMessage(0);
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
        char *copy;
        line[strcspn(line, "\r\n")] = 0;
        copy = strdup(line);
        if (!PostMessageA(main_window, WM_APP, 0, (LPARAM)copy)) { free(copy); break; }
        if (!strcmp(line, "quit")) break;
    }
    return 0;
}

int main(int argc, char **argv)
{
    WNDCLASSA wc = {0};
    MSG msg;
    foreign = argc > 1 && !strcmp(argv[1], "foreign");
    SetProcessDPIAware();
    wc.lpfnWndProc = proc;
    wc.hInstance = GetModuleHandleA(NULL);
    wc.lpszClassName = "CardStack";
    RegisterClassA(&wc);
    main_window = CreateWindowExA(0, "CardStack", foreign ? "foreign app" : "card main",
                                  WS_POPUP | WS_THICKFRAME, foreign ? 400 : 300, foreign ? 300 : 200,
                                  foreign ? 240 : 640, foreign ? 240 : 500, NULL, NULL, wc.hInstance,
                                  (void *)(ULONG_PTR)(foreign ? RGB(255, 0, 0) : RGB(255, 255, 255)));
    ShowWindow(main_window, SW_SHOW);
    UpdateWindow(main_window);
    if (!foreign)
    {
        sentinel = CreateWindowExA(WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, "CardStack", "sentinel",
                                   WS_POPUP, 10, 10, 1, 1, NULL, NULL, wc.hInstance, NULL);
        ShowWindow(sentinel, SW_SHOWNOACTIVATE);
    }
    state("ready");
    CreateThread(NULL, 0, commands, NULL, 0, NULL);
    while (GetMessageA(&msg, NULL, 0, 0) > 0) { TranslateMessage(&msg); DispatchMessageA(&msg); }
    return 0;
}
