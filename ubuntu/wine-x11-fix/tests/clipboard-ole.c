#define COBJMACROS
#define _WIN32_WINNT 0x0601
#include <windows.h>
#include <ole2.h>
#include <shlobj.h>
#include <stdio.h>
#include <string.h>

static const DWORD pixels[] = {0x00112233, 0x00445566, 0x00778899, 0x00abcdef, 0x00abcdef, 0x0000ff00};
static BOOL target_device;

static LONG WINAPI exception_filter(EXCEPTION_POINTERS *exception)
{
    fprintf(stderr, "exception=%08lx\n", exception->ExceptionRecord->ExceptionCode);
    ExitProcess(222);
    return EXCEPTION_EXECUTE_HANDLER;
}

static HRESULT WINAPI query(IDataObject *object, REFIID iid, void **result)
{
    *result = NULL;
    if (!IsEqualIID(iid, &IID_IUnknown) && !IsEqualIID(iid, &IID_IDataObject)) return E_NOINTERFACE;
    *result = object;
    return S_OK;
}

static ULONG WINAPI add_ref(IDataObject *object) { (void)object; return 2; }
static ULONG WINAPI release(IDataObject *object) { (void)object; return 1; }

static HRESULT WINAPI get_data(IDataObject *object, FORMATETC *format, STGMEDIUM *medium)
{
    const WCHAR text[] = L"OLE fixture";
    void *buffer;

    (void)object;
    memset(medium, 0, sizeof(*medium));
    if (format->cfFormat == CF_BITMAP && (format->tymed & TYMED_GDI))
    {
        medium->tymed = TYMED_GDI;
        medium->hBitmap = CreateBitmap(3, 2, 1, 32, pixels);
        return medium->hBitmap ? S_OK : E_FAIL;
    }
    if (format->cfFormat != CF_UNICODETEXT || !(format->tymed & TYMED_HGLOBAL)) return DV_E_TYMED;
    medium->tymed = TYMED_HGLOBAL;
    medium->hGlobal = GlobalAlloc(GMEM_MOVEABLE, sizeof(text));
    if (!medium->hGlobal) return E_OUTOFMEMORY;
    buffer = GlobalLock(medium->hGlobal);
    memcpy(buffer, text, sizeof(text));
    GlobalUnlock(medium->hGlobal);
    return S_OK;
}

static HRESULT WINAPI get_here(IDataObject *object, FORMATETC *format, STGMEDIUM *medium)
{
    (void)object; (void)format; (void)medium;
    return E_NOTIMPL;
}

static HRESULT WINAPI query_data(IDataObject *object, FORMATETC *format)
{
    (void)object;
    return format->cfFormat == CF_BITMAP || format->cfFormat == CF_UNICODETEXT ? S_OK : DV_E_FORMATETC;
}

static HRESULT WINAPI canonical(IDataObject *object, FORMATETC *input, FORMATETC *output)
{
    (void)object; (void)input;
    output->ptd = NULL;
    return E_NOTIMPL;
}

static HRESULT WINAPI set_data(IDataObject *object, FORMATETC *format, STGMEDIUM *medium, BOOL owned)
{
    (void)object; (void)format; (void)medium; (void)owned;
    return E_NOTIMPL;
}

static HRESULT WINAPI enumerate(IDataObject *object, DWORD direction, IEnumFORMATETC **result)
{
    FORMATETC formats[] = {
        {CF_UNICODETEXT, NULL, DVASPECT_CONTENT, -1, TYMED_HGLOBAL},
        {CF_BITMAP, NULL, DVASPECT_CONTENT, -1, TYMED_GDI | TYMED_ENHMF},
        {CF_BITMAP, NULL, DVASPECT_THUMBNAIL, -1, TYMED_GDI}
    };
    static DWORD device_data[4] = {sizeof(device_data), 0, 0, 0};
    DVTARGETDEVICE *device = (DVTARGETDEVICE *)device_data;

    (void)object;
    device->tdDriverNameOffset = FIELD_OFFSET(DVTARGETDEVICE, tdData);
    memcpy(device->tdData, L"X", 2 * sizeof(WCHAR));
    if (target_device) formats[1].ptd = formats[2].ptd = device;
    if (direction != DATADIR_GET) return E_NOTIMPL;
    return SHCreateStdEnumFmtEtc(target_device ? 3 : 2, formats, result);
}

static HRESULT WINAPI advise(IDataObject *object, FORMATETC *format, DWORD flags,
                             IAdviseSink *sink, DWORD *connection)
{
    (void)object; (void)format; (void)flags; (void)sink; (void)connection;
    return OLE_E_ADVISENOTSUPPORTED;
}

static HRESULT WINAPI unadvise(IDataObject *object, DWORD connection)
{
    (void)object; (void)connection;
    return OLE_E_ADVISENOTSUPPORTED;
}

static HRESULT WINAPI enum_advise(IDataObject *object, IEnumSTATDATA **result)
{
    (void)object;
    *result = NULL;
    return OLE_E_ADVISENOTSUPPORTED;
}

static IDataObjectVtbl methods = {
    query, add_ref, release, get_data, get_here, query_data, canonical, set_data, enumerate,
    advise, unadvise, enum_advise
};
static IDataObject object = {&methods};

static int check_bitmap(HBITMAP bitmap)
{
    BITMAP description;
    DWORD actual[ARRAYSIZE(pixels)] = {0};
    BOOL passed = bitmap && GetObjectW(bitmap, sizeof(description), &description) &&
        description.bmWidth == 3 && description.bmHeight == 2 &&
        GetBitmapBits(bitmap, sizeof(actual), actual) == sizeof(actual) &&
        !memcmp(actual, pixels, sizeof(actual));

    printf("bitmap=%p passed=%d\n", bitmap, passed);
    return passed ? 0 : 1;
}

static int check_formats(IDataObject *data, BOOL devices)
{
    IEnumFORMATETC *enumerator;
    FORMATETC format;
    ULONG fetched, count = 0;
    HRESULT hr = IDataObject_EnumFormatEtc(data, DATADIR_GET, &enumerator);
    BOOL passed = TRUE;

    if (FAILED(hr)) return 6;
    while ((hr = IEnumFORMATETC_Next(enumerator, 1, &format, &fetched)) == S_OK)
    {
        DWORD aspect = count == 2 ? DVASPECT_THUMBNAIL : DVASPECT_CONTENT;
        DWORD medium = count == 0 ? TYMED_HGLOBAL : count == 1 ? TYMED_GDI | TYMED_ENHMF : TYMED_GDI;
        CLIPFORMAT type = count == 0 ? CF_UNICODETEXT : CF_BITMAP;
        BOOL device = devices && count != 0;

        printf("format=%u aspect=%lu lindex=%ld tymed=%lu device=%d\n",
               format.cfFormat, format.dwAspect, format.lindex, format.tymed, !!format.ptd);
        passed &= count < (devices ? 3 : 2) && format.cfFormat == type && format.dwAspect == aspect &&
            format.lindex == -1 && format.tymed == medium && !!format.ptd == device;
        if (format.ptd)
            passed &= format.ptd->tdSize == 16 && format.ptd->tdDriverNameOffset == 12 &&
                !memcmp(format.ptd->tdData, L"X", 2 * sizeof(WCHAR));
        CoTaskMemFree(format.ptd);
        if (++count > 3) break;
    }
    IEnumFORMATETC_Release(enumerator);
    return passed && hr == S_FALSE && count == (devices ? 3 : 2) ? 0 : 7;
}

int main(int argc, char **argv)
{
    IDataObject *data = NULL;
    HRESULT hr;
    int result;

    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
    SetUnhandledExceptionFilter(exception_filter);
    if (argc < 3 || FAILED(OleInitialize(NULL))) return 2;
    if (!strcmp(argv[1], "write"))
    {
        MSG message;
        DWORD deadline = GetTickCount() + 30000;

        target_device = argc > 3 && !strcmp(argv[3], "target");
        hr = OleSetClipboard(&object);
        if (SUCCEEDED(hr) && argc > 3 && !strcmp(argv[3], "flush")) hr = OleFlushClipboard();
        if (FAILED(hr)) return 3;
        puts("ready");
        fflush(stdout);
        while (GetFileAttributesA(argv[2]) == INVALID_FILE_ATTRIBUTES && GetTickCount() < deadline)
        {
            while (PeekMessageW(&message, NULL, 0, 0, PM_REMOVE))
            {
                TranslateMessage(&message);
                DispatchMessageW(&message);
            }
            Sleep(5);
        }
        OleSetClipboard(NULL);
        result = 0;
    }
    else if (!strcmp(argv[1], "raw"))
    {
        if (!OpenClipboard(NULL)) return 4;
        result = check_bitmap(GetClipboardData(CF_BITMAP));
        CloseClipboard();
    }
    else
    {
        if (FAILED(OleGetClipboard(&data))) return 5;
        if (!strcmp(argv[1], "enum")) result = check_formats(data, !strcmp(argv[2], "target"));
        else
        {
            FORMATETC format = {CF_BITMAP, NULL, DVASPECT_CONTENT, -1, TYMED_GDI | TYMED_ENHMF};
            STGMEDIUM medium = {0};

            hr = IDataObject_GetData(data, &format, &medium);
            result = FAILED(hr) || medium.tymed != TYMED_GDI ? 8 : check_bitmap(medium.hBitmap);
            if (SUCCEEDED(hr)) ReleaseStgMedium(&medium);
        }
        IDataObject_Release(data);
    }
    OleUninitialize();
    return result;
}
