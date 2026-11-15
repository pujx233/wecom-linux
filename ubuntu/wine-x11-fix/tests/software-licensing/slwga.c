#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <slpublic.h>
#include <stdio.h>

typedef HRESULT (WINAPI *query_genuine)(const SLID *, SL_GENUINE_STATE *, SL_NONGENUINE_UI_OPTIONS *);

static unsigned failures, checks;

static void check(BOOL passed, const char *name)
{
    ++checks;
    if (!passed)
    {
        ++failures;
        fprintf(stderr, "Failed: %s\n", name);
    }
}

int main(void)
{
    const SLID app = {0x55c92734, 0xd682, 0x4d71, {0x98, 0x3e, 0xd6, 0xec, 0x3f, 0x16, 0x05, 0x9f}};
    HMODULE module = LoadLibraryW(L"slwga.dll");
    query_genuine query;
    SL_GENUINE_STATE state;
    SL_NONGENUINE_UI_OPTIONS options = {sizeof(options), &app, (HRESULT)0xdeadbeef};
    HRESULT result;
    if (!module)
    {
        printf("{\"loaded\":false,\"error\":%lu}\n", GetLastError());
        return 1;
    }
    query = (query_genuine)(void *)GetProcAddress(module, "SLIsGenuineLocal");
    if (!query) return 2;
    state = SL_GEN_STATE_TAMPERED;
    check(query(NULL, &state, NULL) == E_INVALIDARG, "null application");
    check(state == SL_GEN_STATE_TAMPERED, "invalid call preserves state");
    check(query(&app, NULL, NULL) == E_INVALIDARG, "null state");
    check(query(NULL, NULL, NULL) == E_INVALIDARG, "both mandatory pointers null");
    SetLastError(0xdeadbeef);
    result = query(&app, &state, NULL);
    check(result == E_NOTIMPL, "unsupported provider returns failure");
    check(state == SL_GEN_STATE_TAMPERED, "failed query preserves state");
    check(GetLastError() == 0xdeadbeef, "HRESULT call preserves last error");
    result = query(&app, &state, &options);
    check(result == E_NOTIMPL, "optional UI does not turn unsupported query into success");
    check(state == SL_GEN_STATE_TAMPERED && options.hResultUI == (HRESULT)0xdeadbeef,
          "failed query preserves optional output");
    check(FreeLibrary(module), "module unload");
    printf("{\"loaded\":true,\"checks\":%u,\"failures\":%u}\n", checks, failures);
    return failures != 0;
}
