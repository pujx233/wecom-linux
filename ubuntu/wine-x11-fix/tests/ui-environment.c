#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <commdlg.h>
#include <shellapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static HWND window, dialog;
static HFONT tahoma, reference;
static void json_text(const WCHAR *text);

static int check_glyphs(const WCHAR *face)
{
    const WCHAR text[] = L"中文目录";
    BITMAPINFO info = {{sizeof(BITMAPINFOHEADER), 32, -32, 1, 32, BI_RGB}};
    DWORD *pixels;
    HDC dc = CreateCompatibleDC(NULL);
    HBITMAP bitmap = CreateDIBSection(dc, &info, DIB_RGB_COLORS, (void **)&pixels, NULL, 0);
    HFONT font = CreateFontW(-11, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
                            DEFAULT_CHARSET, 0, 0, 0, 0, face);
    unsigned int hashes[4], ink[4], i, j, distinct = 0;
    if (!dc || !bitmap || !font) return 2;
    SelectObject(dc, bitmap);
    SelectObject(dc, font);
    SetTextColor(dc, RGB(0, 0, 0));
    SetBkColor(dc, RGB(255, 255, 255));
    for (i = 0; i < 4; i++)
    {
        memset(pixels, 255, 32 * 32 * sizeof(*pixels));
        TextOutW(dc, 0, 0, text + i, 1);
        GdiFlush();
        hashes[i] = 2166136261u;
        ink[i] = 0;
        for (j = 0; j < 32 * 32; j++)
        {
            DWORD pixel = pixels[j] & 0xffffff;
            if (pixel != 0xffffff) ink[i]++;
            hashes[i] = (hashes[i] ^ pixel) * 16777619u;
        }
        for (j = 0; j < i && hashes[j] != hashes[i]; j++);
        if (j == i) distinct++;
    }
    printf("{\"event\":\"glyphs\",\"font\":");
    json_text(face);
    printf(",\"distinct\":%u,\"ink\":[%u,%u,%u,%u]}\n", distinct, ink[0], ink[1], ink[2], ink[3]);
    DeleteDC(dc);
    DeleteObject(bitmap);
    DeleteObject(font);
    return distinct == 4 && ink[0] && ink[1] && ink[2] && ink[3] ? 0 : 1;
}

static void json_text(const WCHAR *text)
{
    char utf8[2048];
    const unsigned char *p;
    WideCharToMultiByte(CP_UTF8, 0, text, -1, utf8, sizeof(utf8), NULL, NULL);
    putchar('"');
    for (p = (const unsigned char *)utf8; *p; p++)
    {
        if (*p == '"' || *p == '\\') putchar('\\');
        if (*p < 32) printf("\\u%04x", *p);
        else putchar(*p);
    }
    putchar('"');
}

static BOOL CALLBACK inspect(HWND hwnd, LPARAM unused)
{
    WCHAR title[512], cls[256];
    RECT rect;
    DWORD pid;
    (void)unused;
    if (hwnd != GetDesktopWindow() &&
        (!IsWindowVisible(hwnd) || !GetPropW(hwnd, L"__wine_x11_whole_window"))) return TRUE;
    GetWindowTextW(hwnd, title, 512);
    GetClassNameW(hwnd, cls, 256);
    GetWindowRect(hwnd, &rect);
    GetWindowThreadProcessId(hwnd, &pid);
    printf("{\"event\":\"window\",\"hwnd\":%llu,\"pid\":%lu,\"title\":",
           (unsigned long long)(UINT_PTR)hwnd, pid);
    json_text(title);
    printf(",\"class\":");
    json_text(cls);
    printf(",\"dpi\":%u,\"rect\":[%ld,%ld,%ld,%ld],\"style\":%lu,\"ex_style\":%lu,\"owner\":%llu,"
           "\"body\":%llu,\"frame\":%llu}\n",
           GetDpiForWindow(hwnd), rect.left, rect.top, rect.right, rect.bottom,
           (DWORD)GetWindowLongPtrW(hwnd, GWL_STYLE), (DWORD)GetWindowLongPtrW(hwnd, GWL_EXSTYLE),
           (unsigned long long)(UINT_PTR)GetWindow(hwnd, GW_OWNER),
           (unsigned long long)(UINT_PTR)GetPropW(hwnd, L"__wine_x11_whole_window"),
           (unsigned long long)(UINT_PTR)GetPropW(hwnd, L"__wine_x11_wm_window"));
    return TRUE;
}

static BOOL CALLBACK set_font(HWND hwnd, LPARAM font)
{
    SendMessageW(hwnd, WM_SETFONT, font, TRUE);
    return TRUE;
}

static UINT_PTR CALLBACK dialog_hook(HWND hwnd, UINT message, WPARAM wp, LPARAM lp)
{
    (void)wp;
    if (message == WM_INITDIALOG) dialog = GetParent(hwnd);
    if (message == WM_NOTIFY && ((NMHDR *)lp)->code == CDN_INITDONE)
    {
        SendMessageW(dialog, WM_SETFONT, (WPARAM)tahoma, TRUE);
        EnumChildWindows(dialog, set_font, (LPARAM)tahoma);
        printf("{\"event\":\"dialog\",\"hwnd\":%llu,\"font\":\"Tahoma\",\"dpi\":%u}\n",
               (unsigned long long)(UINT_PTR)dialog, GetDpiForWindow(dialog));
        fflush(stdout);
    }
    return 0;
}

static LRESULT CALLBACK proc(HWND hwnd, UINT message, WPARAM wp, LPARAM lp)
{
    if (message == WM_PAINT)
    {
        PAINTSTRUCT ps;
        RECT rect;
        HDC dc = BeginPaint(hwnd, &ps);
        UINT dpi = GetDpiForWindow(hwnd);
        SetBkMode(dc, TRANSPARENT);
        GetClientRect(hwnd, &rect);
        FillRect(dc, &rect, (HBRUSH)GetStockObject(WHITE_BRUSH));
        rect.left = 20;
        rect.top = MulDiv(24, dpi, 96);
        SelectObject(dc, tahoma);
        DrawTextW(dc, L"Tahoma: 打开文件 中文目录 测试报告", -1, &rect, DT_LEFT | DT_SINGLELINE);
        rect.top = MulDiv(72, dpi, 96);
        SelectObject(dc, reference);
        DrawTextW(dc, L"思源黑体: 打开文件 中文目录 测试报告", -1, &rect, DT_LEFT | DT_SINGLELINE);
        EndPaint(hwnd, &ps);
        return 0;
    }
    if (message == WM_APP)
    {
        OPENFILENAMEW ofn = {sizeof(ofn)};
        WCHAR file[MAX_PATH] = L"中文文件测试.txt";
        WCHAR directory[MAX_PATH];
        GetEnvironmentVariableW(L"WECOM_QA_FILES", directory, MAX_PATH);
        ofn.hwndOwner = hwnd;
        ofn.lpstrFilter = L"文本文件 (*.txt)\0*.txt\0所有文件\0*.*\0";
        ofn.lpstrFile = file;
        ofn.nMaxFile = MAX_PATH;
        ofn.lpstrInitialDir = directory;
        ofn.lpstrTitle = L"打开中文文件 — Tahoma 字体回退验证";
        ofn.Flags = OFN_EXPLORER | OFN_ENABLEHOOK | OFN_FILEMUSTEXIST;
        ofn.lpfnHook = dialog_hook;
        SetLastError(0);
        GetOpenFileNameW(&ofn);
        printf("{\"event\":\"dialog-closed\",\"error\":%lu}\n", CommDlgExtendedError());
        fflush(stdout);
        dialog = NULL;
        return 0;
    }
    if (message == WM_APP + 1)
    {
        WCHAR directory[MAX_PATH];
        HINSTANCE result;
        GetEnvironmentVariableW(L"WECOM_QA_FILES", directory, MAX_PATH);
        result = ShellExecuteW(hwnd, L"open", directory, NULL, NULL, SW_SHOWNORMAL);
        printf("{\"event\":\"folder-launch\",\"result\":%llu}\n", (unsigned long long)(UINT_PTR)result);
        fflush(stdout);
        return 0;
    }
    if (message == WM_CLOSE && dialog)
    {
        PostMessageW(dialog, WM_CLOSE, 0, 0);
        return 0;
    }
    if (message == WM_DESTROY) { PostQuitMessage(0); return 0; }
    return DefWindowProcW(hwnd, message, wp, lp);
}

static DWORD WINAPI commands(void *unused)
{
    char line[40];
    (void)unused;
    while (fgets(line, sizeof(line), stdin))
    {
        if (!strncmp(line, "dialog", 6)) PostMessageW(window, WM_APP, 0, 0);
        else if (!strncmp(line, "folder", 6)) PostMessageW(window, WM_APP + 1, 0, 0);
        else if (!strncmp(line, "inspect", 7)) { EnumWindows(inspect, 0); fflush(stdout); }
        else PostMessageW(dialog ? dialog : window, WM_CLOSE, 0, 0);
    }
    return 0;
}

int main(int argc, char **argv)
{
    WNDCLASSW cls = {0};
    MSG msg;
    UINT dpi;
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    if (argc > 2 && !strcmp(argv[1], "close"))
    {
        PostMessageW((HWND)(UINT_PTR)strtoull(argv[2], NULL, 0), WM_CLOSE, 0, 0);
        return 0;
    }
    if (argc > 1 && !strcmp(argv[1], "inspect"))
    {
        inspect(GetDesktopWindow(), 0);
        EnumWindows(inspect, 0);
        return 0;
    }
    if (argc > 1 && !strcmp(argv[1], "glyphs"))
    {
        WCHAR face[LF_FACESIZE] = L"Tahoma";
        if (argc > 2) MultiByteToWideChar(CP_UTF8, 0, argv[2], -1, face, LF_FACESIZE);
        return check_glyphs(face);
    }
    cls.lpfnWndProc = proc;
    cls.hInstance = GetModuleHandleW(NULL);
    cls.lpszClassName = L"WeComEnvironmentProbe";
    if (!RegisterClassW(&cls)) return 2;
    dpi = GetDpiForSystem();
    tahoma = CreateFontW(-MulDiv(12, dpi, 72), 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
                         DEFAULT_CHARSET, 0, 0, 0, 0, L"Tahoma");
    reference = CreateFontW(-MulDiv(12, dpi, 72), 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
                            DEFAULT_CHARSET, 0, 0, 0, 0, L"Source Han Sans CN");
    window = CreateWindowW(cls.lpszClassName, L"中文字体与文件对话框验证", WS_OVERLAPPEDWINDOW,
                           100, 100, MulDiv(720, dpi, 96), MulDiv(240, dpi, 96),
                           NULL, NULL, cls.hInstance, NULL);
    if (!window) return 3;
    ShowWindow(window, SW_SHOW);
    UpdateWindow(window);
    printf("{\"event\":\"ready\",\"dpi\":%u}\n", GetDpiForWindow(window));
    fflush(stdout);
    CreateThread(NULL, 0, commands, NULL, 0, NULL);
    while (GetMessageW(&msg, NULL, 0, 0) > 0) { TranslateMessage(&msg); DispatchMessageW(&msg); }
    DeleteObject(tahoma);
    DeleteObject(reference);
    return 0;
}
