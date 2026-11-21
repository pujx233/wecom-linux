#define _WIN32_WINNT 0x0601
#include <windows.h>
#include <stdio.h>
#include <string.h>
static const DWORD pixels[6] = {0x00112233,0x00445566,0x00778899,0x00abcdef,0x00abcdef,0x0000ff00};
int main(int argc, char **argv)
{
    HWND owner = CreateWindowA("STATIC", "Bitmap clipboard test", WS_POPUP, 0, 0, 10, 10, NULL, NULL, NULL, NULL);
    DWORD actual[6] = {0};
    BITMAP info;
    if (argc < 2 || !owner || !OpenClipboard(owner)) return 2;
    if (!strcmp(argv[1], "write"))
    {
        MSG message;
        DWORD started = GetTickCount();
        HBITMAP bmp = CreateBitmap(3, 2, 1, 32, pixels);
        if (argc != 3 || !bmp || !EmptyClipboard() || !SetClipboardData(CF_BITMAP, bmp)) return 3;
        CloseClipboard();
        puts("ready"); fflush(stdout);
        while (GetFileAttributesA(argv[2]) == INVALID_FILE_ATTRIBUTES)
        {
            if (GetTickCount() - started > 30000) return 4;
            while (PeekMessageW(&message, NULL, 0, 0, PM_REMOVE))
            {
                TranslateMessage(&message);
                DispatchMessageW(&message);
            }
            Sleep(10);
        }
        DestroyWindow(owner);
        return 0;
    }
    if (argc != 2 || strcmp(argv[1], "read")) return 2;
    HANDLE bitmap = GetClipboardData(CF_BITMAP);
    LONG size = bitmap ? GetBitmapBits(bitmap, sizeof(actual), actual) : 0;
    BOOL passed = bitmap && GetObjectW(bitmap, sizeof(info), &info) && info.bmWidth == 3 && info.bmHeight == 2
        && size == sizeof(actual) && !memcmp(actual, pixels, sizeof(actual));
    printf("bits=%u bitmap=%p size=%ld passed=%d pixels=%08lx,%08lx,%08lx,%08lx,%08lx,%08lx\n",
           (unsigned)(8 * sizeof(void *)), bitmap, size, passed, actual[0], actual[1], actual[2],
           actual[3], actual[4], actual[5]);
    CloseClipboard(); DestroyWindow(owner);
    return !passed;
}
