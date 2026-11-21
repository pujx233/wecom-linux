#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>

static const POINT start = {200, 200}, first = {320, 260}, last = {470, 370};
static const INPUT wheel = {.type = INPUT_MOUSE, .mi = {.dwFlags = MOUSEEVENTF_WHEEL, .mouseData = WHEEL_DELTA}};
static UINT inject_message, injected;

static INPUT absolute_move(POINT point)
{
    int width = GetSystemMetrics(SM_CXSCREEN), height = GetSystemMetrics(SM_CYSCREEN);
    INPUT input = {.type = INPUT_MOUSE, .mi = {.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE}};
    input.mi.dx = ((point.x << 16) + width - 1) / width;
    input.mi.dy = ((point.y << 16) + height - 1) / height;
    return input;
}

static LRESULT CALLBACK on_mouse(int code, WPARAM message, LPARAM param)
{
    const MOUSEHOOKSTRUCT *mouse = (const MOUSEHOOKSTRUCT *)param;
    INPUT inputs[] = {absolute_move(last), {.type = INPUT_MOUSE, .mi.dwFlags = MOUSEEVENTF_LEFTUP}};

    if (code == HC_ACTION && message == inject_message)
    {
        if (message == WM_MOUSEMOVE && mouse->pt.x == first.x && mouse->pt.y == first.y)
        {
            inject_message = 0;
            injected = SendInput(2, inputs, sizeof(INPUT));
        }
        if (message == WM_MOUSEWHEEL)
        {
            INPUT input = wheel;
            inject_message = 0;
            injected = SendInput(1, &input, sizeof(INPUT));
        }
    }
    return CallNextHookEx(NULL, code, message, param);
}

static BOOL check_movement(HWND window, BOOL during_delivery)
{
    INPUT initial[] = {absolute_move(start), {.type = INPUT_MOUSE, .mi.dwFlags = MOUSEEVENTF_LEFTDOWN}};
    INPUT inputs[] = {absolute_move(first), absolute_move(last),
                      {.type = INPUT_MOUSE, .mi.dwFlags = MOUSEEVENTF_LEFTUP}};
    const UINT count = during_delivery ? 1 : 3;
    BOOL last_move = FALSE, release = FALSE;
    int moves = 0;
    MSG message;

    if (SendInput(2, initial, sizeof(INPUT)) != 2) return FALSE;
    while (PeekMessageW(&message, NULL, 0, 0, PM_REMOVE)) DispatchMessageW(&message);

    inject_message = during_delivery ? WM_MOUSEMOVE : 0;
    injected = 0;
    if (SendInput(count, inputs, sizeof(INPUT)) != count) return FALSE;
    while (PeekMessageW(&message, window, WM_MOUSEFIRST, WM_MOUSELAST, PM_REMOVE))
    {
        if (message.message == WM_MOUSEMOVE && (message.wParam & MK_LBUTTON))
        {
            if (message.pt.x == first.x || message.pt.x == last.x) ++moves;
            if (message.pt.x == last.x && message.pt.y == last.y) last_move = TRUE;
        }
        if (message.message == WM_LBUTTONUP)
        {
            release = message.pt.x == last.x && message.pt.y == last.y;
            break;
        }
    }
    printf("move during_delivery=%d injected=%u moves=%d endpoint_before_release=%d released=%d\n",
           during_delivery, injected, moves, last_move, release);
    return release && last_move && (during_delivery ? injected == 2 && moves == 2 : moves == 1);
}

static BOOL check_wheel(HWND window, BOOL during_delivery)
{
    INPUT inputs[] = {wheel, wheel};
    const UINT count = during_delivery ? 1 : 2;
    int total = 0, messages = 0;
    MSG message;

    inject_message = during_delivery ? WM_MOUSEWHEEL : 0;
    injected = 0;
    if (SendInput(count, inputs, sizeof(INPUT)) != count) return FALSE;
    while (PeekMessageW(&message, window, WM_MOUSEWHEEL, WM_MOUSEWHEEL, PM_REMOVE))
    {
        total += (short)HIWORD(message.wParam);
        ++messages;
    }
    printf("wheel during_delivery=%d injected=%u messages=%d total=%d\n", during_delivery, injected, messages, total);
    return total == WHEEL_DELTA * 2 && (during_delivery ? injected == 1 && messages == 2 : messages == 1);
}

int main(void)
{
    BOOL passed = TRUE;
    if (!SetProcessDPIAware()) return 1;
    HWND window = CreateWindowW(L"static", L"Exercise the mouse queue", WS_OVERLAPPEDWINDOW | WS_VISIBLE,
                                70, 100, 640, 460, NULL, NULL, GetModuleHandleW(NULL), NULL);
    if (!window) return 2;
    SetForegroundWindow(window);
    SetFocus(window);
    SetCapture(window);
    HHOOK hook = SetWindowsHookExW(WH_MOUSE, on_mouse, NULL, GetCurrentThreadId());
    if (!hook) return 3;
    passed &= check_movement(window, FALSE);
    passed &= check_movement(window, TRUE);
    passed &= check_wheel(window, FALSE);
    passed &= check_wheel(window, TRUE);
    UnhookWindowsHookEx(hook);
    ReleaseCapture();
    DestroyWindow(window);
    return passed ? 0 : 4;
}
