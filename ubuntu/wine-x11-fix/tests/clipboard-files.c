#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shlobj.h>
#include <stdio.h>
#include <wchar.h>

int wmain(int argc, WCHAR **argv)
{
    BOOL text, ansi;
    SIZE_T size;
    HGLOBAL memory;
    void *data;
    HWND window;
    HANDLE ready;
    DWORD started;
    MSG message;
    int i;

    if (argc < 5) return 2;
    text = !wcscmp(argv[1], L"text");
    ansi = !wcscmp(argv[1], L"ansi");
    if (!text && !ansi && wcscmp(argv[1], L"unicode")) return 2;
    size = text ? (wcslen(argv[4]) + 1) * sizeof(WCHAR) : sizeof(DROPFILES);
    if (!text)
    {
        size += ansi ? 1 : sizeof(WCHAR);
        for (i = 4; i < argc; i++)
            size += ansi ? (SIZE_T)WideCharToMultiByte(CP_ACP, 0, argv[i], -1, NULL, 0, NULL, NULL)
                         : (wcslen(argv[i]) + 1) * sizeof(WCHAR);
    }
    memory = GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, size);
    if (!memory || !(data = GlobalLock(memory))) return 3;
    if (text) memcpy(data, argv[4], size);
    else
    {
        DROPFILES *drop = data;
        char *ptr = (char *)(drop + 1);
        drop->pFiles = sizeof(*drop);
        drop->fWide = !ansi;
        for (i = 4; i < argc; i++)
        {
            if (ansi)
                ptr += WideCharToMultiByte(CP_ACP, 0, argv[i], -1, ptr, size - (ptr - (char *)data), NULL, NULL);
            else
            {
                SIZE_T length = (wcslen(argv[i]) + 1) * sizeof(WCHAR);
                memcpy(ptr, argv[i], length);
                ptr += length;
            }
        }
    }
    GlobalUnlock(memory);
    window = CreateWindowExW(0, L"STATIC", L"Clipboard regression", 0, 0, 0, 0, 0, HWND_MESSAGE, NULL, NULL, NULL);
    if (!window || !OpenClipboard(window)) return 4;
    if (!EmptyClipboard() || !SetClipboardData(text ? CF_UNICODETEXT : CF_HDROP, memory)) return 5;
    CloseClipboard();
    ready = CreateFileW(argv[2], GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (ready == INVALID_HANDLE_VALUE) return 6;
    CloseHandle(ready);
    started = GetTickCount();
    while (GetFileAttributesW(argv[3]) == INVALID_FILE_ATTRIBUTES)
    {
        if (GetTickCount() - started > 30000) return 7;
        while (PeekMessageW(&message, NULL, 0, 0, PM_REMOVE))
        {
            TranslateMessage(&message);
            DispatchMessageW(&message);
        }
        Sleep(10);
    }
    DestroyWindow(window);
    return 0;
}
