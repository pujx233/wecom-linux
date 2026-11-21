// Account-free ABI and COM lifetime fixture for the installed msftedit adapter.
#include <windows.h>
#include <richedit.h>
#include <textserv.h>
#include <new>
#include <stdio.h>
#include <stdlib.h>

static const IID service_iid =
    {0x8d33f740,0xcf58,0x11ce,{0xa8,0x9d,0x00,0xaa,0x00,0x6c,0xad,0xc5}};
static const IID extra_iid =
    {0x76e43b32,0x3402,0x4710,{0xa8,0x8a,0x51,0x23,0x00,0x44,0x30,0xa9}};

static ULONG_PTR argument_hash(ULONG_PTR value, ULONG_PTR next)
{
    return (value * 33) ^ next;
}
#define CHECK(value) do { if (!(value)) { printf("FAIL line %d\n", __LINE__); return 1; } ++checks; } while (0)

int main(int argc, char **argv)
{
    unsigned int checks = 0;
    bool enabled = argc > 1 && !strcmp(argv[1], "enabled");
    bool missing = argc > 1 && !strcmp(argv[1], "missing");
    HMODULE dui = missing ? nullptr : LoadLibraryW(L"DuiLib.dll");
    CHECK(missing || dui);
    auto get_enabled = (BOOL (__cdecl *)(void))(void *)GetProcAddress(dui, "TestEnabled");
    auto override_flag = (void (__cdecl *)(void))(void *)GetProcAddress(dui, "TestOverride");
    HMODULE module = LoadLibraryW(L"msftedit.dll");
    CHECK(module);
    auto factory = (HRESULT (WINAPI *)(IUnknown *, ITextHost *, IUnknown **))
        (void *)GetProcAddress(module, "CreateTextServices");
    HMODULE backend = GetModuleHandleW(L"riched20.dll");
    auto value = (ULONG_PTR (WINAPI *)(UINT))(void *)GetProcAddress(backend, "TestValue");
    auto fail = (void (WINAPI *)(BOOL))(void *)GetProcAddress(backend, "TestFail");
    CHECK(factory && value && fail);
    ITextHost *host = (ITextHost *)(ULONG_PTR)0x101230;
    for (int repeat = 0; repeat < 100; ++repeat)
    {
        if (dui) override_flag();
        IUnknown *unknown = nullptr, *identity = nullptr, *extra = nullptr;
        ITextServices *service = nullptr;
        CHECK(factory(nullptr, host, &unknown) == S_OK);
        CHECK(unknown && value(0) == 1 && value(3) == (ULONG_PTR)host);
        CHECK((value(4) != 0) == enabled);
        CHECK(!dui || get_enabled() == enabled);
        CHECK(unknown->QueryInterface(service_iid, (void **)&service) == S_OK);
        CHECK(service->QueryInterface(IID_IUnknown, (void **)&identity) == S_OK && identity == unknown);
        identity->Release();
        CHECK(service->QueryInterface(extra_iid, (void **)&extra) == S_OK);
        CHECK(extra->QueryInterface(IID_IUnknown, (void **)&identity) == S_OK && identity == unknown);
        identity->Release();
        extra->Release();
        unknown->Release();
        ULONG_PTR expected;
        HRESULT result;
        expected = 5381;
        expected = argument_hash(expected, (ULONG_PTR)((UINT)(ULONG_PTR)4233));
        expected = argument_hash(expected, (ULONG_PTR)((WPARAM)(ULONG_PTR)4242));
        expected = argument_hash(expected, (ULONG_PTR)((LPARAM)(ULONG_PTR)4251));
        expected = argument_hash(expected, (ULONG_PTR)((LRESULT*)(ULONG_PTR)4260));
        if (dui) override_flag();
        result = service->TxSendMessage((UINT)(ULONG_PTR)4233, (WPARAM)(ULONG_PTR)4242,
        (LPARAM)(ULONG_PTR)4251, (LRESULT*)(ULONG_PTR)4260);
        CHECK(result == 0x12340000 + 1 && value(1) == 1 && value(2) == expected);
        CHECK(!dui || get_enabled() == enabled);
        expected = 5381;
        expected = argument_hash(expected, (ULONG_PTR)((DWORD)(ULONG_PTR)4361));
        expected = argument_hash(expected, (ULONG_PTR)((LONG)(ULONG_PTR)4370));
        expected = argument_hash(expected, (ULONG_PTR)((void*)(ULONG_PTR)4379));
        expected = argument_hash(expected, (ULONG_PTR)((DVTARGETDEVICE*)(ULONG_PTR)4388));
        expected = argument_hash(expected, (ULONG_PTR)((HDC)(ULONG_PTR)4397));
        expected = argument_hash(expected, (ULONG_PTR)((HDC)(ULONG_PTR)4406));
        expected = argument_hash(expected, (ULONG_PTR)((LPCRECTL)(ULONG_PTR)4415));
        expected = argument_hash(expected, (ULONG_PTR)((LPCRECTL)(ULONG_PTR)4424));
        expected = argument_hash(expected, (ULONG_PTR)((LPRECT)(ULONG_PTR)4433));
        expected = argument_hash(expected, (ULONG_PTR)((BOOL (CALLBACK *)(DWORD))(ULONG_PTR)4442));
        expected = argument_hash(expected, (ULONG_PTR)((DWORD)(ULONG_PTR)4451));
        expected = argument_hash(expected, (ULONG_PTR)((LONG)(ULONG_PTR)4460));
        result = service->TxDraw((DWORD)(ULONG_PTR)4361, (LONG)(ULONG_PTR)4370, (void*)(ULONG_PTR)4379,
        (DVTARGETDEVICE*)(ULONG_PTR)4388, (HDC)(ULONG_PTR)4397, (HDC)(ULONG_PTR)4406,
        (LPCRECTL)(ULONG_PTR)4415, (LPCRECTL)(ULONG_PTR)4424, (LPRECT)(ULONG_PTR)4433,
        (BOOL (CALLBACK *)(DWORD))(ULONG_PTR)4442, (DWORD)(ULONG_PTR)4451, (LONG)(ULONG_PTR)4460);
        CHECK(result == 0x12340000 + 2 && value(1) == 2 && value(2) == expected);
        expected = 5381;
        expected = argument_hash(expected, (ULONG_PTR)((LONG*)(ULONG_PTR)4489));
        expected = argument_hash(expected, (ULONG_PTR)((LONG*)(ULONG_PTR)4498));
        expected = argument_hash(expected, (ULONG_PTR)((LONG*)(ULONG_PTR)4507));
        expected = argument_hash(expected, (ULONG_PTR)((LONG*)(ULONG_PTR)4516));
        expected = argument_hash(expected, (ULONG_PTR)((BOOL*)(ULONG_PTR)4525));
        result = service->TxGetHScroll((LONG*)(ULONG_PTR)4489, (LONG*)(ULONG_PTR)4498, (LONG*)(ULONG_PTR)4507,
        (LONG*)(ULONG_PTR)4516, (BOOL*)(ULONG_PTR)4525);
        CHECK(result == 0x12340000 + 3 && value(1) == 3 && value(2) == expected);
        expected = 5381;
        expected = argument_hash(expected, (ULONG_PTR)((LONG*)(ULONG_PTR)4617));
        expected = argument_hash(expected, (ULONG_PTR)((LONG*)(ULONG_PTR)4626));
        expected = argument_hash(expected, (ULONG_PTR)((LONG*)(ULONG_PTR)4635));
        expected = argument_hash(expected, (ULONG_PTR)((LONG*)(ULONG_PTR)4644));
        expected = argument_hash(expected, (ULONG_PTR)((BOOL*)(ULONG_PTR)4653));
        result = service->TxGetVScroll((LONG*)(ULONG_PTR)4617, (LONG*)(ULONG_PTR)4626, (LONG*)(ULONG_PTR)4635,
        (LONG*)(ULONG_PTR)4644, (BOOL*)(ULONG_PTR)4653);
        CHECK(result == 0x12340000 + 4 && value(1) == 4 && value(2) == expected);
        expected = 5381;
        expected = argument_hash(expected, (ULONG_PTR)((DWORD)(ULONG_PTR)4745));
        expected = argument_hash(expected, (ULONG_PTR)((LONG)(ULONG_PTR)4754));
        expected = argument_hash(expected, (ULONG_PTR)((void*)(ULONG_PTR)4763));
        expected = argument_hash(expected, (ULONG_PTR)((DVTARGETDEVICE*)(ULONG_PTR)4772));
        expected = argument_hash(expected, (ULONG_PTR)((HDC)(ULONG_PTR)4781));
        expected = argument_hash(expected, (ULONG_PTR)((HDC)(ULONG_PTR)4790));
        expected = argument_hash(expected, (ULONG_PTR)((LPCRECT)(ULONG_PTR)4799));
        expected = argument_hash(expected, (ULONG_PTR)((INT)(ULONG_PTR)4808));
        expected = argument_hash(expected, (ULONG_PTR)((INT)(ULONG_PTR)4817));
        result = service->OnTxSetCursor((DWORD)(ULONG_PTR)4745, (LONG)(ULONG_PTR)4754, (void*)(ULONG_PTR)4763,
        (DVTARGETDEVICE*)(ULONG_PTR)4772, (HDC)(ULONG_PTR)4781, (HDC)(ULONG_PTR)4790, (LPCRECT)(ULONG_PTR)4799,
        (INT)(ULONG_PTR)4808, (INT)(ULONG_PTR)4817);
        CHECK(result == 0x12340000 + 5 && value(1) == 5 && value(2) == expected);
        expected = 5381;
        expected = argument_hash(expected, (ULONG_PTR)((DWORD)(ULONG_PTR)4873));
        expected = argument_hash(expected, (ULONG_PTR)((LONG)(ULONG_PTR)4882));
        expected = argument_hash(expected, (ULONG_PTR)((void*)(ULONG_PTR)4891));
        expected = argument_hash(expected, (ULONG_PTR)((DVTARGETDEVICE*)(ULONG_PTR)4900));
        expected = argument_hash(expected, (ULONG_PTR)((HDC)(ULONG_PTR)4909));
        expected = argument_hash(expected, (ULONG_PTR)((HDC)(ULONG_PTR)4918));
        expected = argument_hash(expected, (ULONG_PTR)((LPCRECT)(ULONG_PTR)4927));
        expected = argument_hash(expected, (ULONG_PTR)((INT)(ULONG_PTR)4936));
        expected = argument_hash(expected, (ULONG_PTR)((INT)(ULONG_PTR)4945));
        expected = argument_hash(expected, (ULONG_PTR)((DWORD*)(ULONG_PTR)4954));
        result = service->TxQueryHitPoint((DWORD)(ULONG_PTR)4873, (LONG)(ULONG_PTR)4882,
        (void*)(ULONG_PTR)4891, (DVTARGETDEVICE*)(ULONG_PTR)4900, (HDC)(ULONG_PTR)4909, (HDC)(ULONG_PTR)4918,
        (LPCRECT)(ULONG_PTR)4927, (INT)(ULONG_PTR)4936, (INT)(ULONG_PTR)4945, (DWORD*)(ULONG_PTR)4954);
        CHECK(result == 0x12340000 + 6 && value(1) == 6 && value(2) == expected);
        expected = 5381;
        expected = argument_hash(expected, (ULONG_PTR)((LPCRECT)(ULONG_PTR)5001));
        if (dui) override_flag();
        result = service->OnTxInPlaceActivate((LPCRECT)(ULONG_PTR)5001);
        CHECK(result == 0x12340000 + 7 && value(1) == 7 && value(2) == expected);
        CHECK(!dui || get_enabled() == enabled);
        expected = 5381;
        result = service->OnTxInPlaceDeactivate();
        CHECK(result == 0x12340000 + 8 && value(1) == 8 && value(2) == expected);
        expected = 5381;
        result = service->OnTxUIActivate();
        CHECK(result == 0x12340000 + 9 && value(1) == 9 && value(2) == expected);
        expected = 5381;
        result = service->OnTxUIDeactivate();
        CHECK(result == 0x12340000 + 10 && value(1) == 10 && value(2) == expected);
        expected = 5381;
        expected = argument_hash(expected, (ULONG_PTR)((BSTR*)(ULONG_PTR)5513));
        result = service->TxGetText((BSTR*)(ULONG_PTR)5513);
        CHECK(result == 0x12340000 + 11 && value(1) == 11 && value(2) == expected);
        expected = 5381;
        expected = argument_hash(expected, (ULONG_PTR)((LPCWSTR)(ULONG_PTR)5641));
        result = service->TxSetText((LPCWSTR)(ULONG_PTR)5641);
        CHECK(result == 0x12340000 + 12 && value(1) == 12 && value(2) == expected);
        expected = 5381;
        expected = argument_hash(expected, (ULONG_PTR)((LONG*)(ULONG_PTR)5769));
        result = service->TxGetCurTargetX((LONG*)(ULONG_PTR)5769);
        CHECK(result == 0x12340000 + 13 && value(1) == 13 && value(2) == expected);
        expected = 5381;
        expected = argument_hash(expected, (ULONG_PTR)((LONG*)(ULONG_PTR)5897));
        result = service->TxGetBaseLinePos((LONG*)(ULONG_PTR)5897);
        CHECK(result == 0x12340000 + 14 && value(1) == 14 && value(2) == expected);
        expected = 5381;
        expected = argument_hash(expected, (ULONG_PTR)((DWORD)(ULONG_PTR)6025));
        expected = argument_hash(expected, (ULONG_PTR)((HDC)(ULONG_PTR)6034));
        expected = argument_hash(expected, (ULONG_PTR)((HDC)(ULONG_PTR)6043));
        expected = argument_hash(expected, (ULONG_PTR)((DVTARGETDEVICE*)(ULONG_PTR)6052));
        expected = argument_hash(expected, (ULONG_PTR)((DWORD)(ULONG_PTR)6061));
        expected = argument_hash(expected, (ULONG_PTR)((const SIZEL*)(ULONG_PTR)6070));
        expected = argument_hash(expected, (ULONG_PTR)((LONG*)(ULONG_PTR)6079));
        expected = argument_hash(expected, (ULONG_PTR)((LONG*)(ULONG_PTR)6088));
        result = service->TxGetNaturalSize((DWORD)(ULONG_PTR)6025, (HDC)(ULONG_PTR)6034, (HDC)(ULONG_PTR)6043,
        (DVTARGETDEVICE*)(ULONG_PTR)6052, (DWORD)(ULONG_PTR)6061, (const SIZEL*)(ULONG_PTR)6070,
        (LONG*)(ULONG_PTR)6079, (LONG*)(ULONG_PTR)6088);
        CHECK(result == 0x12340000 + 15 && value(1) == 15 && value(2) == expected);
        expected = 5381;
        expected = argument_hash(expected, (ULONG_PTR)((IDropTarget**)(ULONG_PTR)6153));
        result = service->TxGetDropTarget((IDropTarget**)(ULONG_PTR)6153);
        CHECK(result == 0x12340000 + 16 && value(1) == 16 && value(2) == expected);
        expected = 5381;
        expected = argument_hash(expected, (ULONG_PTR)((DWORD)(ULONG_PTR)6281));
        expected = argument_hash(expected, (ULONG_PTR)((DWORD)(ULONG_PTR)6290));
        result = service->OnTxPropertyBitsChange((DWORD)(ULONG_PTR)6281, (DWORD)(ULONG_PTR)6290);
        CHECK(result == 0x12340000 + 17 && value(1) == 17 && value(2) == expected);
        expected = 5381;
        expected = argument_hash(expected, (ULONG_PTR)((DWORD*)(ULONG_PTR)6409));
        expected = argument_hash(expected, (ULONG_PTR)((DWORD*)(ULONG_PTR)6418));
        result = service->TxGetCachedSize((DWORD*)(ULONG_PTR)6409, (DWORD*)(ULONG_PTR)6418);
        CHECK(result == 0x12340000 + 18 && value(1) == 18 && value(2) == expected);
        CHECK(service->Release() == 0 && value(0) == 0);
    }
    IUnknown *outer = (IUnknown *)(ULONG_PTR)0x987650;
    IUnknown *aggregated = nullptr;
    CHECK(factory(outer, host, &aggregated) == S_OK);
    CHECK(aggregated && value(4) == (ULONG_PTR)outer && value(3) == (ULONG_PTR)host);
    CHECK(aggregated->Release() == 0 && !value(0));
    IUnknown *unknown = (IUnknown *)(ULONG_PTR)0x1234;
    fail(TRUE);
    CHECK(factory(nullptr, host, &unknown) == E_ABORT && !unknown && !value(0));
    printf("PASS checks=%u repeats=100 methods=18 enabled=%d missing=%d\n", checks, enabled, missing);
    return 0;
}
