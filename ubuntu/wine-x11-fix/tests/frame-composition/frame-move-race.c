#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <string.h>

static HWND owner, overlay;
static HANDLE resume_owner;
static int overlay_x = 184, overlay_y = 184;

static void state(const char *event)
{
    RECT parent = {0}, child = {0};
    GetWindowRect(owner, &parent);
    GetWindowRect(overlay, &child);
    printf("{\"event\":\"%s\",\"owner\":[%ld,%ld,%ld,%ld],\"overlay\":[%ld,%ld,%ld,%ld],"
           "\"owner_body\":%lu,\"body\":%lu,\"frame\":%lu,\"overlay_frame\":%lu}\n", event,
           parent.left, parent.top, parent.right, parent.bottom, child.left, child.top, child.right, child.bottom,
           (unsigned long)(ULONG_PTR)GetPropA(owner, "__wine_x11_whole_window"),
           (unsigned long)(ULONG_PTR)GetPropA(overlay, "__wine_x11_whole_window"),
           (unsigned long)(ULONG_PTR)GetPropA(owner, "__wine_x11_wm_window"),
           (unsigned long)(ULONG_PTR)GetPropA(overlay, "__wine_x11_wm_window"));
}

static LRESULT CALLBACK proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    if (msg == WM_NCCALCSIZE) return 0;
    if (msg == WM_PAINT)
    {
        ValidateRect(hwnd, NULL);
        return 0;
    }
    if (msg == WM_APP)
    {
        state("paused");
        if (WaitForSingleObject(resume_owner, 10000) != WAIT_OBJECT_0) ExitProcess(4);
        state("resumed");
        return 0;
    }
    if (msg == WM_APP + 1)
    {
        if (!SetWindowPos(overlay, NULL, (LONG)wp, (LONG)lp, 0, 0,
                          SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)) ExitProcess(5);
        state("moved");
        return 0;
    }
    if (msg == WM_APP + 2)
    {
        state(hwnd == owner ? "owner-state" : "overlay-state");
        return 0;
    }
    if (msg == WM_APP + 3)
    {
        if (!SetWindowPos(owner, NULL, (LONG)wp, (LONG)lp, 0, 0,
                          SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)) ExitProcess(5);
        state("owner-moved");
        return 0;
    }
    if (msg == WM_DESTROY)
    {
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcA(hwnd, msg, wp, lp);
}

static DWORD WINAPI overlay_thread(void *unused)
{
    WNDCLASSA wc = {0};
    MSG msg;
    (void)unused;
    wc.lpfnWndProc = proc;
    wc.hInstance = GetModuleHandleA(NULL);
    wc.lpszClassName = "MoveRaceOverlay";
    if (!RegisterClassA(&wc)) ExitProcess(2);
    overlay = CreateWindowExA(WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
                              wc.lpszClassName, "synthetic overlay", WS_POPUP,
                              overlay_x, overlay_y, 532, 432, owner, NULL, wc.hInstance, NULL);
    if (!overlay) ExitProcess(3);
    SetLayeredWindowAttributes(overlay, 0, 255, LWA_ALPHA);
    ShowWindow(overlay, SW_SHOWNOACTIVATE);
    UpdateWindow(overlay);
    state("ready");
    while (GetMessageA(&msg, NULL, 0, 0) > 0)
    {
        TranslateMessage(&msg);
        DispatchMessageA(&msg);
    }
    return 0;
}

static DWORD WINAPI commands(void *unused)
{
    char line[80];
    int x, y;
    (void)unused;
    while (fgets(line, sizeof(line), stdin))
    {
        if (!strncmp(line, "pause", 5)) PostMessageA(owner, WM_APP, 0, 0);
        else if (!strncmp(line, "resume", 6)) SetEvent(resume_owner);
        else if (sscanf(line, "move-owner %d %d", &x, &y) == 2) PostMessageA(owner, WM_APP + 3, x, y);
        else if (sscanf(line, "create %d %d", &x, &y) == 2)
        {
            overlay_x = x;
            overlay_y = y;
            CreateThread(NULL, 0, overlay_thread, NULL, 0, NULL);
        }
        else if (sscanf(line, "move %d %d", &x, &y) == 2) PostMessageA(overlay, WM_APP + 1, x, y);
        else if (!strncmp(line, "owner-state", 11)) PostMessageA(owner, WM_APP + 2, 0, 0);
        else if (!strncmp(line, "state", 5)) PostMessageA(overlay, WM_APP + 2, 0, 0);
        else if (!strncmp(line, "quit", 4))
        {
            SetEvent(resume_owner);
            PostMessageA(overlay, WM_CLOSE, 0, 0);
            PostMessageA(owner, WM_CLOSE, 0, 0);
            break;
        }
    }
    return 0;
}

int main(int argc, char **argv)
{
    WNDCLASSA wc = {0};
    MSG msg;
    if (argc > 2 || (argc == 2 && strcmp(argv[1], "defer-overlay"))) return 1;
    setvbuf(stdout, NULL, _IONBF, 0);
    SetProcessDPIAware();
    resume_owner = CreateEventA(NULL, FALSE, FALSE, NULL);
    wc.lpfnWndProc = proc;
    wc.hInstance = GetModuleHandleA(NULL);
    wc.lpszClassName = "MoveRaceOwner";
    if (!resume_owner || !RegisterClassA(&wc)) return 2;
    owner = CreateWindowExA(0, wc.lpszClassName, "synthetic owner", WS_POPUP | WS_THICKFRAME,
                            200, 200, 500, 400, NULL, NULL, wc.hInstance, NULL);
    if (!owner) return 3;
    ShowWindow(owner, SW_SHOW);
    UpdateWindow(owner);
    if (argc == 2) state("owner-ready");
    else CreateThread(NULL, 0, overlay_thread, NULL, 0, NULL);
    CreateThread(NULL, 0, commands, NULL, 0, NULL);
    while (GetMessageA(&msg, NULL, 0, 0) > 0)
    {
        TranslateMessage(&msg);
        DispatchMessageA(&msg);
    }
    return 0;
}
