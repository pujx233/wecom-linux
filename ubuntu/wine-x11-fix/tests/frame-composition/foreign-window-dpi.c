#define _WIN32_WINNT 0x0a00
#include <windows.h>
#include <shellscalingapi.h>
#include <stdio.h>
#include <stdlib.h>

static HWND foreign;
static const WCHAR *device;
static int checked;

static BOOL CALLBACK inspect(HMONITOR monitor, HDC dc, LPRECT bounds, LPARAM arg)
{
    MONITORINFOEXW info = {.cbSize = sizeof(info)};
    UINT dpi_x, dpi_y;
    RECT actual;
    (void)dc;
    (void)bounds;
    (void)arg;
    if (!GetMonitorInfoW(monitor, (MONITORINFO *)&info)) return FALSE;
    if (wcscmp(device, info.szDevice)) return TRUE;
    if (FAILED(GetDpiForMonitor(monitor, MDT_EFFECTIVE_DPI, &dpi_x, &dpi_y)) || !GetWindowRect(foreign, &actual))
        return FALSE;
    RECT expected = {info.rcMonitor.left + MulDiv(64, dpi_x, 96), info.rcMonitor.top + MulDiv(64, dpi_y, 96),
                     info.rcMonitor.left + MulDiv(192, dpi_x, 96), info.rcMonitor.top + MulDiv(160, dpi_y, 96)};
    BOOL same = MonitorFromWindow(foreign, MONITOR_DEFAULTTONULL) == monitor;
    printf("foreign rect %ld,%ld,%ld,%ld expected %ld,%ld,%ld,%ld same monitor %d\n",
           actual.left, actual.top, actual.right, actual.bottom, expected.left, expected.top,
           expected.right, expected.bottom, same);
    checked = same && EqualRect(&actual, &expected);
    return FALSE;
}

static BOOL CALLBACK create_on_monitor(HMONITOR monitor, HDC dc, LPRECT bounds, LPARAM aware_owner)
{
    MONITORINFOEXW info = {.cbSize = sizeof(info)};
    PROCESS_INFORMATION process;
    STARTUPINFOW startup = {.cb = sizeof(startup)};
    WCHAR path[MAX_PATH], command[2 * MAX_PATH];
    DWORD status = 1;
    UINT dpi_x, dpi_y;
    (void)dc;
    (void)bounds;
    if (!GetMonitorInfoW(monitor, (MONITORINFO *)&info) || !GetModuleFileNameW(NULL, path, ARRAYSIZE(path)) ||
        FAILED(GetDpiForMonitor(monitor, MDT_EFFECTIVE_DPI, &dpi_x, &dpi_y)))
        return FALSE;
    HWND window = CreateWindowExW(0, L"STATIC", L"", WS_POPUP, info.rcMonitor.left + MulDiv(64, dpi_x, 96),
                                  info.rcMonitor.top + MulDiv(64, dpi_y, 96), MulDiv(128, dpi_x, 96),
                                  MulDiv(96, dpi_y, 96), NULL, NULL, NULL, NULL);
    if (!window) return FALSE;
    swprintf(command, ARRAYSIZE(command), L"\"%ls\" %ls %lu %ls", path, aware_owner ? L"unaware" : L"per-monitor",
             (DWORD)(ULONG_PTR)window, info.szDevice);
    if (CreateProcessW(path, command, NULL, NULL, TRUE, 0, NULL, NULL, &startup, &process))
    {
        if (WaitForSingleObject(process.hProcess, 5000) == WAIT_OBJECT_0)
            GetExitCodeProcess(process.hProcess, &status);
        else
        {
            TerminateProcess(process.hProcess, 2);
            WaitForSingleObject(process.hProcess, 5000);
        }
        CloseHandle(process.hThread);
        CloseHandle(process.hProcess);
    }
    DestroyWindow(window);
    if (status) return FALSE;
    ++checked;
    return TRUE;
}

int wmain(int argc, WCHAR **argv)
{
    const WCHAR *mode = argc > 1 ? argv[1] : L"unaware";
    BOOL aware = !wcscmp(mode, L"per-monitor");
    if ((argc != 1 && argc != 2 && argc != 4) || (!aware && wcscmp(mode, L"unaware"))) return 2;
    if (!SetProcessDpiAwarenessContext(aware ? DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 :
                                              DPI_AWARENESS_CONTEXT_UNAWARE)) return 2;
    if (argc == 4)
    {
        foreign = (HWND)(ULONG_PTR)wcstoul(argv[2], NULL, 10);
        device = argv[3];
        EnumDisplayMonitors(NULL, NULL, inspect, 0);
        return !checked;
    }
    EnumDisplayMonitors(NULL, NULL, create_on_monitor, aware);
    return checked == 2 ? 0 : 1;
}
