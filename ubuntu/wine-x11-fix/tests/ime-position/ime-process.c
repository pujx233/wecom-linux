#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <imm.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define WM_COMMAND_READY (WM_APP + 1)
#define WM_CHILD_READY (WM_APP + 2)
#define WM_NOTIFY_IME (WM_APP + 3)
#define WM_REPORT_STATE (WM_APP + 4)
#define WM_IME_UPDATE_TEST 0x80000010u
static HWND root_window, input_window;
static BOOL is_child;

static void report_state(const char *event, HWND hwnd)
{
    POINT point = {80, 110};
    HIMC context = ImmGetContext(hwnd);
    BOOL open = context && ImmGetOpenStatus(context);
    if (context) ImmReleaseContext(hwnd, context);
    ClientToScreen(hwnd, &point);
    LogicalToPhysicalPointForPerMonitorDPI(hwnd, &point);
    printf("{\"event\":\"%s\",\"pid\":%lu,\"hwnd\":%llu,\"root\":%llu,"
           "\"physical\":[%ld,%ld],\"focus\":%llu,\"xid\":%llu,\"open\":%d}\n", event, GetCurrentProcessId(),
           (unsigned long long)(UINT_PTR)hwnd, (unsigned long long)(UINT_PTR)root_window,
           point.x, point.y, (unsigned long long)(UINT_PTR)GetFocus(),
           (unsigned long long)(UINT_PTR)GetPropA(root_window, "__wine_x11_whole_window"), open);
    fflush(stdout);
}

static void report_string(HIMC context, DWORD index, const char *key)
{
    WCHAR buffer[64];
    LONG bytes = ImmGetCompositionStringW(context, index, buffer, sizeof(buffer));
    printf(",\"%s\":[", key);
    for (LONG i = 0; i < bytes / (LONG)sizeof(WCHAR); ++i) printf("%s%u", i ? "," : "", buffer[i]);
    printf("]");
}

static void focus_input(void)
{
    SetForegroundWindow(root_window);
    SetFocus(input_window);
}

static LRESULT CALLBACK window_proc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam)
{
    if (message == WM_REPORT_STATE)
    {
        report_state("posted", hwnd);
        return 0;
    }
    if (message == WM_NOTIFY_IME)
    {
        HIMC context = ImmGetContext(hwnd);
        BOOL ok = ImmNotifyIME(context, NI_COMPOSITIONSTR, (DWORD)wparam, 0);
        ImmReleaseContext(hwnd, context);
        printf("{\"event\":\"notify\",\"operation\":%u,\"ok\":%d}\n", (UINT)wparam, ok);
        fflush(stdout);
        return 0;
    }
    if (message == WM_CHILD_READY)
    {
        input_window = (HWND)lparam;
        focus_input();
        report_state("ready", input_window);
        return 0;
    }
    if (message == WM_IME_STARTCOMPOSITION || message == WM_IME_ENDCOMPOSITION)
    {
        printf("{\"event\":\"%s\",\"child\":%d}\n",
               message == WM_IME_STARTCOMPOSITION ? "start" : "end", is_child);
        fflush(stdout);
        return 0;
    }
    if (message == WM_IME_COMPOSITION)
    {
        HIMC context = ImmGetContext(hwnd);
        COMPOSITIONFORM composition = {CFS_POINT, {80, 110}, {0}};
        CANDIDATEFORM candidate = {0, CFS_CANDIDATEPOS, {80, 110}, {0}};
        ImmSetCompositionWindow(context, &composition);
        ImmSetCandidateWindow(context, &candidate);
        printf("{\"event\":\"composition\",\"child\":%d,\"flags\":%llu", is_child,
               (unsigned long long)(UINT_PTR)lparam);
        if (lparam & GCS_COMPSTR) report_string(context, GCS_COMPSTR, "comp");
        if (lparam & GCS_RESULTSTR) report_string(context, GCS_RESULTSTR, "result");
        printf("}\n");
        fflush(stdout);
        ImmReleaseContext(hwnd, context);
        return 0;
    }
    if (message == WM_COMMAND_READY)
    {
        char *command = (char *)lparam;
        if (!strncmp(command, "quit", 4))
        {
            PostMessageW(input_window, WM_CLOSE, 0, 0);
            PostMessageW(hwnd, WM_CLOSE, 0, 0);
        }
        else if (!strncmp(command, "root", 4))
        {
            SetFocus(root_window);
            report_state("root-focus", root_window);
        }
        else if (!strncmp(command, "focus", 5))
        {
            focus_input();
            report_state("child-focus", input_window);
        }
        else if (!strncmp(command, "complete", 8) || !strncmp(command, "cancel", 6))
            SendMessageW(input_window, WM_NOTIFY_IME, !strncmp(command, "complete", 8) ? CPS_COMPLETE : CPS_CANCEL, 0);
        else if (!strncmp(command, "state", 5))
        {
            report_state("root-state", root_window);
            SendMessageW(input_window, WM_REPORT_STATE, 0, 0);
        }
        else if (!strncmp(command, "stale", 5) || !strncmp(command, "invalid", 7))
        {
            struct
            {
                UINT cursor_pos, hkl, comp_len, result_len;
                WCHAR buffer[4];
            } update = {1, 0xe0010409, 4, 0, {97, 0xd83d, 0xde42, 0}};
            if (!strncmp(command, "invalid", 7)) update.buffer[3] = 98;
            SendNotifyMessageW(input_window, WM_IME_UPDATE_TEST, (WPARAM)root_window, (LPARAM)&update);
            SendMessageW(input_window, WM_NULL, 0, 0);
            report_state("fence", input_window);
        }
        else
        {
            report_state("posted", input_window);
        }
        free(command);
        return 0;
    }
    if (message == WM_CLOSE) { DestroyWindow(hwnd); return 0; }
    if (message == WM_DESTROY) PostQuitMessage(0);
    return DefWindowProcW(hwnd, message, wparam, lparam);
}

static DWORD WINAPI read_commands(void *unused)
{
    char command[80];
    (void)unused;
    while (fgets(command, sizeof(command), stdin))
    {
        char *copy = malloc(strlen(command) + 1);
        if (!copy) break;
        strcpy(copy, command);
        if (!PostMessageW(root_window, WM_COMMAND_READY, 0, (LPARAM)copy)) { free(copy); break; }
        if (!strncmp(command, "quit", 4)) return 0;
    }
    PostMessageW(root_window, WM_CLOSE, 0, 0);
    return 0;
}

int main(int argc, char **argv)
{
    WNDCLASSW cls = {0};
    MSG msg;
    char guard[8], display[32];
    if (!GetEnvironmentVariableA("WECOM_IME_FIXTURE", guard, sizeof(guard)) || strcmp(guard, "1")) return 2;
    if (!GetEnvironmentVariableA("DISPLAY", display, sizeof(display))) return 3;
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    is_child = argc > 2 && !strcmp(argv[1], "child");
    cls.hInstance = GetModuleHandleW(NULL);
    cls.lpfnWndProc = window_proc;
    cls.lpszClassName = L"ImeProcessFixture";
    cls.hbrBackground = GetSysColorBrush(COLOR_WINDOW);
    if (!RegisterClassW(&cls)) return 5;
    if (is_child)
    {
        root_window = (HWND)(UINT_PTR)strtoull(argv[2], NULL, 10);
        ActivateKeyboardLayout((HKL)(UINT_PTR)0xe0010409, 0);
        input_window = CreateWindowW(cls.lpszClassName, L"Foreign editor", WS_CHILD | WS_VISIBLE,
                                     40, 50, 500, 300, root_window, NULL, cls.hInstance, NULL);
        if (!input_window) return 6;
        ImmAssociateContextEx(input_window, NULL, IACE_DEFAULT);
        PostMessageW(root_window, WM_CHILD_READY, 0, (LPARAM)input_window);
    }
    else
    {
        STARTUPINFOA startup = {.cb = sizeof(startup)};
        PROCESS_INFORMATION process;
        char command[2048];
        if (argc != 2) return 7;
        root_window = CreateWindowW(cls.lpszClassName, L"Isolated foreign-process IME fixture",
                                    WS_OVERLAPPEDWINDOW, 160, 100, 700, 520, NULL, NULL, cls.hInstance, NULL);
        if (!root_window) return 8;
        ShowWindow(root_window, SW_SHOW);
        UpdateWindow(root_window);
        ActivateKeyboardLayout((HKL)(UINT_PTR)0xe0010409, 0);
        snprintf(command, sizeof(command), "\"%s\" child %llu", argv[1],
                 (unsigned long long)(UINT_PTR)root_window);
        if (!CreateProcessA(NULL, command, NULL, NULL, TRUE, 0, NULL, NULL, &startup, &process)) return 9;
        CloseHandle(process.hThread);
        CloseHandle(process.hProcess);
        HANDLE reader = CreateThread(NULL, 0, read_commands, NULL, 0, NULL);
        if (!reader) return 10;
        CloseHandle(reader);
    }
    while (GetMessageW(&msg, NULL, 0, 0) > 0) { TranslateMessage(&msg); DispatchMessageW(&msg); }
    return 0;
}
