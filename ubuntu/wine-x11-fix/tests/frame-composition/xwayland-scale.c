#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <stdio.h>

int main(int argc, char **argv)
{
    unsigned int width, height;
    if (argc != 3 || sscanf(argv[1], "%u", &width) != 1 || sscanf(argv[2], "%u", &height) != 1 ||
        width < 32 || height < 32 || width > 4096 || height > 4096) return 2;
    Display *display = XOpenDisplay(NULL);
    if (!display) return 2;
    int screen = DefaultScreen(display);
    Window window = XCreateSimpleWindow(display, RootWindow(display, screen), 150, 120, width, height,
                                        0, 0, 0x15d934);
    Atom motif = XInternAtom(display, "_MOTIF_WM_HINTS", False);
    long hints[] = {2, 0, 0, 0, 0};
    XChangeProperty(display, window, motif, motif, 32, PropModeReplace, (unsigned char *)hints, 5);
    XSizeHints size_hints = {.flags = PPosition | PWinGravity, .x = 150, .y = 120,
                             .win_gravity = NorthWestGravity};
    XSetWMNormalHints(display, window, &size_hints);
    XStoreName(display, window, "X11 scale test");
    XSelectInput(display, window, StructureNotifyMask);
    XMapWindow(display, window);
    XEvent event;
    do XNextEvent(display, &event); while (event.type != MapNotify);
    GC gc = XCreateGC(display, window, 0, NULL);
    setvbuf(stdout, NULL, _IOLBF, 0);
    puts("mapped");

    unsigned long marker;
    while (scanf("%u %u %lx", &width, &height, &marker) == 3)
    {
        if (width < 32 || height < 32 || width > 4096 || height > 4096) return 2;
        unsigned long serial = NextRequest(display);
        XWindowChanges change = {.width = (int)width, .height = (int)height};
        XReconfigureWMWindow(display, window, screen, CWWidth | CWHeight, &change);
        do XNextEvent(display, &event);
        while (event.type != ConfigureNotify || event.xconfigure.serial < serial ||
               event.xconfigure.width != (int)width || event.xconfigure.height != (int)height);
        XWindowAttributes client;
        if (!XGetWindowAttributes(display, window, &client)) return 2;

        XSetForeground(display, gc, 0x15d934);
        XFillRectangle(display, window, gc, 0, 0, width, height);
        XSetForeground(display, gc, marker);
        XFillRectangle(display, window, gc, 4, 24, 12, 16);
        XSetForeground(display, gc, 0xf527bf);
        XFillRectangle(display, window, gc, width - 9, height / 2 - 8, 8, 16);
        XSync(display, False);
        printf("{\"configure\":[%d,%d],\"synthetic\":%d,\"drawable\":[%d,%d]}\n",
               event.xconfigure.width, event.xconfigure.height, !!event.xconfigure.send_event,
               client.width, client.height);
    }
    XFreeGC(display, gc);
    XDestroyWindow(display, window);
    XCloseDisplay(display);
    return 0;
}
