#define _GNU_SOURCE
#include <X11/Xlib.h>
#include <X11/Xresource.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/syscall.h>
#include <unistd.h>

static void record(const char *event, Display *display)
{
    const char *path = getenv("WECOM_XIM_OWNER_LOG");
    char buffer[180];
    int fd, length;
    if (!path || (fd = open(path, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0600)) < 0) return;
    length = snprintf(buffer, sizeof(buffer), "{\"event\":\"%s\",\"pid\":%d,\"tid\":%ld,\"display\":\"%p\"}\n",
                      event, getpid(), syscall(SYS_gettid), (void *)display);
    if (length > 0 && length < (int)sizeof(buffer) && write(fd, buffer, length) != length)
    {
        perror("XIM display ownership trace");
        _exit(97);
    }
    close(fd);
}

Display *XOpenDisplay(const char *name)
{
    Display *(*real)(const char *) = dlsym(RTLD_NEXT, "XOpenDisplay");
    Display *display = real(name);
    if (display) record("display", display);
    return display;
}

XIM XOpenIM(Display *display, XrmDatabase database, char *name, char *class)
{
    XIM (*real)(Display *, XrmDatabase, char *, char *) = dlsym(RTLD_NEXT, "XOpenIM");
    record("open-im", display);
    return real(display, database, name, class);
}
