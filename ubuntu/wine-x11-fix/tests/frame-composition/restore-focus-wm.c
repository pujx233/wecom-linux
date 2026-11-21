#include <X11/Xlib.h>
#include <X11/Xatom.h>
#include <X11/Xutil.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static Atom protocols, take_focus, wm_state, change_state, active;
static Window root, helper, minimized;
static Display *display;

static void state(Window window, long value)
{
    long data[] = {value, None};
    XChangeProperty(display, window, wm_state, wm_state, 32, PropModeReplace, (unsigned char *)data, 2);
}

static void focus(Window window)
{
    XEvent event = {0};
    event.xclient.type = ClientMessage;
    event.xclient.window = window;
    event.xclient.message_type = protocols;
    event.xclient.format = 32;
    event.xclient.data.l[0] = take_focus;
    event.xclient.data.l[1] = CurrentTime;
    XSendEvent(display, window, False, NoEventMask, &event);
    XChangeProperty(display, root, active, XA_WINDOW, 32, PropModeReplace, (unsigned char *)&window, 1);
}

int main(void)
{
    XEvent event;
    Atom supported, check;
    Window manager;

    display = XOpenDisplay(NULL);
    if (!display) return 2;
    root = DefaultRootWindow(display);
    protocols = XInternAtom(display, "WM_PROTOCOLS", False);
    take_focus = XInternAtom(display, "WM_TAKE_FOCUS", False);
    wm_state = XInternAtom(display, "WM_STATE", False);
    change_state = XInternAtom(display, "WM_CHANGE_STATE", False);
    active = XInternAtom(display, "_NET_ACTIVE_WINDOW", False);
    supported = XInternAtom(display, "_NET_SUPPORTED", False);
    check = XInternAtom(display, "_NET_SUPPORTING_WM_CHECK", False);
    manager = XCreateSimpleWindow(display, root, 0, 0, 1, 1, 0, 0, 0);
    XChangeProperty(display, root, supported, XA_ATOM, 32, PropModeReplace, (unsigned char *)&active, 1);
    XChangeProperty(display, root, check, XA_WINDOW, 32, PropModeReplace, (unsigned char *)&manager, 1);
    XChangeProperty(display, manager, check, XA_WINDOW, 32, PropModeReplace, (unsigned char *)&manager, 1);
    XSelectInput(display, root, SubstructureRedirectMask | SubstructureNotifyMask);
    XSync(display, False);
    puts("ready"); fflush(stdout);
    for (;;)
    {
        XNextEvent(display, &event);
        if (event.type == MapRequest)
        {
            Window window = event.xmaprequest.window;
            char *name = NULL;
            if (XFetchName(display, window, &name) && name)
            {
                if (!strcmp(name, "restore focus helper")) helper = window;
                XFree(name);
            }
            XMapWindow(display, window);
            state(window, NormalState);
            focus(window);
        }
        else if (event.type == ConfigureRequest)
        {
            XConfigureRequestEvent *request = &event.xconfigurerequest;
            XWindowChanges changes = {.x = request->x, .y = request->y, .width = request->width,
                .height = request->height, .border_width = request->border_width,
                .sibling = request->above, .stack_mode = request->detail};
            XConfigureWindow(display, request->window, request->value_mask, &changes);
        }
        else if (event.type == ClientMessage && event.xclient.message_type == change_state &&
                 event.xclient.data.l[0] == IconicState)
        {
            minimized = event.xclient.window;
            if (!helper) return 3;
            /* A stale request received while minimizing must not steal focus back. */
            focus(minimized);
            state(minimized, IconicState);
            focus(helper);
        }
        else if (event.type == ClientMessage && event.xclient.message_type == active)
        {
            Window window = event.xclient.window;
            if (window == minimized)
            {
                /* Global-active WMs send TAKE_FOCUS before the restore state acknowledgement. */
                focus(window);
                state(window, NormalState);
                minimized = None;
                puts("restore-focus-before-state"); fflush(stdout);
            }
        }
        XFlush(display);
    }
}
