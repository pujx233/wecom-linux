typedef unsigned long DWORD;
typedef unsigned short WCHAR;
typedef int BOOL;
typedef void *HANDLE;
#define API __declspec(dllimport) __stdcall

typedef struct {
    long height, width, escapement, orientation, weight;
    unsigned char italic, underline, strikeout, charset;
    unsigned char outprecision, clipprecision, quality, pitch;
    WCHAR face[32];
} LOGFONTW;
typedef struct {
    unsigned size;
    int border, scrollw, scrollh, captionw, captionh;
    LOGFONTW caption;
    int smcaptionw, smcaptionh;
    LOGFONTW smcaption;
    int menuw, menuh;
    LOGFONTW menu, status, message;
    int padded;
} METRICS;

API BOOL SystemParametersInfoW(unsigned, unsigned, void *, unsigned);
API HANDLE GetStdHandle(DWORD);
API BOOL WriteFile(HANDLE, const void *, DWORD, DWORD *, void *);
API void ExitProcess(DWORD);

void mainCRTStartup(void)
{
    static METRICS metrics;
    static const WCHAR face[] = L"Source Han Sans CN";
    static const char success[] = "StatusFont set to Source Han Sans CN. Restart WeCom to apply.\n";
    static const char failure[] = "Unable to set StatusFont.\n";
    DWORD written;
    unsigned i;
    BOOL ok;

    metrics.size = sizeof(metrics);
    ok = SystemParametersInfoW(0x29, sizeof(metrics), &metrics, 0);
    if (ok) {
        /* Change only the status font family and charset. */
        for (i = 0; i < 32; i++) metrics.status.face[i] = 0;
        for (i = 0; face[i]; i++) metrics.status.face[i] = face[i];
        metrics.status.charset = 1;
        ok = SystemParametersInfoW(0x2a, sizeof(metrics), &metrics, 3);
    }
    WriteFile(GetStdHandle(ok ? (DWORD)-11 : (DWORD)-12),
              ok ? success : failure,
              ok ? sizeof(success) - 1 : sizeof(failure) - 1, &written, 0);
    ExitProcess(ok ? 0 : 1);
}
