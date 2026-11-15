#include <windows.h>

#ifndef IMAGE_MARKER
#define IMAGE_MARKER 101
#endif

static LONG counter;
static DWORD owner;
static const char text[] = "cef-image-cache";
__attribute__((section(".shared"))) LONG shared_counter;

__declspec(dllexport) int image_marker(void) { return IMAGE_MARKER; }
__declspec(dllexport) const char *image_pointer(void) { return text; }
__declspec(dllexport) LONG image_bump(void) { return InterlockedIncrement(&counter); }
__declspec(dllexport) LONG image_shared_bump(void) { return InterlockedIncrement(&shared_counter); }
__declspec(dllexport) DWORD image_owner(void) { return owner; }
__declspec(dllexport) void cache_probe(void) { MemoryBarrier(); }

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, void *reserved)
{
    (void)instance;
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) owner = GetCurrentProcessId();
    return TRUE;
}
