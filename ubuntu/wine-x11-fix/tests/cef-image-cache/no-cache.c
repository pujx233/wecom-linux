#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <string.h>
#include <sys/mman.h>

int memfd_create(const char *name, unsigned int flags)
{
    static int (*original)(const char *, unsigned int);

    if (!strcmp(name, "wine-cef-image"))
    {
        errno = ENOMEM;
        return -1;
    }
    if (!original) original = dlsym(RTLD_NEXT, "memfd_create");
    return original(name, flags);
}
