/* Simulate DuiLib's public switch and its login configuration override. */
#include <windows.h>
static BOOL enabled;
void __cdecl SetFlag(BOOL value) { enabled = value; }
__declspec(dllexport) BOOL __cdecl TestEnabled(void) { return enabled; }
__declspec(dllexport) void __cdecl TestOverride(void) { enabled = FALSE; }
