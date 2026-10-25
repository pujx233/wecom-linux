#define _GNU_SOURCE
#include <X11/Xlib.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <iconv.h>
#include <langinfo.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* App-scoped XIM commit bridge, verified on unmodified Arch Wine 11.19.
 * win32u.so exports the Unix ABI, not the Win64 calling convention.
 * Never log the committed text. No clipboard, files, or DLLs are modified. */
typedef void *Hwnd;
typedef struct { uint32_t size, flags; Hwnd active, focus, capture, menu, move, caret;
                 int32_t rect[4]; } GuiInfo;
typedef struct { uint16_t length, capacity; uint16_t *buffer; } UnicodeString;
_Static_assert(sizeof(GuiInfo) == 72, "Requires the x86_64 Wine Unix ABI");
static _Thread_local int (*gui_info)(uint32_t, GuiInfo *);
static _Thread_local Hwnd (*ancestor)(Hwnd, uint32_t);
static _Thread_local Hwnd (*query_window)(Hwnd, int);
static _Thread_local int (*class_name)(Hwnd, int, UnicodeString *);
static _Thread_local Hwnd (*get_prop)(Hwnd, const uint16_t *);
static _Thread_local int (*post_message)(Hwnd, uint32_t, uintptr_t, intptr_t);
static _Thread_local int is_input_host = -1, debug;

static int init_api(void)
{
    if (is_input_host < 0) {
        char cmd[4096] = {0};
        int fd = open("/proc/self/cmdline", O_RDONLY | O_CLOEXEC);
        ssize_t n = fd >= 0 ? read(fd, cmd, sizeof(cmd) - 1) : -1;
        if (fd >= 0) close(fd);
        const char *base = strrchr(cmd, '\\');
        if (!base) base = strrchr(cmd, '/');
        const char *name = base ? base + 1 : cmd;
        is_input_host = n > 0 && (!strcasecmp(name, "WeMail.exe") ||
                                   !strcasecmp(name, "WXWork.exe"));
        const char *flag = getenv("WECOM_IME_DEBUG");
        debug = flag && !strcmp(flag, "1");
    }
    if (!is_input_host) return 0;
    if (gui_info) return 1;
    const char *module = getenv("WECOM_WIN32U_PATH");
    if (!module || !*module) module = "/usr/lib/wine/x86_64-unix/win32u.so";
    void *lib = dlopen(module, RTLD_NOW | RTLD_NOLOAD);
    if (!lib) return 0;
    gui_info = dlsym(lib, "NtUserGetGUIThreadInfo");
    ancestor = dlsym(lib, "NtUserGetAncestor");
    query_window = dlsym(lib, "NtUserQueryWindow");
    class_name = dlsym(lib, "NtUserGetClassName");
    get_prop = dlsym(lib, "NtUserGetProp");
    post_message = dlsym(lib, "NtUserPostMessage");
    if (!gui_info || !ancestor || !query_window || !class_name || !get_prop || !post_message) {
        gui_info = NULL;
        dlclose(lib);
        return 0;
    }
    if (debug) fprintf(stderr, "wecom-ime: bridge ready pid=%ld\n", (long)getpid());
    return 1;
}

static int has_class(Hwnd hwnd, const char *expected)
{
    uint16_t buf[128] = {0};
    UnicodeString str = {0, sizeof(buf), buf};
    int n = class_name(hwnd, 0, &str);
    if (n < 0 || (size_t)n != strlen(expected)) return 0;
    for (int i = 0; i < n; ++i) if (buf[i] != (unsigned char)expected[i]) return 0;
    return 1;
}

static int forward_commit(Window client, const char *text, int bytes)
{
    if (bytes <= 0 || !init_api()) return 0;
    GuiInfo info = {.size = sizeof(info)};
    if (!gui_info(0, &info) || !info.focus) return 0;
    Hwnd root = ancestor(info.focus, 2); /* GA_ROOT */
    Hwnd parent = ancestor(info.focus, 1); /* GA_PARENT */
    if (!has_class(info.focus, "Chrome_WidgetWin_1") ||
        !has_class(parent, "CefBrowserWindow") ||
        query_window(root, 0) == query_window(info.focus, 0)) return 0;
    /* WeMail hosts standalone mail/doc windows; WXWork hosts embedded docs
     * and workbench forms. Match the actual XIM host rather than a Qt class. */
    static const uint16_t whole[] = {'_','_','w','i','n','e','_','x','1','1','_','w','h','o','l','e','_','w','i','n','d','o','w',0};
    if ((uintptr_t)get_prop(root, whole) != client) return 0;

    iconv_t cd = iconv_open("UTF-16LE", nl_langinfo(CODESET));
    if (cd == (iconv_t)-1) return 0;
    size_t in_left = bytes, capacity = (size_t)bytes * 2, out_left = capacity;
    uint16_t *output = malloc(capacity);
    if (!output) { iconv_close(cd); return 0; }
    char *input = (char *)text, *out = (char *)output;
    size_t converted = iconv(cd, &input, &in_left, &out, &out_left);
    iconv_close(cd);
    if (converted == (size_t)-1 || in_left) { free(output); return 0; }
    size_t count = (capacity - out_left) / 2;
    /* Recheck focus immediately before sending, and keep one explicit target
     * throughout the commit. Do not use global SendInput or the clipboard. */
    GuiInfo current = {.size = sizeof(current)};
    if (!gui_info(0, &current) || current.focus != info.focus) { free(output); return 0; }
    size_t sent = 0;
    for (; sent < count; ++sent)
        if (!post_message(info.focus, 0x0102, output[sent], 1)) break; /* WM_CHAR */
    free(output);
    if (debug || sent != count)
        fprintf(stderr, "wecom-ime: forwarded=%zu/%zu hwnd=%p\n", sent, count, info.focus);
    /* After any successful post, do not duplicate an incomplete commit via IMM. */
    return sent > 0;
}

int XmbLookupString(XIC ic, XKeyPressedEvent *event, char *buffer, int size,
                    KeySym *keysym, Status *status)
{
    static _Thread_local int (*original)(XIC, XKeyPressedEvent *, char *, int, KeySym *, Status *);
    if (!original) original = dlsym(RTLD_NEXT, "XmbLookupString");
    if (!original) { if (status) *status = XLookupNone; return 0; }
    int count = original(ic, event, buffer, size, keysym, status);
    if (status && *status == XLookupChars && event->keycode == 0 && count > 0 && count <= size &&
        forward_commit(event->window, buffer, count)) {
        *status = XLookupNone;
        if (keysym) *keysym = NoSymbol;
        return 0;
    }
    return count;
}
