#define _WIN32_WINNT 0x0a00
#include <windows.h>
#include <shellscalingapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>

static const WCHAR *room_title;
static HWND meeting;
static unsigned int matches;

static BOOL has_image(HWND window, const WCHAR *image)
{
    DWORD pid, count = MAX_PATH;
    WCHAR path[MAX_PATH];
    GetWindowThreadProcessId(window, &pid);
    HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    if (!process) return FALSE;
    BOOL ok = QueryFullProcessImageNameW(process, 0, path, &count);
    CloseHandle(process);
    if (!ok) return FALSE;
    const WCHAR *base = wcsrchr(path, L'\\');
    return !_wcsicmp(base ? base + 1 : path, image);
}

static BOOL CALLBACK find_meeting(HWND window, LPARAM unused)
{
    WCHAR title[512];
    (void)unused;
    if (!IsWindowVisible(window) || (GetWindowLongPtrW(window, GWL_EXSTYLE) & WS_EX_TOOLWINDOW)) return TRUE;
    if (has_image(window, L"wwmapp.exe") && GetWindowTextW(window, title, ARRAYSIZE(title)) &&
        wcsstr(title, room_title))
    {
        meeting = window;
        ++matches;
    }
    return TRUE;
}

static unsigned int visible_rooms(void)
{
    meeting = NULL;
    matches = 0;
    EnumWindows(find_meeting, 0);
    return matches;
}

static int check_window(HWND window, HMONITOR origin, int width, int height, UINT output_dpi, const char *phase,
                        const WCHAR *expected_device)
{
    MONITORINFOEXW info = {.cbSize = sizeof(info)};
    MONITORINFO from = {.cbSize = sizeof(from)};
    HMONITOR target = MonitorFromWindow(window, MONITOR_DEFAULTTONULL);
    RECT rect, client;
    UINT dpi_x, dpi_y, window_dpi = GetDpiForWindow(window);
    if (!window_dpi || !GetWindowRect(window, &rect) || !GetClientRect(window, &client)) return 2;
    if (!target)
    {
        printf("{\"phase\":\"%s\",\"monitor\":null,\"window_dpi\":%u,\"window_origin_px\":[%ld,%ld]}\n",
               phase, window_dpi, rect.left, rect.top);
        fflush(stdout);
        return 1;
    }
    if (!GetMonitorInfoW(target, (MONITORINFO *)&info) || !GetMonitorInfoW(origin, &from) ||
        FAILED(GetDpiForMonitor(target, MDT_EFFECTIVE_DPI, &dpi_x, &dpi_y)) || !dpi_x || !dpi_y)
    {
        fprintf(stderr, "Could not measure the meeting at %s (monitor=%p, window DPI=%u).\n", phase,
                (void *)target, window_dpi);
        return 2;
    }
    LONG w = rect.right - rect.left, h = rect.bottom - rect.top;
    BOOL same = origin == target && (!expected_device || !wcscmp(info.szDevice, expected_device));
    BOOL native = window_dpi == dpi_x && window_dpi == dpi_y;
    const RECT *bounds = &from.rcMonitor;
    BOOL fits_x = w <= bounds->right - bounds->left, fits_y = h <= bounds->bottom - bounds->top;
    BOOL placed = same && (!fits_x || (rect.left >= bounds->left && rect.right <= bounds->right)) &&
                          (!fits_y || (rect.top >= bounds->top && rect.bottom <= bounds->bottom));
    BOOL output_ok = !output_dpi || (dpi_x == output_dpi && dpi_y == output_dpi);
    BOOL size = labs(w - MulDiv(width, output_dpi ? output_dpi : dpi_x, 96)) <= 1 &&
                labs(h - MulDiv(height, output_dpi ? output_dpi : dpi_y, 96)) <= 1;
    printf("{\"phase\":\"%s\",\"monitor\":[%ld,%ld,%ld,%ld],\"same_monitor\":%s,"
           "\"placement_ok\":%s,\"expected_output_dpi\":%u,\"output_dpi_ok\":%s,"
           "\"hwnd\":\"0x%llx\",\"client_px\":[%ld,%ld],\"window_dpi\":%u,\"monitor_dpi\":[%u,%u],\"native_dpi\":%s,"
           "\"window_origin_px\":[%ld,%ld],\"window_px\":[%ld,%ld],"
           "\"expected_logical_size\":[%d,%d],\"size_ok\":%s}\n",
           phase, info.rcMonitor.left, info.rcMonitor.top, info.rcMonitor.right, info.rcMonitor.bottom,
           same ? "true" : "false", placed ? "true" : "false", output_dpi,
           !output_dpi ? "null" : (output_ok ? "true" : "false"),
           (unsigned long long)(ULONG_PTR)window, client.right - client.left,
           client.bottom - client.top, window_dpi, dpi_x, dpi_y, native ? "true" : "false",
           rect.left, rect.top, w, h, width, height, size ? "true" : "false");
    fflush(stdout);
    return placed && native && output_ok && size ? 0 : 1;
}

static int dimension(const WCHAR *s)
{
    WCHAR *end;
    long n = wcstol(s, &end, 10);
    return !*end && n > 0 && n <= 32767 ? (int)n : 0;
}

/* Keep the same room open across a host scale change. Monitor handles can change on re-enumeration. */
static int observe_scale_change(HWND room, int width, int height, UINT target_dpi)
{
    MONITORINFOEXW original = {.cbSize = sizeof(original)};
    HMONITOR start = MonitorFromWindow(room, MONITOR_DEFAULTTONULL);
    UINT initial = GetDpiForWindow(room);
    if (!initial || initial == target_dpi || !GetMonitorInfoW(start, (MONITORINFO *)&original))
    {
        fputs("Start the observer before changing the scale to a different DPI.\n", stderr);
        return 2;
    }
    int before = check_window(room, start, width, height, initial, "before-scale", original.szDevice);
    if (before == 2) return 2;

    ULONGLONG deadline = GetTickCount64() + 60000, stable_since = 0;
    RECT last = {0};
    do
    {
        HMONITOR monitor = MonitorFromWindow(room, MONITOR_DEFAULTTONULL);
        RECT rect;
        UINT x, y;
        if (visible_rooms() != 1 || meeting != room || IsZoomed(room) || IsIconic(room))
        {
            fputs("The observed meeting closed, changed or left restored state.\n", stderr);
            return 2;
        }
        BOOL ready = monitor && GetWindowRect(room, &rect) &&
                     SUCCEEDED(GetDpiForMonitor(monitor, MDT_EFFECTIVE_DPI, &x, &y)) &&
                     x == target_dpi && y == target_dpi && GetDpiForWindow(room) == target_dpi;
        if (ready)
        {
            ULONGLONG now = GetTickCount64();
            if (!stable_since || !EqualRect(&last, &rect))
            {
                stable_since = now;
                last = rect;
            }
            else if (now - stable_since >= 1000)
            {
                int after = check_window(room, monitor, width, height, target_dpi, "after-scale", original.szDevice);
                return after ? after : before;
            }
        }
        else stable_since = 0;
        Sleep(50);
    } while (GetTickCount64() < deadline);

    HMONITOR end = MonitorFromWindow(room, MONITOR_DEFAULTTONULL);
    int result = check_window(room, end, width, height, target_dpi, "scale-timeout", original.szDevice);
    fputs("The meeting did not settle at the requested output DPI.\n", stderr);
    return result == 2 ? 2 : 1;
}

int wmain(int argc, WCHAR **argv)
{
    if (argc == 4 && !wcscmp(argv[1], L"--repaint"))
    {
        WCHAR *end;
        unsigned long long value = wcstoull(argv[3], &end, 16);
        UINT_PTR handle = (UINT_PTR)value;
        room_title = argv[2];
        if (!SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2) ||
            !*room_title || !handle || value != handle || *end || visible_rooms() != 1 || meeting != (HWND)handle ||
            IsIconic(meeting) || IsZoomed(meeting))
            return 2;
        RECT client;
        if (!RedrawWindow(meeting, NULL, NULL, RDW_INVALIDATE | RDW_ALLCHILDREN | RDW_UPDATENOW) ||
            !GetClientRect(meeting, &client)) return 2;
        printf("{\"phase\":\"repaint\",\"hwnd\":\"0x%llx\",\"window_dpi\":%u,\"client_px\":[%ld,%ld]}\n",
               (unsigned long long)handle, GetDpiForWindow(meeting), client.right - client.left,
               client.bottom - client.top);
        return 0;
    }
    BOOL wait = argc > 1 && !wcscmp(argv[1], L"--wait");
    BOOL change = argc > 1 && !wcscmp(argv[1], L"--change-dpi");
    if ((argc != 5 && argc != 6) || (!wait && !change && wcscmp(argv[1], L"--snapshot")) ||
        (change && argc != 6) || !*argv[2] || !dimension(argv[3]) || !dimension(argv[4]) ||
        (argc == 6 && !dimension(argv[5])))
    {
        fputs("usage: meeting-display.exe --wait|--snapshot TITLE WIDTH HEIGHT [OUTPUT_DPI]\n"
              "       meeting-display.exe --change-dpi TITLE WIDTH HEIGHT TARGET_DPI\n"
              "       meeting-display.exe --repaint TITLE OBSERVED_HWND\n", stderr);
        return 2;
    }
    room_title = argv[2];
    int width = dimension(argv[3]), height = dimension(argv[4]);
    UINT output_dpi = argc == 6 ? dimension(argv[5]) : 0;
    if (!SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)) return 2;
    if (change)
    {
        if (visible_rooms() != 1 || IsZoomed(meeting) || IsIconic(meeting))
        {
            fputs("A single visible, restored meeting is required before changing the scale.\n", stderr);
            return 2;
        }
        return observe_scale_change(meeting, width, height, output_dpi);
    }
    HWND host = FindWindowW(L"WeWorkWindow", NULL);
    MONITORINFO info = {.cbSize = sizeof(info)};
    HMONITOR origin = MonitorFromWindow(host, MONITOR_DEFAULTTONULL);
    if (!host || !has_image(host, L"WXWork.exe") || !IsWindowVisible(host) || IsIconic(host) ||
        !origin || !GetMonitorInfoW(origin, &info) || GetSystemMetrics(SM_CMONITORS) < 2)
    {
        fputs("A visible WeCom main window and two monitors are required.\n", stderr);
        return 2;
    }
    unsigned int count = visible_rooms();
    if (wait && count)
    {
        fputs("Start --wait before opening the meeting.\n", stderr);
        return 2;
    }
    printf("{\"phase\":\"origin\",\"monitor\":[%ld,%ld,%ld,%ld]}\n", info.rcMonitor.left,
           info.rcMonitor.top, info.rcMonitor.right, info.rcMonitor.bottom);
    fflush(stdout);
    ULONGLONG deadline = GetTickCount64() + 120000;
    while (wait && !count && GetTickCount64() < deadline)
    {
        Sleep(50);
        count = visible_rooms();
    }
    if (count != 1 || IsZoomed(meeting) || IsIconic(meeting))
    {
        fprintf(stderr, "Expected one visible, restored meeting with the specified title (matches=%u).\n", count);
        return 2;
    }
    HWND first = meeting;
    int initial = check_window(first, origin, width, height, output_dpi, wait ? "first-title-match" : "snapshot", NULL);
    if (!wait || initial == 2) return initial;
    Sleep(1000);
    if (visible_rooms() != 1 || meeting != first || IsZoomed(first) || IsIconic(first) ||
        MonitorFromWindow(host, MONITOR_DEFAULTTONULL) != origin)
    {
        fputs("The meeting or the launch window changed during observation.\n", stderr);
        return 2;
    }
    int settled = check_window(first, origin, width, height, output_dpi, "settled", NULL);
    return settled ? settled : initial;
}
