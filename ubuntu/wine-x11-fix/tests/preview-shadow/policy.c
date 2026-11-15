#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static HWND main_window, foreign_owner, foreign_shadow;
static BOOL foreign_process, burst_ready, delayed;
static unsigned checks, failures;

static void check(BOOL passed, const char *name)
{
    ++checks;
    if (!passed) { ++failures; fprintf(stderr, "Failed: %s\n", name); }
}

static LRESULT CALLBACK procedure(HWND window, UINT message, WPARAM wp, LPARAM lp)
{
    if (message == WM_STYLECHANGING && burst_ready && !delayed)
    {
        /* A busy application thread lets SHOW events reenter the waiting helper. */
        delayed = TRUE;
        Sleep(750);
    }
    if (message == WM_APP + 1)
    {
        foreign_owner = (HWND)wp;
        foreign_shadow = (HWND)lp;
        return 0;
    }
    if (message == WM_CLOSE)
    {
        DestroyWindow(window);
        if (foreign_process) PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcA(window, message, wp, lp);
}

static void pump(unsigned milliseconds)
{
    DWORD start = GetTickCount();
    do
    {
        MSG message;
        while (PeekMessageA(&message, NULL, 0, 0, PM_REMOVE))
        {
            TranslateMessage(&message);
            DispatchMessageA(&message);
        }
        Sleep(1);
    } while (GetTickCount() - start < milliseconds);
}

static HWND window(const char *cls, HWND owner, DWORD exstyle, DWORD style, int x, int y)
{
    HWND result = CreateWindowExA(exstyle, cls, "Private shadow policy regression", style,
                                  x, y, 400, 240, owner, NULL, GetModuleHandleA(NULL), NULL);
    if (!result) { fprintf(stderr, "CreateWindow %s: %lu\n", cls, GetLastError()); ExitProcess(3); }
    if (exstyle & WS_EX_LAYERED) SetLayeredWindowAttributes(result, 0, 128, LWA_ALPHA);
    return result;
}

static PROCESS_INFORMATION launch(const char *command, BOOL pipe_output, HANDLE *reader)
{
    STARTUPINFOA startup = {.cb = sizeof(startup)};
    PROCESS_INFORMATION process = {0};
    SECURITY_ATTRIBUTES security = {sizeof(security), NULL, TRUE};
    HANDLE writer = NULL;
    char buffer[2 * MAX_PATH];
    snprintf(buffer, sizeof(buffer), "%s", command);
    if (pipe_output)
    {
        if (!CreatePipe(reader, &writer, &security, 0)) ExitProcess(4);
        SetHandleInformation(*reader, HANDLE_FLAG_INHERIT, 0);
        startup.dwFlags = STARTF_USESTDHANDLES;
        startup.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
        startup.hStdOutput = startup.hStdError = writer;
    }
    if (!CreateProcessA(NULL, buffer, NULL, NULL, pipe_output, 0, NULL, NULL, &startup, &process))
        ExitProcess(5);
    if (writer) CloseHandle(writer);
    CloseHandle(process.hThread);
    return process;
}

static BOOL wait_process(HANDLE process, DWORD timeout)
{
    DWORD start = GetTickCount();
    while (WaitForSingleObject(process, 0) == WAIT_TIMEOUT)
    {
        if (GetTickCount() - start >= timeout) return FALSE;
        pump(2);
    }
    return TRUE;
}

static BOOL wait_hook(HANDLE reader)
{
    char text[4096] = {0};
    DWORD start = GetTickCount(), used = 0;
    while (GetTickCount() - start < 10000)
    {
        DWORD available, count;
        if (!PeekNamedPipe(reader, NULL, 0, NULL, &available, NULL)) return FALSE;
        if (available && used < sizeof(text) - 1)
        {
            if (!ReadFile(reader, text + used, sizeof(text) - used - 1, &count, NULL)) return FALSE;
            used += count;
            if (strstr(text, "tray popup hook installed=")) return TRUE;
        }
        pump(2);
    }
    return FALSE;
}

static BOOL wait_output(HANDLE process, HANDLE reader, char *text, DWORD capacity)
{
    DWORD start = GetTickCount(), used = 0;
    while (GetTickCount() - start < 10000)
    {
        DWORD available = 0, count;
        PeekNamedPipe(reader, NULL, 0, NULL, &available, NULL);
        if (available && used < capacity - 1)
        {
            if (!ReadFile(reader, text + used, capacity - used - 1, &count, NULL)) return FALSE;
            used += count;
            text[used] = 0;
        }
        if (!available && WaitForSingleObject(process, 0) == WAIT_OBJECT_0) return TRUE;
        pump(2);
    }
    return FALSE;
}

int main(int argc, char **argv)
{
    const char *classes[] = {"WeWorkWindow", "ImagePreview", "PerryShadowWnd", "OtherOwner",
                             "TitleBarWindow", "InteractiveOverlay"};
    WNDCLASSA cls = {.lpfnWndProc = procedure, .hInstance = GetModuleHandleA(NULL),
                     .hbrBackground = (HBRUSH)(COLOR_WINDOW + 1)};
    const DWORD layered = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_WINDOWEDGE;
    for (unsigned i = 0; i < sizeof(classes) / sizeof(*classes); ++i)
    {
        cls.lpszClassName = classes[i];
        if (!RegisterClassA(&cls)) return 2;
    }
    SetProcessDPIAware();
    if (argc == 3 && !strcmp(argv[1], "--foreign"))
    {
        foreign_process = TRUE;
        HWND owner = window("ImagePreview", NULL, 0, WS_POPUP, 100, 100);
        HWND shadow = window("PerryShadowWnd", owner, layered, WS_POPUP, 90, 90);
        PostMessageA((HWND)(UINT_PTR)strtoull(argv[2], NULL, 16), WM_APP + 1, (WPARAM)owner, (LPARAM)shadow);
        MSG message;
        while (GetMessageA(&message, NULL, 0, 0) > 0) DispatchMessageA(&message);
        return 0;
    }
    if (argc != 3) return 2;
    BOOL fixed = !strcmp(argv[2], "fixed");
    main_window = window("WeWorkWindow", NULL, 0, WS_OVERLAPPEDWINDOW | WS_VISIBLE, 20, 40);
    HWND preview = window("ImagePreview", NULL, 0, WS_OVERLAPPEDWINDOW | WS_VISIBLE, 500, 200);
    HWND other = window("OtherOwner", NULL, 0, WS_POPUP, 20, 40);
    char path[MAX_PATH], command[2 * MAX_PATH];
    GetModuleFileNameA(NULL, path, sizeof(path));
    snprintf(command, sizeof(command), "\"%s\" --foreign %llx", path,
             (unsigned long long)(UINT_PTR)main_window);
    PROCESS_INFORMATION foreign = launch(command, FALSE, NULL);
    DWORD start = GetTickCount();
    while (!foreign_owner && GetTickCount() - start < 10000) pump(2);
    check(foreign_owner && foreign_shadow, "foreign process fixture ready");
    if (!foreign_owner) return 3;
    HWND samples[] = {
        window("PerryShadowWnd", main_window, layered, WS_POPUP, 20, 40),
        window("PerryShadowWnd", preview, layered, WS_POPUP | WS_VISIBLE, 500, 200),
        window("PerryShadowWnd", other, layered, WS_POPUP, 20, 40),
        window("PerryShadowWnd", preview, WS_EX_TOOLWINDOW, WS_POPUP, 20, 40),
        window("TitleBarWindow", preview, layered, WS_POPUP, 20, 40),
        window("InteractiveOverlay", preview, layered, WS_POPUP, 20, 40),
        window("PerryShadowWnd", preview, layered, WS_CHILD, 20, 40),
        window("PerryShadowWnd", foreign_owner, layered, WS_POPUP, 20, 40),
        foreign_shadow
    };
    enum {COUNT = sizeof(samples) / sizeof(*samples)};
    RECT rectangles[COUNT];
    DWORD styles[COUNT], exstyles[COUNT];
    pump(200);
    SetWindowPos(samples[1], HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
    for (unsigned i = 0; i < COUNT; ++i)
    {
        GetWindowRect(samples[i], &rectangles[i]);
        styles[i] = GetWindowLongA(samples[i], GWL_STYLE);
        exstyles[i] = GetWindowLongA(samples[i], GWL_EXSTYLE);
    }
    snprintf(command, sizeof(command), "\"%s\" -apply", argv[1]);
    PROCESS_INFORMATION helper = launch(command, FALSE, NULL);
    check(wait_process(helper.hProcess, 10000), "one-shot helper exits");
    DWORD exit_code;
    GetExitCodeProcess(helper.hProcess, &exit_code);
    check(exit_code == 0, "one-shot helper succeeds");
    CloseHandle(helper.hProcess);
    for (unsigned i = 0; i < COUNT; ++i)
    {
        RECT after;
        DWORD wanted = exstyles[i] | ((i == 0 || (fixed && i == 1)) ? WS_EX_TRANSPARENT : 0);
        GetWindowRect(samples[i], &after);
        check(GetWindowLongA(samples[i], GWL_EXSTYLE) == (LONG)wanted, "exact role and process scope");
        check(GetWindowLongA(samples[i], GWL_STYLE) == (LONG)styles[i], "style preserved");
        check(EqualRect(&after, &rectangles[i]), "geometry preserved");
    }
    check(WindowFromPoint((POINT){600, 300}) == (fixed ? preview : samples[1]), "preview receives hit testing");
    HWND batch[24];
    for (unsigned i = 0; i < sizeof(batch) / sizeof(*batch); ++i)
    {
        HWND owner = window("ImagePreview", NULL, 0, WS_POPUP, 20, 40);
        batch[i] = window("PerryShadowWnd", owner, layered, WS_POPUP, 20, 40);
    }
    HANDLE batch_reader = NULL;
    char batch_output[16384] = {0};
    helper = launch(command, TRUE, &batch_reader);
    check(wait_output(helper.hProcess, batch_reader, batch_output, sizeof(batch_output)), "batch helper exits");
    GetExitCodeProcess(helper.hProcess, &exit_code);
    check(exit_code == 0, "batch helper succeeds");
    check(strstr(batch_output, "matched=") != NULL, "batch diagnostics include the completion summary");
    CloseHandle(helper.hProcess);
    CloseHandle(batch_reader);
    for (unsigned i = 0; i < sizeof(batch) / sizeof(*batch); ++i)
        check(!!(GetWindowLongA(batch[i], GWL_EXSTYLE) & WS_EX_TRANSPARENT) == fixed, "all matching shadows handled");
    if (fixed)
    {
        HANDLE reader = NULL;
        snprintf(command, sizeof(command), "\"%s\" -watch", argv[1]);
        helper = launch(command, TRUE, &reader);
        check(wait_hook(reader), "show event hook installed");
        pump(100);
        HWND shown = window("PerryShadowWnd", preview, layered, WS_POPUP | WS_VISIBLE, 500, 200);
        start = GetTickCount();
        while (!(GetWindowLongA(shown, GWL_EXSTYLE) & WS_EX_TRANSPARENT) && GetTickCount() - start < 600)
            pump(2);
        check(GetWindowLongA(shown, GWL_EXSTYLE) & WS_EX_TRANSPARENT, "new shadow handled before next scan");
        printf("{\"event_fix_ms\":%lu}\n", GetTickCount() - start);
        enum {BURST = 32};
        HWND burst[BURST];
        char logs[32768] = {0};
        DWORD used = 0;
        burst_ready = TRUE;
        for (unsigned i = 0; i < BURST; ++i)
            burst[i] = window("PerryShadowWnd", preview, layered, WS_POPUP | WS_VISIBLE, 500, 200);
        start = GetTickCount();
        unsigned transparent = 0;
        while (GetTickCount() - start < 4000)
        {
            DWORD available = 0, count;
            if (PeekNamedPipe(reader, NULL, 0, NULL, &available, NULL) && available && used < sizeof(logs) - 1)
            {
                if (ReadFile(reader, logs + used, sizeof(logs) - used - 1, &count, NULL)) used += count;
                logs[used] = 0;
            }
            transparent = 0;
            for (unsigned i = 0; i < BURST; ++i)
                transparent += !!(GetWindowLongA(burst[i], GWL_EXSTYLE) & WS_EX_TRANSPARENT);
            if (transparent == BURST && !available && GetTickCount() - start > 1500) break;
            pump(2);
        }
        unsigned records = 0, completions = 0;
        for (char *p = logs; (p = strstr(p, "PerryShadowWnd hwnd=")); ++p) ++records;
        for (char *p = logs; (p = strstr(p, "new_style=")); ++p) ++completions;
        printf("%s\n", logs);
        printf("{\"burst_records\":%u,\"burst_completions\":%u,\"bytes\":%lu,\"transparent\":%u}\n",
               records, completions, used, transparent);
        check(delayed, "busy application thread exercised");
        check(transparent == BURST, "burst shadows all handled");
        /* The preceding single SHOW record has not been consumed from the pipe. */
        check(records == BURST + 1 && completions == BURST + 1, "reentrant diagnostics remain complete");
        for (unsigned i = 0; i < BURST; ++i)
        {
            char record[64];
            snprintf(record, sizeof(record), "PerryShadowWnd hwnd=0x%08lx ", (DWORD)(UINT_PTR)burst[i]);
            const char *entry = strstr(logs, record);
            const char *result = entry ? strchr(entry, '\n') : NULL;
            check(result && !strncmp(result + 1, "new_style=", 10), "each burst window has paired diagnostics");
        }
        TerminateProcess(helper.hProcess, 0);
        WaitForSingleObject(helper.hProcess, 2000);
        CloseHandle(helper.hProcess);
        CloseHandle(reader);
    }
    PostMessageA(foreign_owner, WM_CLOSE, 0, 0);
    if (!wait_process(foreign.hProcess, 5000)) TerminateProcess(foreign.hProcess, 0);
    CloseHandle(foreign.hProcess);
    printf("{\"fixed\":%s,\"checks\":%u,\"failures\":%u}\n", fixed ? "true" : "false", checks, failures);
    return failures != 0;
}
