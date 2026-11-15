#include <windows.h>

#ifndef IMAGE_MARKER
#define IMAGE_MARKER 101
#endif

__declspec(dllexport) const unsigned char readonly_blob[16 * 1024 * 1024] = {43, [16 * 1024 * 1024 - 1] = 111};
static const char text[] = "pe-image-cache";
__declspec(dllexport) const char *const relocated_pointer = text;
static LONG counter;
static DWORD owner;
__attribute__((section(".shared"))) LONG shared_counter;

__declspec(dllexport) int image_marker(void) { return IMAGE_MARKER; }
__declspec(dllexport) const char *image_pointer(void)
{
    return *(const char *volatile const *)&relocated_pointer;
}
__declspec(dllexport) LONG image_bump(void) { return InterlockedIncrement(&counter); }
__declspec(dllexport) LONG image_shared_bump(void) { return InterlockedIncrement(&shared_counter); }
__declspec(dllexport) DWORD image_owner(void) { return owner; }

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, void *reserved)
{
    (void)instance;
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) owner = GetCurrentProcessId();
    return TRUE;
}
