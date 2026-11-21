#define _GNU_SOURCE
#include <X11/Xlib.h>
#include <dlfcn.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Hold only the fixture's private WM after its first, single-output allocation.
 * The client can then consume that real reply before the WM processes its span request. */
Status XSendEvent(Display *display, Window window, Bool propagate, long mask, XEvent *event)
{
    static Status (*send_event)(Display *, Window, Bool, long, XEvent *);
    static int held;

    if (!send_event) send_event = dlsym(RTLD_NEXT, "XSendEvent");
    if (!held && event->type == ClientMessage && event->xclient.data.l[2] != event->xclient.data.l[3])
    {
        char *name = XGetAtomName(display, event->xclient.message_type);
        if (name && !strcmp(name, "_NET_WM_FULLSCREEN_MONITORS"))
        {
            XWindowAttributes root, actual;
            const char *value = getenv("WECOM_QA_WM_PID");
            int ready = 0, pid = value ? atoi(value) : 0;

            held = 1;
            XSync(display, False);
            XGetWindowAttributes(display, DefaultRootWindow(display), &root);
            for (int i = 0; i < 400; i++)
            {
                XSync(display, False);
                if (XGetWindowAttributes(display, event->xclient.window, &actual) &&
                    actual.map_state == IsViewable &&
                    (actual.width != root.width || actual.height != root.height))
                {
                    ready = 1;
                    break;
                }
                usleep(5000);
            }
            if (!ready || pid <= 1 || kill(pid, SIGSTOP))
            {
                fputs("Could not pause the private fullscreen fixture WM.\n", stderr);
                _exit(120);
            }
            fprintf(stderr, "Paused private WM %d at native size %dx%d, before span %dx%d.\n",
                    pid, actual.width, actual.height, root.width, root.height);
        }
        if (name) XFree(name);
    }
    return send_event(display, window, propagate, mask, event);
}
