#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

static HWND owner, holder;
static unsigned int failures, checks;

static COLORREF color(unsigned int x, unsigned int y)
{
    return RGB(25 + 50 * x, 40 + 55 * y, 70 + 20 * (x + y));
}

static void paint(HWND hwnd, HDC dc)
{
    unsigned int x, y;
    RECT rect;
    HBRUSH brush;
    GetClientRect(hwnd, &rect);
    brush = CreateSolidBrush(RGB(30, 30, 30));
    FillRect(dc, &rect, brush);
    DeleteObject(brush);
    for (x = 0; x < 3; x++) for (y = 0; y < 3; y++)
    {
        SetRect(&rect, x * 40, y * 150, (x + 1) * 40, (y + 1) * 150);
        brush = CreateSolidBrush(color(x, y));
        FillRect(dc, &rect, brush);
        DeleteObject(brush);
    }
}

static void check_pixels(const char *stage, unsigned int round)
{
    HDC dc = GetDC(owner);
    unsigned int x, y;
    for (x = 0; x < 3; x++) for (y = 0; y < 3; y++)
    {
        COLORREF pixel = GetPixel(dc, x * 40 + 20, y * 150 + 40);
        checks++;
        if (pixel == color(x, y)) continue;
        failures++;
        printf("FAIL round=%u stage=%s x=%u y=%u actual=%06lx expected=%06lx\n",
               round, stage, x, y, pixel, color(x, y));
    }
    ReleaseDC(owner, dc);
}

static LRESULT CALLBACK proc(HWND hwnd, UINT message, WPARAM wp, LPARAM lp)
{
    if (message == WM_NCCALCSIZE) return 0;
    if (message == WM_ERASEBKGND) return 1;
    if (message == WM_PAINT)
    {
        PAINTSTRUCT ps;
        HDC dc = BeginPaint(hwnd, &ps);
        paint(hwnd, dc);
        EndPaint(hwnd, &ps);
        return 0;
    }
    if (message == WM_APP + 1)
    {
        SetTimer(owner, 1, 100, NULL);
        return 0;
    }
    if (message == WM_TIMER && wp == 1)
    {
        unsigned int round;
        KillTimer(owner, 1);
        for (round = 0; round < 6; round++)
        {
            SetWindowRgn(owner, round & 1 ? CreateRoundRectRgn(0, 0, 700, 500, 16, 16) : NULL, FALSE);
            ShowWindow(holder, SW_SHOWNA);
            InvalidateRect(owner, NULL, FALSE);
            UpdateWindow(owner);
            check_pixels("before", round);
            ShowWindow(holder, SW_HIDE);
            SetParent(holder, NULL);
            check_pixels("detached", round);
            SetParent(holder, owner);
            check_pixels("reattached", round);
        }
        printf("RESULT bits=%u checks=%u failures=%u\n", (unsigned int)(8 * sizeof(void *)), checks, failures);
        fflush(stdout);
        DestroyWindow(owner);
        return 0;
    }
    if (message == WM_DESTROY) { PostQuitMessage(0); return 0; }
    return DefWindowProcA(hwnd, message, wp, lp);
}

int main(int argc, char **argv)
{
    BOOL child = argc > 1 && !strcmp(argv[1], "--child");
    BOOL unaware = child ? argc > 3 && !strcmp(argv[3], "unaware") :
                           argc > 1 && !strcmp(argv[1], "unaware");
    WNDCLASSA wc = {0};
    MSG msg;
    if (!unaware) SetProcessDPIAware();
    wc.lpfnWndProc = proc;
    wc.hInstance = GetModuleHandleA(NULL);
    wc.lpszClassName = "SurfaceTransitionRegression";
    RegisterClassA(&wc);
    if (child)
    {
        HWND foreign;
        owner = (HWND)(ULONG_PTR)strtoull(argv[2], NULL, 16);
        foreign = CreateWindowA(wc.lpszClassName, "foreign", WS_CHILD | WS_VISIBLE,
                               0, 0, 300, 240, owner, NULL, wc.hInstance, NULL);
        if (!foreign) return 2;
        UpdateWindow(foreign);
        PostMessageA(GetAncestor(owner, GA_ROOT), WM_APP + 1, 0, 0);
    }
    else
    {
        STARTUPINFOW si = {0};
        PROCESS_INFORMATION pi;
        WCHAR exe[MAX_PATH], command[2 * MAX_PATH];
        owner = CreateWindowA(wc.lpszClassName, "Surface transition regression", WS_POPUP | WS_THICKFRAME,
                              200, 100, 700, 500, NULL, NULL, wc.hInstance, NULL);
        if (!owner) return 2;
        ShowWindow(owner, SW_SHOW);
        UpdateWindow(owner);
        holder = CreateWindowA(wc.lpszClassName, "holder", WS_CHILD | WS_VISIBLE,
                               160, 80, 400, 300, owner, NULL, wc.hInstance, NULL);
        if (!holder) return 2;
        GetModuleFileNameW(NULL, exe, MAX_PATH);
        si.cb = sizeof(si);
        swprintf(command, 2 * MAX_PATH, L"\"%ls\" --child %llx %ls", exe,
                 (unsigned long long)(ULONG_PTR)holder, unaware ? L"unaware" : L"aware");
        if (!CreateProcessW(NULL, command, NULL, NULL, TRUE, 0, NULL, NULL, &si, &pi)) return 2;
        CloseHandle(pi.hProcess);
        CloseHandle(pi.hThread);
    }
    while (GetMessageA(&msg, NULL, 0, 0) > 0) { TranslateMessage(&msg); DispatchMessageA(&msg); }
    return failures ? 1 : 0;
}
