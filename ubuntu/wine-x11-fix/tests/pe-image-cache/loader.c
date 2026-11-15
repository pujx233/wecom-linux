#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static HMODULE module;
static char *base;
static unsigned char *probe;
static wchar_t path[32768];
static DWORD flags;
static DWORD image_size;
static BOOL self;

static int describe(void)
{
    typedef int (__cdecl *int_fn)(void);
    typedef DWORD (__cdecl *owner_fn)(void);
    typedef const char *(__cdecl *pointer_fn)(void);
    IMAGE_NT_HEADERS *nt;
    IMAGE_SECTION_HEADER *section;
    int marker = 0, count = 0;
    unsigned int i;
    int_fn marker_fn, bump_fn;
    owner_fn owner;
    pointer_fn pointer;

    module = self ? GetModuleHandleW(NULL) : LoadLibraryExW(path, NULL, flags);
    if (!module)
    {
        printf("{\"error\":%lu}\n", GetLastError());
        fflush(stdout);
        return 0;
    }
    base = (char *)((uintptr_t)module & ~(uintptr_t)3);
    nt = (IMAGE_NT_HEADERS *)(base + ((IMAGE_DOS_HEADER *)base)->e_lfanew);
    image_size = nt->OptionalHeader.SizeOfImage;
    section = IMAGE_FIRST_SECTION(nt);
    probe = flags ? NULL : (unsigned char *)GetProcAddress(module, "readonly_blob");
    for (i = 0; !probe && i < nt->FileHeader.NumberOfSections; i++)
        if ((section[i].Characteristics & (IMAGE_SCN_MEM_READ | IMAGE_SCN_MEM_WRITE)) == IMAGE_SCN_MEM_READ &&
            section[i].SizeOfRawData) probe = (unsigned char *)base + section[i].VirtualAddress;
    if (!probe) return 0;
    marker_fn = flags ? NULL : (int_fn)(void *)GetProcAddress(module, "image_marker");
    if (marker_fn)
    {
        const char *value;
        bump_fn = (int_fn)(void *)GetProcAddress(module, "image_bump");
        pointer = (pointer_fn)(void *)GetProcAddress(module, "image_pointer");
        owner = (owner_fn)(void *)GetProcAddress(module, "image_owner");
        value = pointer();
        if ((uintptr_t)value < (uintptr_t)base || (uintptr_t)value >= (uintptr_t)base + image_size ||
            strcmp(value, "pe-image-cache") || (!self && owner() != GetCurrentProcessId())) return 0;
        marker = marker_fn();
        count = bump_fn();
    }
    printf("{\"pid\":%lu,\"base\":%llu,\"preferred\":%llu,\"size\":%lu,\"probe_rva\":%llu,"
           "\"probe\":%u,\"marker\":%d,\"count\":%d}\n", GetCurrentProcessId(),
           (unsigned long long)(uintptr_t)base, (unsigned long long)nt->OptionalHeader.ImageBase,
           image_size, (unsigned long long)(probe - (unsigned char *)base), *probe, marker, count);
    fflush(stdout);
    return 1;
}

int wmain(int argc, wchar_t **argv)
{
    void *reserved = NULL;
    int command;

    if (argc < 3) return 2;
    self = !wcscmp(argv[1], L"--self");
    if (!self && !GetFullPathNameW(argv[1], 32768, path, NULL)) return 2;
    flags = wcstoul(argv[2], NULL, 0);
    if (argc == 5)
    {
        void *address = (void *)(uintptr_t)_wcstoui64(argv[3], NULL, 0);
        SIZE_T size = (SIZE_T)_wcstoui64(argv[4], NULL, 0);
        reserved = VirtualAlloc(address, size, MEM_RESERVE, PAGE_NOACCESS);
        if (reserved != address) return 3;
    }
    if (!describe()) return 4;
    while ((command = getchar()) != EOF && command != 'q')
    {
        if (command == 'u')
        {
            if (!FreeLibrary(module)) return 5;
            module = NULL;
            puts("{\"unloaded\":true}");
        }
        else if (command == 'l')
        {
            if (module || !describe()) return 6;
            continue;
        }
        else if (command == 's')
        {
            typedef LONG (__cdecl *shared_fn)(void);
            shared_fn fn = (shared_fn)(void *)GetProcAddress(module, "image_shared_bump");
            printf("{\"shared\":%ld}\n", fn());
        }
        else if (command == 'w' || command == 'r')
        {
            DWORD old, unused;
            if (command == 'w')
            {
                if (!VirtualProtect(probe, 1, PAGE_READWRITE, &old)) return 7;
                *probe ^= 1;
                if (!VirtualProtect(probe, 1, old, &unused)) return 8;
            }
            printf("{\"probe\":%u}\n", *probe);
        }
        else if (command == 't')
        {
            IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)(base + ((IMAGE_DOS_HEADER *)base)->e_lfanew);
            IMAGE_SECTION_HEADER *section = IMAGE_FIRST_SECTION(nt);
            unsigned long checksum = 0;
            unsigned int i;
            for (i = 0; i < nt->FileHeader.NumberOfSections; i++)
            {
                DWORD offset, size = section[i].Misc.VirtualSize;
                volatile unsigned char *bytes = (unsigned char *)base + section[i].VirtualAddress;
                if ((section[i].Characteristics & (IMAGE_SCN_MEM_READ | IMAGE_SCN_MEM_WRITE)) != IMAGE_SCN_MEM_READ)
                    continue;
                for (offset = 0; offset < size; offset += 4096) checksum += bytes[offset];
                if (size) checksum += bytes[size - 1];
            }
            printf("{\"checksum\":%lu}\n", checksum);
        }
        else return 9;
        fflush(stdout);
    }
    if (module) FreeLibrary(module);
    if (reserved) VirtualFree(reserved, 0, MEM_RELEASE);
    return 0;
}
