/* Check that native mode leaves foreground restoration to Wine instead of
 * queuing a second command. This tests the helper policy, not Wine integration. */
#define __declspec(x)
#define __stdcall
#ifndef TITLEBAR_SOURCE
#define TITLEBAR_SOURCE "../../../scripts/titlebar-managed.c"
#endif
#include TITLEBAR_SOURCE

static int commands;
HANDLE GetForegroundWindow(void) { return main_window; }
BOOL IsWindowVisible(HANDLE window) { return 1; }
BOOL IsIconic(HANDLE window) { return 1; }
long GetWindowLongA(HANDLE window,int index) { return 0; }
BOOL PostMessageA(HANDLE window,unsigned message,unsigned wparam,long lparam)
{
    if(window!=main_window||message!=0x0112||wparam!=0xf120||lparam)return 0;
    commands++;
    return 1;
}
HANDLE GetStdHandle(DWORD index) { return 0; }
BOOL WriteFile(HANDLE file,const void *buffer,DWORD bytes,DWORD *written,void *overlapped)
{
    *written=bytes;
    return 1;
}

int main(void)
{
    main_window=(HANDLE)1;
    native_frames=1;
    restore_foreground_main(main_window);
    /* Wine now restores to maximized state. Any queued SC_RESTORE would then
       restore it a second time, to normal; native mode must leave it alone. */
    if(commands)return 1;
    native_frames=0;
    restore_foreground_main(main_window);
    if(commands!=1)return 2; /* Preserve the explicit legacy compatibility path. */
    restore_foreground_main((HANDLE)2);
    return commands!=1;
}
