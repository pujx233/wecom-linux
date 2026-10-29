#define _WIN32_WINNT 0x0a00
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>

static HWND window, shadow;
static HMONITOR selected_monitor;
static MONITORINFO selected_info = {.cbSize = sizeof(MONITORINFO)};
static BOOL default_limits, select_primary, custom_offset;
static unsigned int max_proposals;
static BOOL proposal_wrong_monitor;
static RECT first_proposal;

static void state(void)
{
    RECT rect, shadow_rect = {0};
    GetWindowRect(window, &rect);
    if (shadow) GetWindowRect(shadow, &shadow_rect);
    printf("{\"event\":\"state\",\"rect\":[%ld,%ld,%ld,%ld],\"selected_monitor\":%d,\"maximized\":%d,"
           "\"minimized\":%d,"
           "\"body\":%lu,\"frame\":%lu,\"shadow\":%lu,\"shadow_visible\":%d,"
           "\"shadow_rect\":[%ld,%ld,%ld,%ld],\"max_proposals\":%u,\"proposal_wrong_monitor\":%d,"
           "\"first_proposal\":[%ld,%ld,%ld,%ld]}\n", rect.left, rect.top, rect.right, rect.bottom,
           MonitorFromWindow(window, MONITOR_DEFAULTTONEAREST) == selected_monitor, IsZoomed(window),
           IsIconic(window),
           (unsigned long)(ULONG_PTR)GetPropA(window, "__wine_x11_whole_window"),
           (unsigned long)(ULONG_PTR)GetPropA(window, "__wine_x11_wm_window"),
           (unsigned long)(ULONG_PTR)GetPropA(shadow, "__wine_x11_whole_window"), IsWindowVisible(shadow),
           shadow_rect.left, shadow_rect.top, shadow_rect.right, shadow_rect.bottom,
           max_proposals, proposal_wrong_monitor,
           first_proposal.left, first_proposal.top, first_proposal.right, first_proposal.bottom);
    fflush(stdout);
}

static BOOL CALLBACK select_monitor(HMONITOR monitor, HDC dc, RECT *rect, LPARAM context)
{
    MONITORINFO info = {.cbSize = sizeof(info)};
    GetMonitorInfoA(monitor, &info);
    if (!!(info.dwFlags & MONITORINFOF_PRIMARY) == select_primary)
    {
        selected_monitor = monitor;
        selected_info = info;
    }
    (void)dc;
    (void)rect;
    (void)context;
    return TRUE;
}

static LRESULT CALLBACK procedure(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam)
{
    if (message == WM_NCCALCSIZE) return 0;
    if (message == WM_NCHITTEST)
    {
        POINT point = {(short)LOWORD(lparam), (short)HIWORD(lparam)};
        ScreenToClient(hwnd, &point);
        return point.y < 56 ? HTCAPTION : HTCLIENT;
    }
    if (message == WM_WINDOWPOSCHANGING && IsZoomed(hwnd) && !IsIconic(hwnd))
    {
        WINDOWPOS *position = (WINDOWPOS *)lparam;
        if (!(position->flags & SWP_NOMOVE))
        {
            POINT origin = {position->x, position->y};
            RECT proposed;
            GetWindowRect(hwnd, &proposed);
            OffsetRect(&proposed, position->x - proposed.left, position->y - proposed.top);
            if (!(position->flags & SWP_NOSIZE))
            {
                proposed.right = proposed.left + position->cx;
                proposed.bottom = proposed.top + position->cy;
            }
            if (!max_proposals++) first_proposal = proposed;
            proposal_wrong_monitor |= MonitorFromPoint(origin, MONITOR_DEFAULTTONEAREST) != selected_monitor;
        }
    }
    if (message == WM_GETMINMAXINFO && !default_limits)
    {
        MONITORINFO info = {.cbSize = sizeof(info)};
        MINMAXINFO *limits = (MINMAXINFO *)lparam;
        GetMonitorInfoA(MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST), &info);
        limits->ptMaxPosition.x = info.rcWork.left - info.rcMonitor.left;
        limits->ptMaxPosition.y = info.rcWork.top - info.rcMonitor.top;
        if (custom_offset)
        {
            limits->ptMaxPosition.x += 23;
            limits->ptMaxPosition.y += 17;
        }
        limits->ptMaxSize.x = info.rcWork.right - info.rcWork.left;
        limits->ptMaxSize.y = info.rcWork.bottom - info.rcWork.top;
        return 0;
    }
    if ((message == WM_SIZE || message == WM_MOVE) && shadow)
    {
        RECT rect;
        GetWindowRect(hwnd, &rect);
        SetWindowPos(shadow, HWND_BOTTOM, rect.left - 8, rect.top - 8,
                     rect.right - rect.left + 16, rect.bottom - rect.top + 16,
                     SWP_NOACTIVATE | SWP_SHOWWINDOW);
    }
    if (message == WM_PAINT)
    {
        PAINTSTRUCT paint;
        HDC dc = BeginPaint(hwnd, &paint);
        FillRect(dc, &paint.rcPaint, (HBRUSH)(COLOR_WINDOW + 1));
        EndPaint(hwnd, &paint);
        return 0;
    }
    if (message == WM_APP)
    {
        if (wparam != 's')
        {
            max_proposals = 0;
            proposal_wrong_monitor = FALSE;
            SetRectEmpty(&first_proposal);
        }
        if (wparam == 'm') ShowWindow(hwnd, SW_MAXIMIZE);
        else if (wparam == 'i') ShowWindow(hwnd, SW_MINIMIZE);
        else if (wparam == 'r') ShowWindow(hwnd, SW_RESTORE);
        else if (wparam == 'a' && IsIconic(hwnd)) ShowWindow(hwnd, SW_RESTORE);
        else if (wparam == 'c')
        {
            ShowWindow(hwnd, SW_MINIMIZE);
            ShowWindow(hwnd, SW_RESTORE);
        }
        else if (wparam == 's') state();
        else if (wparam == 'q') PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcA(hwnd, message, wparam, lparam);
}

static DWORD WINAPI commands(void *unused)
{
    char line[32];
    while (fgets(line, sizeof(line), stdin))
        PostMessageA(window, WM_APP, line[0], 0);
    (void)unused;
    return 0;
}

int main(int argc, char **argv)
{
    WNDCLASSA body = {.lpfnWndProc = procedure, .hInstance = GetModuleHandleA(NULL),
                     .lpszClassName = "MaximizeRegression"};
    WNDCLASSA border = {.lpfnWndProc = DefWindowProcA, .hInstance = body.hInstance,
                       .lpszClassName = "MaximizeRegressionShadow"};
    MSG message;
    if (argc != 6) return 2;
    select_primary = atoi(argv[1]) != 0;
    default_limits = atoi(argv[3]) == 1;
    custom_offset = atoi(argv[3]) == 2;
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    if (GetSystemMetrics(SM_CMONITORS) != 2) return 3;
    EnumDisplayMonitors(NULL, NULL, select_monitor, 0);
    if (!selected_monitor) return 4;
    RegisterClassA(&body);
    RegisterClassA(&border);
    window = CreateWindowExA(0, body.lpszClassName, "Dual monitor maximize regression",
                             (atoi(argv[5]) ? WS_OVERLAPPED : WS_POPUP) |
                             WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU,
                             atoi(argv[4]) ? selected_info.rcWork.right - 1200 : selected_info.rcWork.left + 200,
                             selected_info.rcWork.top + 200,
                             1000, 700, NULL, NULL, body.hInstance, NULL);
    if (atoi(argv[2]))
    {
        shadow = CreateWindowExA(WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT,
                                border.lpszClassName, "", WS_POPUP, 0, 0, 1, 1,
                                window, NULL, body.hInstance, NULL);
        SetLayeredWindowAttributes(shadow, 0, 100, LWA_ALPHA);
    }
    ShowWindow(window, SW_SHOW);
    printf("{\"event\":\"ready\",\"monitor\":[%ld,%ld,%ld,%ld],\"work\":[%ld,%ld,%ld,%ld],"
           "\"virtual_origin\":[%d,%d]}\n",
           selected_info.rcMonitor.left, selected_info.rcMonitor.top,
           selected_info.rcMonitor.right, selected_info.rcMonitor.bottom,
           selected_info.rcWork.left, selected_info.rcWork.top,
           selected_info.rcWork.right, selected_info.rcWork.bottom,
           GetSystemMetrics(SM_XVIRTUALSCREEN), GetSystemMetrics(SM_YVIRTUALSCREEN));
    fflush(stdout);
    CloseHandle(CreateThread(NULL, 0, commands, NULL, 0, NULL));
    while (GetMessageA(&message, NULL, 0, 0) > 0)
    {
        TranslateMessage(&message);
        DispatchMessageA(&message);
    }
    if (shadow) DestroyWindow(shadow);
    DestroyWindow(window);
    return 0;
}
