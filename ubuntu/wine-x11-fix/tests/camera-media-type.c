#define COBJMACROS
#include <windows.h>
#include <dshow.h>
#include <stdio.h>

static unsigned int failures, formats;

static void check_type(AM_MEDIA_TYPE *type, const char *operation)
{
    if (type->pUnk || type->cbFormat != sizeof(VIDEOINFOHEADER) || !type->pbFormat ||
        !IsEqualGUID(&type->majortype, &MEDIATYPE_Video) || !IsEqualGUID(&type->formattype, &FORMAT_VideoInfo))
    {
        printf("FAIL %s pUnk=%p cbFormat=%lu format=%p\n", operation,
               type->pUnk, type->cbFormat, type->pbFormat);
        ++failures;
    }
    else ++formats;
    /* Capture formats have no IUnknown. Do not dereference a failed output. */
    CoTaskMemFree(type->pbFormat);
    CoTaskMemFree(type);
}

static void check_pin(IPin *pin)
{
    IAMStreamConfig *config;
    IEnumMediaTypes *types;
    AM_MEDIA_TYPE *type;
    HRESULT hr;
    int count, size, i;

    if (SUCCEEDED(IPin_QueryInterface(pin, &IID_IAMStreamConfig, (void **)&config)))
    {
        hr = IAMStreamConfig_GetFormat(config, &type);
        if (SUCCEEDED(hr)) check_type(type, "GetFormat");
        else { printf("FAIL GetFormat %#lx\n", hr); ++failures; }
        hr = IAMStreamConfig_GetNumberOfCapabilities(config, &count, &size);
        if (FAILED(hr) || size != sizeof(VIDEO_STREAM_CONFIG_CAPS) || count <= 0)
        {
            printf("FAIL capabilities %#lx\n", hr);
            ++failures;
        }
        else for (i = 0; i < count; ++i)
        {
            VIDEO_STREAM_CONFIG_CAPS caps;
            hr = IAMStreamConfig_GetStreamCaps(config, i, &type, (BYTE *)&caps);
            if (SUCCEEDED(hr)) check_type(type, "GetStreamCaps");
            else { printf("FAIL GetStreamCaps %#lx\n", hr); ++failures; }
        }
        IAMStreamConfig_Release(config);
    }
    hr = IPin_EnumMediaTypes(pin, &types);
    if (FAILED(hr)) { printf("FAIL EnumMediaTypes %#lx\n", hr); ++failures; return; }
    while (IEnumMediaTypes_Next(types, 1, &type, NULL) == S_OK) check_type(type, "EnumMediaTypes");
    IEnumMediaTypes_Release(types);
}

int main(void)
{
    ICreateDevEnum *devices;
    IEnumMoniker *monikers;
    IMoniker *moniker;
    unsigned int opened = 0, round;
    HRESULT hr;

    setvbuf(stdout, NULL, _IONBF, 0);
    CoInitializeEx(NULL, COINIT_MULTITHREADED);
    hr = CoCreateInstance(&CLSID_SystemDeviceEnum, NULL, CLSCTX_INPROC_SERVER,
                          &IID_ICreateDevEnum, (void **)&devices);
    if (FAILED(hr)) { printf("FAIL device enumerator %#lx\n", hr); return 1; }
    for (round = 0; round < 3; ++round)
    {
        hr = ICreateDevEnum_CreateClassEnumerator(devices, &CLSID_VideoInputDeviceCategory, &monikers, 0);
        if (hr != S_OK) { printf("NO_DEVICES %#lx\n", hr); break; }
        while (IEnumMoniker_Next(monikers, 1, &moniker, NULL) == S_OK)
        {
            IBaseFilter *filter;
            IEnumPins *pins;
            IPin *pin;

            hr = IMoniker_BindToObject(moniker, NULL, NULL, &IID_IBaseFilter, (void **)&filter);
            IMoniker_Release(moniker);
            if (FAILED(hr)) { printf("device unavailable %#lx\n", hr); continue; }
            ++opened;
            if (SUCCEEDED(IBaseFilter_EnumPins(filter, &pins)))
            {
                while (IEnumPins_Next(pins, 1, &pin, NULL) == S_OK)
                {
                    PIN_DIRECTION direction;
                    IPin_QueryDirection(pin, &direction);
                    if (direction == PINDIR_OUTPUT) check_pin(pin);
                    IPin_Release(pin);
                }
                IEnumPins_Release(pins);
            }
            else ++failures;
            IBaseFilter_Release(filter);
        }
        IEnumMoniker_Release(monikers);
    }
    ICreateDevEnum_Release(devices);
    CoUninitialize();
    printf("RESULT bits=%u opened=%u formats=%u failures=%u\n", (unsigned int)(8 * sizeof(void *)),
           opened, formats, failures);
    return failures || !opened || !formats;
}
