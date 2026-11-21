/* Exercise the actual private Xlib protocol callbacks through a real isolated IBus server. */
#include <X11/Xlibint.h>
#include "Xlcint.h"
#include "Ximint.h"
#include <dlfcn.h>
#include <locale.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

#define CHECK(expr) do { if (!(expr)) { fprintf(stderr, "FAIL line %d\n", __LINE__); exit(1); } ++checks; } while (0)
static unsigned int checks;
static int sequence[8], count, depth, max_depth, action;
static Window window;
static XIM input_method;

static void dispatch(XIC context, unsigned char opcode)
{
    Xic ic = (Xic)context;
    CARD16 packet[4] = {opcode, 1, ((Xim)ic->core.im)->private.proto.imid, ic->private.proto.icid};
    CHECK(_XimCbDispatch((Xim)ic->core.im, sizeof(packet), (XPointer)packet, (XPointer)ic->core.im));
}

static int callback(XIC context, XPointer data, XPointer call_data)
{
    int marker = (int)(intptr_t)data;
    (void)call_data;
    CHECK(count < 8);
    sequence[count] = marker == 1 && count > 0 ? 4 : marker;
    ++count;
    ++depth;
    if (depth > max_depth) max_depth = depth;
    if (marker == 1 && count == 1)
    {
        if (action == 1)
        {
            dispatch(context, 70);
            CHECK(!XSetICValues(context, XNFocusWindow, window, NULL));
        }
        else if (action == 2) XDestroyIC(context);
        else if (action == 3) XCloseIM(input_method);
    }
    --depth;
    return 0;
}

static XIC create_context(void)
{
    XIC context = XCreateIC(input_method, XNInputStyle, XIMPreeditNothing | XIMStatusNothing,
                            XNClientWindow, window, XNFocusWindow, window, NULL);
    Xic ic = (Xic)context;
    CHECK(context);
    ic->core.geometry_callback.callback = callback;
    ic->core.geometry_callback.client_data = (XPointer)(intptr_t)1;
    ic->core.status_attr.start_callback.callback = callback;
    ic->core.status_attr.start_callback.client_data = (XPointer)(intptr_t)2;
    ic->core.status_attr.done_callback.callback = callback;
    ic->core.status_attr.done_callback.client_data = (XPointer)(intptr_t)3;
    return context;
}

static XIM open_method(Display *display)
{
    XIM method = NULL;
    for (int i = 0; i < 200 && !method; ++i)
    {
        XSetLocaleModifiers("@im=ibus");
        method = XOpenIM(display, NULL, NULL, NULL);
        if (!method) usleep(50000);
    }
    CHECK(method);
    return method;
}

int main(void)
{
    Display *display;
    Dl_info loaded;
    setlocale(LC_ALL, "");
    CHECK(dladdr((void *)XOpenIM, &loaded));
    printf("LIBRARY %s\n", loaded.dli_fname);
    display = XOpenDisplay(NULL);
    CHECK(display);
    window = XCreateSimpleWindow(display, DefaultRootWindow(display), 0, 0, 200, 100, 0, 0, 0);
    input_method = open_method(display);
    for (int repeat = 0; repeat < 80; ++repeat)
    {
        for (int operation = 0; operation < 6; ++operation)
        {
            XIC context = create_context();
            Xic ic = (Xic)context;
            count = depth = max_depth = 0;
            action = operation == 3 ? 2 : operation == 4 ? 3 : 1;
            if (operation != 5)
            {
                ic->private.proto.waitCallback = True;
                dispatch(context, 70);
                dispatch(context, 79);
                dispatch(context, 81);
                CHECK(count == 0);
                ic->private.proto.waitCallback = False;
                if (operation == 1)
                {
                    Window focus = None;
                    CHECK(!XGetICValues(context, XNFocusWindow, &focus, NULL));
                }
                else if (operation == 2) XFree(XmbResetIC(context));
                else CHECK(!XSetICValues(context, XNFocusWindow, window, NULL));
            }
            else dispatch(context, 70);
            CHECK(max_depth == 1);
            if (action > 1)
            {
                CHECK(count == 1 && sequence[0] == 1);
                if (action == 3) input_method = open_method(display);
            }
            else
            {
                CHECK(count == (operation == 5 ? 2 : 4) && sequence[0] == 1);
                if (operation == 5) CHECK(sequence[1] == 4);
                else CHECK(sequence[1] == 2 && sequence[2] == 3 && sequence[3] == 4);
                CHECK(!ic->private.proto.pend_cb_que && !ic->private.proto.processing_callbacks);
                XDestroyIC(context);
            }
        }
    }
    XCloseIM(input_method);
    XDestroyWindow(display, window);
    XCloseDisplay(display);
    printf("PASS checks=%u repeats=80 operations=6\n", checks);
    return 0;
}
