#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static HWND root, body, subject;
static WCHAR text[256];
static unsigned length;

static void report_text(const char *field, const WCHAR *value, unsigned count)
{
    printf("{\"event\":\"%s\",\"units\":[", field);
    for (unsigned i = 0; i < count; i++) printf("%s%u", i ? "," : "", value[i]);
    puts("]}");
    fflush(stdout);
}

static void focus_body(void)
{
    GUITHREADINFO info = {.cbSize = sizeof(info)};
    DWORD process, thread = GetWindowThreadProcessId(body, &process);
    if (thread != GetCurrentThreadId()) AttachThreadInput(GetCurrentThreadId(), thread, TRUE);
    SetForegroundWindow(root);
    SetFocus(body);
    GetGUIThreadInfo(0, &info);
    printf("{\"event\":\"ready\",\"root\":%llu,\"body\":%llu,\"focus\":%llu,"
           "\"root_pid\":%lu,\"body_pid\":%lu,\"xid\":%llu}\n",
           (unsigned long long)(UINT_PTR)root, (unsigned long long)(UINT_PTR)body,
           (unsigned long long)(UINT_PTR)info.hwndFocus, GetCurrentProcessId(), process,
           (unsigned long long)(UINT_PTR)GetPropA(root, "__wine_x11_whole_window"));
    fflush(stdout);
}

static LRESULT CALLBACK procedure(HWND window, UINT message, WPARAM wp, LPARAM lp)
{
    if (window == body)
    {
        if (message == WM_CHAR)
        {
            if (length + 1 < sizeof(text) / sizeof(*text)) text[length++] = wp;
            report_text("body", text, length);
            InvalidateRect(window, NULL, FALSE);
            return 0;
        }
        /* CEF's foreign editor does not commit through DefWindowProc's IMM fallback. */
        if (message == WM_IME_COMPOSITION || message == WM_IME_CHAR) return 0;
        if (message == WM_SETFOCUS)
        {
            CreateCaret(window, NULL, 1, 20);
            SetCaretPos(10, 10);
            ShowCaret(window);
        }
        if (message == WM_KILLFOCUS) DestroyCaret();
        if (message == WM_PAINT)
        {
            PAINTSTRUCT paint;
            RECT rect;
            HDC dc = BeginPaint(window, &paint);
            GetClientRect(window, &rect);
            FillRect(dc, &rect, (HBRUSH)(COLOR_WINDOW + 1));
            DrawTextW(dc, text, length, &rect, DT_LEFT | DT_TOP);
            EndPaint(window, &paint);
            return 0;
        }
    }
    if (window == root && message == WM_APP)
    {
        body = (HWND)wp;
        focus_body();
        return 0;
    }
    if (window == root && message == WM_APP + 1)
    {
        SetFocus(subject);
        puts("{\"event\":\"subject-focus\"}");
        fflush(stdout);
        return 0;
    }
    if (window == root && message == WM_COMMAND && HIWORD(wp) == EN_CHANGE)
    {
        WCHAR value[256];
        int count = GetWindowTextW(subject, value, sizeof(value) / sizeof(*value));
        report_text("subject", value, count);
    }
    if (message == WM_DESTROY && (window == root || window == body)) PostQuitMessage(0);
    return DefWindowProcW(window, message, wp, lp);
}

static void create_body(const char *body_class, const char *parent_class)
{
    WCHAR body_name[128], parent_name[128];
    WNDCLASSW cls = {.lpfnWndProc = procedure, .hInstance = GetModuleHandleW(NULL)};
    MultiByteToWideChar(CP_UTF8, 0, body_class, -1, body_name, 128);
    MultiByteToWideChar(CP_UTF8, 0, parent_class, -1, parent_name, 128);
    cls.lpszClassName = parent_name;
    RegisterClassW(&cls);
    cls.lpszClassName = body_name;
    RegisterClassW(&cls);
    HWND parent = CreateWindowExW(0, parent_name, L"", WS_CHILD | WS_VISIBLE,
                                  20, 100, 750, 300, root, NULL, cls.hInstance, NULL);
    body = CreateWindowExW(0, body_name, L"", WS_CHILD | WS_VISIBLE,
                           0, 0, 750, 300, parent, NULL, cls.hInstance, NULL);
    if (!parent || !body) ExitProcess(3);
    UpdateWindow(body);
    PostMessageA(root, WM_APP, (WPARAM)body, 0);
}

static DWORD WINAPI commands(void *unused)
{
    char line[32];
    (void)unused;
    while (fgets(line, sizeof(line), stdin))
    {
        if (!strncmp(line, "subject", 7)) PostMessageA(root, WM_APP + 1, 0, 0);
        else if (!strncmp(line, "body", 4)) PostMessageA(root, WM_APP, (WPARAM)body, 0);
        else { PostMessageA(root, WM_CLOSE, 0, 0); break; }
    }
    return 0;
}

int main(int argc, char **argv)
{
    WNDCLASSW cls = {.lpfnWndProc = procedure, .hInstance = GetModuleHandleW(NULL),
                    .lpszClassName = L"MailBridgeRoot"};
    PROCESS_INFORMATION process = {0};
    MSG message;
    SetProcessDPIAware();
    if (argc > 1 && !strcmp(argv[1], "--renderer"))
    {
        if (argc != 5) return 2;
        root = (HWND)(UINT_PTR)strtoull(argv[2], NULL, 16);
        create_body(argv[3], argv[4]);
    }
    else
    {
        if (argc != 4 || !RegisterClassW(&cls)) return 2;
        root = CreateWindowExW(0, cls.lpszClassName, L"Private mail bridge regression", WS_OVERLAPPEDWINDOW,
                               80, 80, 900, 600, NULL, NULL, cls.hInstance, NULL);
        subject = CreateWindowExW(WS_EX_CLIENTEDGE, L"Edit", L"", WS_CHILD | WS_VISIBLE | ES_AUTOHSCROLL,
                                  20, 30, 750, 40, root, NULL, cls.hInstance, NULL);
        ShowWindow(root, SW_SHOW);
        UpdateWindow(root);
        if (!strcmp(argv[3], "same-process")) create_body(argv[1], argv[2]);
        else
        {
            char path[MAX_PATH], command[2 * MAX_PATH];
            STARTUPINFOA startup = {.cb = sizeof(startup)};
            GetModuleFileNameA(NULL, path, sizeof(path));
            strcpy(strrchr(path, '\\') + 1, "Renderer.exe");
            snprintf(command, sizeof(command), "\"%s\" --renderer %llx %s %s", path,
                     (unsigned long long)(UINT_PTR)root, argv[1], argv[2]);
            if (!CreateProcessA(NULL, command, NULL, NULL, TRUE, 0, NULL, NULL, &startup, &process)) return 4;
            CloseHandle(process.hThread);
        }
        CloseHandle(CreateThread(NULL, 0, commands, NULL, 0, NULL));
    }
    while (GetMessageW(&message, NULL, 0, 0) > 0)
    {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    if (process.hProcess)
    {
        WaitForSingleObject(process.hProcess, 5000);
        CloseHandle(process.hProcess);
    }
    return 0;
}
