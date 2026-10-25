#include <windows.h>
#include <shellapi.h>
#include <stdio.h>
#include <string.h>

int main(int argc, char **argv)
{
    BOOL alpha_test = argc == 2 && !strcmp(argv[1], "--alpha");
    BOOL checker_test = argc == 2 && !strcmp(argv[1], "--checker");
    BITMAPINFO info = {.bmiHeader = {.biSize = sizeof(BITMAPINFOHEADER), .biWidth = 16, .biHeight = -16,
                                   .biPlanes = 1, .biBitCount = 32, .biCompression = BI_RGB}};
    DWORD *pixels;
    HBITMAP color = CreateDIBSection(NULL, &info, DIB_RGB_COLORS, (void **)&pixels, NULL, 0);
    for (int y = 0; y < 16; y++)
        for (int x = 0; x < 16; x++)
            if (checker_test)
                pixels[y * 16 + x] = x % 2 ? 0xff0000ff : 0xffff0000;
            else if (alpha_test)
                pixels[y * 16 + x] = x < 4 || y < 4 || x >= 12 || y >= 12 ? 0 :
                                    x == 4 || y == 4 || x == 11 || y == 11 ? 0x80ff0000 : 0xffff0000;
            else
                pixels[y * 16 + x] = x < 2 || y < 2 || x >= 14 || y >= 14 ? 0xffff0000 : 0xffffffff;
    WORD mask_bits[16] = {0};
    ICONINFO icon_info = {.fIcon = TRUE, .hbmColor = color, .hbmMask = CreateBitmap(16, 16, 1, 1, mask_bits)};
    HICON image = CreateIconIndirect(&icon_info);
    DeleteObject(icon_info.hbmMask);
    DeleteObject(color);
    HWND window = CreateWindowExA(0, "STATIC", "", 0, 0, 0, 1, 1, NULL, NULL, NULL, NULL);
    NOTIFYICONDATAW icon = {.cbSize = sizeof(icon), .hWnd = window, .uID = 1,
                           .uFlags = NIF_ICON | NIF_MESSAGE, .hIcon = image, .uCallbackMessage = WM_APP};
    printf("added=%d small_icon=%d\n", Shell_NotifyIconW(NIM_ADD, &icon), GetSystemMetrics(SM_CXSMICON));
    fflush(stdout);
    DWORD end = GetTickCount() + 20000;
    while ((LONG)(GetTickCount() - end) < 0) {
        MSG message;
        while (PeekMessageW(&message, NULL, 0, 0, PM_REMOVE)) DispatchMessageW(&message);
        Sleep(5);
    }
    Shell_NotifyIconW(NIM_DELETE, &icon);
    DestroyIcon(image);
    DestroyWindow(window);
    return 0;
}
