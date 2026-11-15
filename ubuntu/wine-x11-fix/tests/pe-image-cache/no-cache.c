#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int cache_fd = -1;

static int failure_stage(const char *expected)
{
    const char *stage = getenv("WECOM_QA_CACHE_FAILURE_STAGE");
    return !strcmp(stage ? stage : "create", expected);
}

int openat(int dir, const char *path, int flags, ...)
{
    static int (*original)(int, const char *, int, ...);
    mode_t mode = 0;
    if ((flags & O_CREAT) || (flags & O_TMPFILE) == O_TMPFILE)
    {
        va_list args;
        va_start(args, flags);
        mode = va_arg(args, int);
        va_end(args);
    }
    if ((flags & O_TMPFILE) == O_TMPFILE && failure_stage("create"))
    {
        errno = ENOSPC;
        return -1;
    }
    if (!original) original = dlsym(RTLD_NEXT, "openat");
    int result = original(dir, path, flags, mode);
    if ((flags & O_TMPFILE) == O_TMPFILE) cache_fd = result;
    return result;
}

int posix_fallocate(int fd, off_t offset, off_t length)
{
    static int (*original)(int, off_t, off_t);
    if (fd == cache_fd && ((!offset && failure_stage("reserve-header")) ||
                           (offset && failure_stage("reserve-section"))))
    {
        static const char marker[] = "qa-cache: reservation rejected\n";
        ssize_t written = write(STDERR_FILENO, marker, sizeof(marker) - 1);
        (void)written;
        return ENOSPC;  /* posix_fallocate returns an error number, not -1. */
    }
    if (!original) original = dlsym(RTLD_NEXT, "posix_fallocate");
    return original(fd, offset, length);
}
