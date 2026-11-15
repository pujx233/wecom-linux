#define _WIN32_WINNT 0x0600
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define THREADS 12
static HANDLE threads[THREADS], ready[THREADS];
static HWND windows[THREADS];

static LRESULT CALLBACK window_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    if (msg == WM_APP) return GetCurrentThreadId();
    if (msg == WM_DESTROY) { PostQuitMessage(0); return 0; }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

static DWORD WINAPI worker(void *arg)
{
    unsigned int i = (unsigned int)(ULONG_PTR)arg;
    MSG msg;
    windows[i] = CreateWindowW(L"WeComXimReconnect", L"XIM reconnect fixture", WS_OVERLAPPEDWINDOW,
                              30 + i * 18, 30 + i * 18, 180, 100, NULL, NULL, GetModuleHandleW(NULL), NULL);
    SetEvent(ready[i]);
    if (!windows[i]) return 1;
    while (GetMessageW(&msg, NULL, 0, 0) > 0) DispatchMessageW(&msg);
    windows[i] = NULL;
    return 0;
}

static int spawn(unsigned int i)
{
    ResetEvent(ready[i]);
    threads[i] = CreateThread(NULL, 0, worker, (void *)(ULONG_PTR)i, 0, NULL);
    return threads[i] && WaitForSingleObject(ready[i], 10000) == WAIT_OBJECT_0 && windows[i];
}

int main(void)
{
    WNDCLASSW cls = {.lpfnWndProc = window_proc, .hInstance = GetModuleHandleW(NULL),
                    .lpszClassName = L"WeComXimReconnect"};
    char cmd[32];
    unsigned int i;
    if (!RegisterClassW(&cls)) return 2;
    for (i = 0; i < THREADS; i++)
    {
        ready[i] = CreateEventW(NULL, TRUE, FALSE, NULL);
        if (!ready[i] || !spawn(i)) return 3;
    }
    puts("{\"event\":\"ready\",\"threads\":12}"); fflush(stdout);
    while (fgets(cmd, sizeof(cmd), stdin))
    {
        if (!strncmp(cmd, "quit", 4)) break;
        if (!strncmp(cmd, "drop", 4))
        {
            for (i = 0; i < THREADS / 2; i++) PostMessageW(windows[i], WM_CLOSE, 0, 0);
            for (i = 0; i < THREADS / 2; i++)
            {
                if (WaitForSingleObject(threads[i], 10000) != WAIT_OBJECT_0) return 4;
                CloseHandle(threads[i]); threads[i] = NULL;
            }
            puts("{\"event\":\"drop\",\"threads\":6}"); fflush(stdout); continue;
        }
        if (!strncmp(cmd, "spawn", 5))
            for (i = 0; i < THREADS / 2; i++) if (!spawn(i)) return 5;
        for (i = 0; i < THREADS; i++)
        {
            DWORD_PTR result;
            if (!windows[i] || !SendMessageTimeoutW(windows[i], WM_APP, 0, 0, SMTO_ABORTIFHUNG, 3000, &result))
                return 6;
        }
        puts("{\"event\":\"ping\",\"threads\":12}"); fflush(stdout);
    }
    for (i = 0; i < THREADS; i++) if (windows[i]) PostMessageW(windows[i], WM_CLOSE, 0, 0);
    for (i = 0; i < THREADS; i++)
    {
        if (threads[i])
        {
            if (WaitForSingleObject(threads[i], 10000) != WAIT_OBJECT_0) return 7;
            CloseHandle(threads[i]);
        }
        CloseHandle(ready[i]);
    }
    return 0;
}
