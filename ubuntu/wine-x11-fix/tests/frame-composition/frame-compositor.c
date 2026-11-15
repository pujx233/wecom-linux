/* Run the extracted production compositor against real X11 resources. */
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/Xatom.h>
#include <X11/extensions/Xcomposite.h>
#include <X11/extensions/Xrender.h>
#include <X11/extensions/shape.h>
#include <X11/extensions/Xdamage.h>
#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef int BOOL;
typedef struct { int cx, cy; } SIZE;
#define TRUE 1
#define FALSE 0
#define BOOL X11_BOOL
#include <X11/Xproto.h>
#undef BOOL
#define SONAME_LIBXCOMPOSITE "libXcomposite.so.1"
#define HAVE_LIBXSHAPE 1
#define HAVE_X11_EXTENSIONS_XRENDER_H 1
#define WXR_FORMAT_A8R8G8B8 0
#define TRACE(...) do {} while (0)
#define TRACE_ON(channel) 0
#define ERR(...) do {} while (0)
#define x11drv_atom(name) opacity_atom
#define pXRenderFreePicture XRenderFreePicture
#define pXRenderCreatePicture XRenderCreatePicture
#define pXRenderFindVisualFormat XRenderFindVisualFormat
#define pXRenderChangePicture XRenderChangePicture
#define pXRenderFillRectangle XRenderFillRectangle
#define pXRenderSetPictureClipRectangles XRenderSetPictureClipRectangles
#define pXRenderComposite XRenderComposite
#define pXCompositeNameWindowPixmap checked_name

typedef int (*x11drv_error_callback)(Display *, XErrorEvent *, void *);
static Display *gdi_display, *clipboard_display, *other_display, *err_callback_display;
static Window root_window, victim;
static Atom opacity_atom;
static XRenderPictFormat *pict_formats[1];
static pthread_mutex_t xrender_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t error_mutex = PTHREAD_MUTEX_INITIALIZER;
static x11drv_error_callback err_callback;
static void *err_callback_arg;
static int err_callback_result, xrender_error_base;
static unsigned long err_serial;
static int (*old_error_handler)(Display *, XErrorEvent *);
static const char *mode;
static int armed, exercised;

static void change_victim(void)
{
    armed = 0;
    exercised = 1;
    if (!strcmp(mode, "unmap-before-name")) XUnmapWindow(other_display, victim);
    else XDestroyWindow(other_display, victim);
    XSync(other_display, False);
}

static int checked_attributes(Display *display, Window window, XWindowAttributes *attributes)
{
    int result = XGetWindowAttributes(display, window, attributes);
    if (result && window == victim && armed &&
        (!strcmp(mode, "destroy-before-name") || !strcmp(mode, "unmap-before-name"))) change_victim();
    return result;
}

static Pixmap checked_name(Display *display, Window window)
{
    Pixmap result = XCompositeNameWindowPixmap(display, window);
    if (window == victim && armed && !strcmp(mode, "destroy-after-name"))
    {
        XSync(display, False);
        change_victim();
    }
    return result;
}

typedef unsigned long HWND;
struct x11drv_win_data { Display *display; XID frame_damage; };
static struct x11drv_win_data window_data;
static atomic_int composition_queued;
static pthread_mutex_t condition_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t condition = PTHREAD_COND_INITIALIZER;
static int notify_started, notify_returned;
static XEvent first_damage;
static typeof(XDamageSubtract) *pXDamageSubtract = XDamageSubtract;

static struct x11drv_win_data *get_win_data(HWND hwnd) { return &window_data; }
static void release_win_data(struct x11drv_win_data *data) {}
static void composite_owned_frame(HWND hwnd, BOOL configure) { atomic_store(&composition_queued, 1); }

#define XGetWindowAttributes checked_attributes
#include "frame-production.h"
#undef XGetWindowAttributes

static unsigned long pixel(Window window, int left, int top)
{
    Pixmap pixmap = XCompositeNameWindowPixmap(gdi_display, window);
    XImage *image = XGetImage(gdi_display, pixmap, left, top, 1, 1, AllPlanes, ZPixmap);
    assert(image);
    unsigned long result = XGetPixel(image, 0, 0) & 0xffffff;
    XDestroyImage(image);
    XFreePixmap(gdi_display, pixmap);
    return result;
}

static int presentation(Window frame, struct frame_compositor **state)
{
    SIZE size = {800, 600};
    XGCValues values = {.subwindow_mode = IncludeInferiors};
    GC gc = XCreateGC(gdi_display, frame, GCSubwindowMode, &values);
    XResizeWindow(gdi_display, victim, size.cx, size.cy);
    XSetForeground(gdi_display, gc, 0x0000ff);
    XFillRectangle(gdi_display, victim, gc, 0, 0, size.cx, size.cy);
    assert(X11DRV_CompositeFrame(frame, state, &size));
    XResizeWindow(gdi_display, frame, size.cx, size.cy);
    XSync(gdi_display, False);
    unsigned long before[2] = {pixel(frame, 30, 30), pixel(frame, 700, 500)};
#ifdef HAVE_FRAME_PRESENT
    X11DRV_PresentFrame(frame, *state, &size);
#endif
    XSync(gdi_display, False);
    unsigned long after[2] = {pixel(frame, 30, 30), pixel(frame, 700, 500)};
    int passed = after[0] == 0x0000ff && after[1] == 0x0000ff;
#ifdef HAVE_FRAME_PRESENT
    XSetForeground(gdi_display, gc, 0x444444);
    XFillRectangle(gdi_display, frame, gc, 0, 0, size.cx, size.cy);
    X11DRV_PresentFrame(frame, *state, &size);  /* A move must not replay an old buffer. */
    passed &= pixel(frame, 30, 30) == 0x444444;
    X11DRV_PresentFrame(frame, *state, NULL);  /* Expose must replay it even at the same size. */
    passed &= pixel(frame, 30, 30) == 0x0000ff;
#endif
    printf("{\"before\":[%lu,%lu],\"after\":[%lu,%lu],\"passed\":%s}\n",
           before[0], before[1], after[0], after[1], passed ? "true" : "false");
    XFreeGC(gdi_display, gc);
    return passed;
}

static void *notify_damage(void *unused)
{
    pthread_mutex_lock(&condition_mutex);
    notify_started = 1;
    pthread_cond_broadcast(&condition);
    pthread_mutex_unlock(&condition_mutex);
    assert(frame_damage_notify(1, &first_damage));
    pthread_mutex_lock(&condition_mutex);
    notify_returned = 1;
    pthread_cond_broadcast(&condition);
    pthread_mutex_unlock(&condition_mutex);
    return NULL;
}

static int take_damage(Display *display, int base)
{
    int count = 0;
    XEvent event;
    while (XPending(display))
    {
        XNextEvent(display, &event);
        if (event.type != base) continue;
        first_damage = event;
        count++;
    }
    return count;
}

static void fill_body(GC gc, unsigned long color)
{
    XSetForeground(gdi_display, gc, color);
    XFillRectangle(gdi_display, victim, gc, 0, 0, 480, 330);
    XSync(gdi_display, False);
}

static int damage_order(Window frame, struct frame_compositor **state, BOOL same_connection)
{
    Display *listener = same_connection ? gdi_display : other_display;
    int base, error;
    assert(XDamageQueryExtension(listener, &base, &error));
    window_data.display = listener;
    window_data.frame_damage = XDamageCreate(listener, victim, XDamageReportNonEmpty);
    XSync(listener, False);
    take_damage(listener, base);
    XDamageSubtract(listener, window_data.frame_damage, None, None);
    XSync(listener, False);
    GC gc = XCreateGC(gdi_display, victim, 0, NULL);
    fill_body(gc, 0x00ff00);
    XSync(listener, False);
    assert(take_damage(listener, base) == 1);
    /* Hold back the listener connection while allowing the compositor connection to progress. */
    XGrabServer(gdi_display);
    XSync(gdi_display, False);
    pthread_t thread;
    assert(!pthread_create(&thread, NULL, notify_damage, NULL));
    pthread_mutex_lock(&condition_mutex);
    while (!notify_started) pthread_cond_wait(&condition, &condition_mutex);
    struct timespec deadline;
    clock_gettime(CLOCK_REALTIME, &deadline);
    deadline.tv_nsec += 100000000;
    if (deadline.tv_nsec >= 1000000000) { deadline.tv_sec++; deadline.tv_nsec -= 1000000000; }
    while (!notify_returned && !pthread_cond_timedwait(&condition, &condition_mutex, &deadline)) {}
    int queued_before_clear = atomic_load(&composition_queued);
    pthread_mutex_unlock(&condition_mutex);
    if (queued_before_clear)
    {
        assert(X11DRV_CompositeFrame(frame, state, NULL));
        fill_body(gc, 0x0000ff);
    }
    XUngrabServer(gdi_display);
    XSync(gdi_display, False);
    assert(!pthread_join(thread, NULL));
    assert(atomic_load(&composition_queued));
    if (!queued_before_clear)
    {
        assert(X11DRV_CompositeFrame(frame, state, NULL));
        fill_body(gc, 0x0000ff);
    }
    XSync(listener, False);
    int followup = take_damage(listener, base);
    if (followup)
    {
        assert(frame_damage_notify(1, &first_damage));
        assert(X11DRV_CompositeFrame(frame, state, NULL));
    }
    XSync(gdi_display, False);
    unsigned long body = pixel(victim, 30, 30), shown = pixel(frame, 30, 30);
    int passed = body == 0x0000ff && shown == body;
    printf("{\"same_connection\":%s,\"queued_before_clear\":%s,\"second_damage_events\":%d,"
           "\"body\":%lu,\"frame\":%lu,\"passed\":%s}\n",
           same_connection ? "true" : "false", queued_before_clear ? "true" : "false", followup,
           body, shown, passed ? "true" : "false");
    XDamageDestroy(listener, window_data.frame_damage);
    XSync(listener, False);
    XFreeGC(gdi_display, gc);
    return passed;
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    mode = argv[1];
    XInitThreads();
    gdi_display = XOpenDisplay(NULL);
    other_display = XOpenDisplay(NULL);
    assert(gdi_display && other_display);
    root_window = DefaultRootWindow(gdi_display);
    opacity_atom = XInternAtom(gdi_display, "_NET_WM_WINDOW_OPACITY", False);
    pict_formats[0] = XRenderFindStandardFormat(gdi_display, PictStandardARGB32);
    old_error_handler = XSetErrorHandler(error_handler);
    XRenderQueryExtension(gdi_display, &(int){0}, &xrender_error_base);
    Window frame = XCreateSimpleWindow(gdi_display, root_window, 30, 30, 500, 350, 0, 0, 0);
    if (!strncmp(mode, "damage-", 7)) XCompositeRedirectWindow(gdi_display, frame, CompositeRedirectManual);
    XSetWindowAttributes attributes = {.override_redirect = True};
    XChangeWindowAttributes(gdi_display, frame, CWOverrideRedirect, &attributes);
    XCompositeRedirectSubwindows(gdi_display, frame, CompositeRedirectManual);
    victim = XCreateSimpleWindow(gdi_display, frame, 0, 0, 480, 330, 0, 0, 0x00ff00);
    XMapWindow(gdi_display, victim);
    XMapWindow(gdi_display, frame);
    XSync(gdi_display, False);
    struct frame_compositor *state = NULL;
    assert(X11DRV_CompositeFrame(frame, &state, NULL));
    XSync(gdi_display, False);
    int passed = 1;
    if (!strcmp(mode, "presentation")) passed = presentation(frame, &state);
    else if (!strncmp(mode, "damage-", 7)) passed = damage_order(frame, &state, !strcmp(mode, "damage-same"));
    else
    {
        if (!strcmp(mode, "input-only") || !strcmp(mode, "unexpected-error"))
        {
            Window input = XCreateWindow(gdi_display, frame, 0, 0, 400, 300, 0, 0,
                                         InputOnly, CopyFromParent, 0, NULL);
            XMapWindow(gdi_display, input);
            XSync(gdi_display, False);
            exercised = 1;
            if (!strcmp(mode, "unexpected-error"))
            {
                XCompositeNameWindowPixmap(gdi_display, input);
                XSync(gdi_display, False);  /* Unrelated BadMatch must still reach Xlib's fatal handler. */
                return 2;
            }
        }
        armed = 1;
        assert(X11DRV_CompositeFrame(frame, &state, NULL));
        XSync(gdi_display, False);
        Window healthy = XCreateSimpleWindow(gdi_display, frame, 0, 0, 480, 330, 0, 0, 0x0000ff);
        XMapRaised(gdi_display, healthy);
        XSync(gdi_display, False);
        assert(X11DRV_CompositeFrame(frame, &state, NULL));
        XSync(gdi_display, False);
        unsigned long color = pixel(frame, 30, 30);
        passed = exercised && color == 0x0000ff;
        printf("{\"race_exercised\":%s,\"healthy_pixel\":%lu,\"passed\":%s}\n",
               exercised ? "true" : "false", color, passed ? "true" : "false");
    }
    X11DRV_DestroyFrameCompositor(&state);
    XDestroyWindow(gdi_display, frame);
    XSync(gdi_display, False);
    XCloseDisplay(other_display);
    XCloseDisplay(gdi_display);
    return passed ? 0 : 1;
}
