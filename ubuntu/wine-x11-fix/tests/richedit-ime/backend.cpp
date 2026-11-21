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
static LONG live, last_method, fail_factory;
static ULONG_PTR last_hash, last_host, last_outer;

class Service : public ITextServices
{
public:
    class Inner : public IUnknown
    {
    public:
        Service *service;
        LONG refs;
        explicit Inner(Service *s) : service(s), refs(1) {}
        HRESULT WINAPI QueryInterface(REFIID iid, void **object) override
        {
            *object = nullptr;
            if (IsEqualIID(iid, IID_IUnknown))
            {
                *object = this;
                AddRef();
            }
            else if (IsEqualIID(iid, service_iid) || IsEqualIID(iid, extra_iid))
            {
                *object = static_cast<ITextServices *>(service);
                service->AddRef();
            }
            else return E_NOINTERFACE;
            return S_OK;
        }
        ULONG WINAPI AddRef() override { return InterlockedIncrement(&refs); }
        ULONG WINAPI Release() override
        {
            ULONG result = InterlockedDecrement(&refs);
            if (!result)
            {
                service->~Service();
                free(service);
                InterlockedDecrement(&live);
            }
            return result;
        }
    } inner;
    IUnknown *controller;
    explicit Service(IUnknown *outer) : inner(this), controller(outer ? outer : &inner) {}
    HRESULT WINAPI QueryInterface(REFIID iid, void **object) override
    {
        return controller->QueryInterface(iid, object);
    }
    ULONG WINAPI AddRef() override { return controller->AddRef(); }
    ULONG WINAPI Release() override { return controller->Release(); }
    HRESULT TxSendMessage(UINT msg, WPARAM wparam, LPARAM lparam, LRESULT* plresult) override
    {
        last_method = 1;
        last_hash = 5381;
        last_hash = argument_hash(last_hash, (ULONG_PTR)msg);
        last_hash = argument_hash(last_hash, (ULONG_PTR)wparam);
        last_hash = argument_hash(last_hash, (ULONG_PTR)lparam);
        last_hash = argument_hash(last_hash, (ULONG_PTR)plresult);
        return 0x12340000 + 1;
    }
    HRESULT TxDraw(DWORD dwDrawAspect, LONG lindex, void* pvAspect, DVTARGETDEVICE* ptd, HDC hdcDraw,
        HDC hicTargetDev, LPCRECTL lprcBounds, LPCRECTL lprcWBounds, LPRECT lprcUpdate,
        BOOL (CALLBACK * pfnContinue)(DWORD), DWORD dwContinue, LONG lViewId) override
    {
        last_method = 2;
        last_hash = 5381;
        last_hash = argument_hash(last_hash, (ULONG_PTR)dwDrawAspect);
        last_hash = argument_hash(last_hash, (ULONG_PTR)lindex);
        last_hash = argument_hash(last_hash, (ULONG_PTR)pvAspect);
        last_hash = argument_hash(last_hash, (ULONG_PTR)ptd);
        last_hash = argument_hash(last_hash, (ULONG_PTR)hdcDraw);
        last_hash = argument_hash(last_hash, (ULONG_PTR)hicTargetDev);
        last_hash = argument_hash(last_hash, (ULONG_PTR)lprcBounds);
        last_hash = argument_hash(last_hash, (ULONG_PTR)lprcWBounds);
        last_hash = argument_hash(last_hash, (ULONG_PTR)lprcUpdate);
        last_hash = argument_hash(last_hash, (ULONG_PTR)pfnContinue);
        last_hash = argument_hash(last_hash, (ULONG_PTR)dwContinue);
        last_hash = argument_hash(last_hash, (ULONG_PTR)lViewId);
        return 0x12340000 + 2;
    }
    HRESULT TxGetHScroll(LONG* plMin, LONG* plMax, LONG* plPos, LONG* plPage, BOOL* pfEnabled) override
    {
        last_method = 3;
        last_hash = 5381;
        last_hash = argument_hash(last_hash, (ULONG_PTR)plMin);
        last_hash = argument_hash(last_hash, (ULONG_PTR)plMax);
        last_hash = argument_hash(last_hash, (ULONG_PTR)plPos);
        last_hash = argument_hash(last_hash, (ULONG_PTR)plPage);
        last_hash = argument_hash(last_hash, (ULONG_PTR)pfEnabled);
        return 0x12340000 + 3;
    }
    HRESULT TxGetVScroll(LONG* plMin, LONG* plMax, LONG* plPos, LONG* plPage, BOOL* pfEnabled) override
    {
        last_method = 4;
        last_hash = 5381;
        last_hash = argument_hash(last_hash, (ULONG_PTR)plMin);
        last_hash = argument_hash(last_hash, (ULONG_PTR)plMax);
        last_hash = argument_hash(last_hash, (ULONG_PTR)plPos);
        last_hash = argument_hash(last_hash, (ULONG_PTR)plPage);
        last_hash = argument_hash(last_hash, (ULONG_PTR)pfEnabled);
        return 0x12340000 + 4;
    }
    HRESULT OnTxSetCursor(DWORD dwDrawAspect, LONG lindex, void* pvAspect, DVTARGETDEVICE* ptd, HDC hdcDraw,
        HDC hicTargetDev, LPCRECT lprcClient, INT x, INT y) override
    {
        last_method = 5;
        last_hash = 5381;
        last_hash = argument_hash(last_hash, (ULONG_PTR)dwDrawAspect);
        last_hash = argument_hash(last_hash, (ULONG_PTR)lindex);
        last_hash = argument_hash(last_hash, (ULONG_PTR)pvAspect);
        last_hash = argument_hash(last_hash, (ULONG_PTR)ptd);
        last_hash = argument_hash(last_hash, (ULONG_PTR)hdcDraw);
        last_hash = argument_hash(last_hash, (ULONG_PTR)hicTargetDev);
        last_hash = argument_hash(last_hash, (ULONG_PTR)lprcClient);
        last_hash = argument_hash(last_hash, (ULONG_PTR)x);
        last_hash = argument_hash(last_hash, (ULONG_PTR)y);
        return 0x12340000 + 5;
    }
    HRESULT TxQueryHitPoint(DWORD dwDrawAspect, LONG lindex, void* pvAspect, DVTARGETDEVICE* ptd, HDC hdcDraw,
        HDC hicTargetDev, LPCRECT lprcClient, INT x, INT y, DWORD* pHitResult) override
    {
        last_method = 6;
        last_hash = 5381;
        last_hash = argument_hash(last_hash, (ULONG_PTR)dwDrawAspect);
        last_hash = argument_hash(last_hash, (ULONG_PTR)lindex);
        last_hash = argument_hash(last_hash, (ULONG_PTR)pvAspect);
        last_hash = argument_hash(last_hash, (ULONG_PTR)ptd);
        last_hash = argument_hash(last_hash, (ULONG_PTR)hdcDraw);
        last_hash = argument_hash(last_hash, (ULONG_PTR)hicTargetDev);
        last_hash = argument_hash(last_hash, (ULONG_PTR)lprcClient);
        last_hash = argument_hash(last_hash, (ULONG_PTR)x);
        last_hash = argument_hash(last_hash, (ULONG_PTR)y);
        last_hash = argument_hash(last_hash, (ULONG_PTR)pHitResult);
        return 0x12340000 + 6;
    }
    HRESULT OnTxInPlaceActivate(LPCRECT prcClient) override
    {
        last_method = 7;
        last_hash = 5381;
        last_hash = argument_hash(last_hash, (ULONG_PTR)prcClient);
        return 0x12340000 + 7;
    }
    HRESULT OnTxInPlaceDeactivate() override
    {
        last_method = 8;
        last_hash = 5381;
        return 0x12340000 + 8;
    }
    HRESULT OnTxUIActivate() override
    {
        last_method = 9;
        last_hash = 5381;
        return 0x12340000 + 9;
    }
    HRESULT OnTxUIDeactivate() override
    {
        last_method = 10;
        last_hash = 5381;
        return 0x12340000 + 10;
    }
    HRESULT TxGetText(BSTR* pbstrText) override
    {
        last_method = 11;
        last_hash = 5381;
        last_hash = argument_hash(last_hash, (ULONG_PTR)pbstrText);
        return 0x12340000 + 11;
    }
    HRESULT TxSetText(LPCWSTR pszText) override
    {
        last_method = 12;
        last_hash = 5381;
        last_hash = argument_hash(last_hash, (ULONG_PTR)pszText);
        return 0x12340000 + 12;
    }
    HRESULT TxGetCurTargetX(LONG* x) override
    {
        last_method = 13;
        last_hash = 5381;
        last_hash = argument_hash(last_hash, (ULONG_PTR)x);
        return 0x12340000 + 13;
    }
    HRESULT TxGetBaseLinePos(LONG* x) override
    {
        last_method = 14;
        last_hash = 5381;
        last_hash = argument_hash(last_hash, (ULONG_PTR)x);
        return 0x12340000 + 14;
    }
    HRESULT TxGetNaturalSize(DWORD dwAspect, HDC hdcDraw, HDC hicTargetDev, DVTARGETDEVICE* ptd, DWORD dwMode,
        const SIZEL* psizelExtent, LONG* pwidth, LONG* pheight) override
    {
        last_method = 15;
        last_hash = 5381;
        last_hash = argument_hash(last_hash, (ULONG_PTR)dwAspect);
        last_hash = argument_hash(last_hash, (ULONG_PTR)hdcDraw);
        last_hash = argument_hash(last_hash, (ULONG_PTR)hicTargetDev);
        last_hash = argument_hash(last_hash, (ULONG_PTR)ptd);
        last_hash = argument_hash(last_hash, (ULONG_PTR)dwMode);
        last_hash = argument_hash(last_hash, (ULONG_PTR)psizelExtent);
        last_hash = argument_hash(last_hash, (ULONG_PTR)pwidth);
        last_hash = argument_hash(last_hash, (ULONG_PTR)pheight);
        return 0x12340000 + 15;
    }
    HRESULT TxGetDropTarget(IDropTarget** ppDropTarget) override
    {
        last_method = 16;
        last_hash = 5381;
        last_hash = argument_hash(last_hash, (ULONG_PTR)ppDropTarget);
        return 0x12340000 + 16;
    }
    HRESULT OnTxPropertyBitsChange(DWORD dwMask, DWORD dwBits) override
    {
        last_method = 17;
        last_hash = 5381;
        last_hash = argument_hash(last_hash, (ULONG_PTR)dwMask);
        last_hash = argument_hash(last_hash, (ULONG_PTR)dwBits);
        return 0x12340000 + 17;
    }
    HRESULT TxGetCachedSize(DWORD* pdwWidth, DWORD* pdwHeight) override
    {
        last_method = 18;
        last_hash = 5381;
        last_hash = argument_hash(last_hash, (ULONG_PTR)pdwWidth);
        last_hash = argument_hash(last_hash, (ULONG_PTR)pdwHeight);
        return 0x12340000 + 18;
    }
};

extern "C" __declspec(dllexport) HRESULT WINAPI CreateTextServices(IUnknown *outer, ITextHost *host,
                                                                  IUnknown **object)
{
    last_host = (ULONG_PTR)host;
    last_outer = (ULONG_PTR)outer;
    *object = nullptr;
    if (fail_factory) return E_ABORT;
    void *memory = malloc(sizeof(Service));
    if (!memory) return E_OUTOFMEMORY;
    Service *service = new (memory) Service(outer);
    InterlockedIncrement(&live);
    *object = &service->inner;
    return S_OK;
}
extern "C" __declspec(dllexport) ULONG_PTR WINAPI TestValue(UINT index)
{
    switch (index)
    {
    case 0: return live;
    case 1: return last_method;
    case 2: return last_hash;
    case 3: return last_host;
    case 4: return last_outer;
    }
    return 0;
}
extern "C" __declspec(dllexport) void WINAPI TestFail(BOOL fail) { fail_factory = fail; }
