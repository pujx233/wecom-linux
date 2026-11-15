#define _GNU_SOURCE
#include <X11/Xlib.h>
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static _Thread_local Display *probe_display;
static _Thread_local XEvent probe_event;
static _Thread_local int probe_armed;

char *XmbResetIC(XIC ic)
{
    static char *(*original)(XIC);
    if (!original) original = dlsym(RTLD_NEXT, "XmbResetIC");
    char *ret = original(ic);
    printf("{\"event\":\"native-reset\",\"native_pid\":%ld}\n", (long)getpid());
    fflush(stdout);
    return ret;
}

int XFlush(Display *display)
{
    static int (*original)(Display *);
    if (!original) original = dlsym(RTLD_NEXT, "XFlush");
    int ret = original(display);
    if (probe_armed && display == probe_display)
    {
        probe_armed = 0;
        XPutBackEvent(display, &probe_event);
        fprintf(stderr, "fixture-driver: buffered operation 10\n");
    }
    return ret;
}

/* Inject on the native driver thread, as XIM does, including in WoW64 apps.
 * The PE NtUserImeDriverCall thunk intentionally cannot accept driver strings. */
Bool XFilterEvent(XEvent *event, Window window)
{
    static Bool (*original)(XEvent *, Window);
    const char *guard = getenv("WECOM_IME_FIXTURE"), *display = getenv("DISPLAY");
    if (!original) original = dlsym(RTLD_NEXT, "XFilterEvent");
    if (guard && !strcmp(guard, "1") && display && strcmp(display, ":0") && event->type == KeyPress &&
        event->xkey.send_event && event->xkey.keycode == 255)
    {
        typedef intptr_t (*message_call)(void *, unsigned, uintptr_t, intptr_t, void *, unsigned, int);
        void *module = dlopen(getenv("WECOM_WIN32U_PATH"), RTLD_NOW | RTLD_NOLOAD);
        message_call call = module ? dlsym(module, "NtUserMessageCall") : NULL;
        uint16_t comp[] = {97, 0xd83d, 0xde42, 0}, result[] = {0x6d4b, 0x8bd5, 0};
        uint16_t *strings[2] = {comp, NULL};
        int operation = event->xkey.time;
        fprintf(stderr, "fixture-driver: operation %d hwnd %lx\n", operation, event->xkey.root);
        if (operation == 2) { strings[0] = NULL; strings[1] = result; }
        else if (operation == 3) comp[0] = 0;
        else if (operation == 4) strings[0] = NULL;
        printf("{\"event\":\"driver\",\"operation\":%d}\n", operation);
        fflush(stdout);
        if (operation == 9)
        {
            probe_display = event->xkey.display;
            probe_event = *event;
            probe_event.xkey.time = 10;
            probe_armed = 1;
        }
        /* WINE_IME_POST_UPDATE=1, NtUserImeDriverCall=0x0305. */
        if (call && operation <= 4) call((void *)(uintptr_t)(uint32_t)event->xkey.root, 1, 1,
                                         (intptr_t)strings, NULL, 0x0305, 0);
        if (module) dlclose(module);
        return True;
    }
    return original(event, window);
}
