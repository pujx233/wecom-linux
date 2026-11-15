#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static wchar_t path[32768];
static HMODULE module;
static unsigned char *probe;
static DWORD image_size;

static int describe(void)
{
    typedef int (__cdecl *int_fn)(void);
    typedef int (__cdecl *version_fn)(int);
    typedef const char *(__cdecl *pointer_fn)(void);
    typedef const char *(__cdecl *hash_fn)(int);
    IMAGE_DOS_HEADER *dos;
    IMAGE_NT_HEADERS *nt;
    IMAGE_SECTION_HEADER *section;
    unsigned long checksum = 0;
    int marker = 0, count = 0;
    unsigned int i;
    char api_hash[65] = "";
    int_fn marker_fn, bump_fn, owner_fn;
    version_fn version;
    pointer_fn pointer;
    hash_fn hash;

    module = LoadLibraryExW(path, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (!module)
    {
        printf("{\"error\":%lu}\n", GetLastError());
        fflush(stdout);
        return 0;
    }
    dos = (IMAGE_DOS_HEADER *)module;
    nt = (IMAGE_NT_HEADERS *)((char *)module + dos->e_lfanew);
    section = IMAGE_FIRST_SECTION(nt);
    image_size = nt->OptionalHeader.SizeOfImage;
    probe = (unsigned char *)GetProcAddress(module, "cache_probe");
    for (i = 0; i < nt->FileHeader.NumberOfSections; i++)
    {
        DWORD offset, size = section[i].Misc.VirtualSize;
        volatile unsigned char *bytes = (unsigned char *)module + section[i].VirtualAddress;

        if (!(section[i].Characteristics & IMAGE_SCN_MEM_READ) ||
            (section[i].Characteristics & IMAGE_SCN_MEM_WRITE)) continue;
        if (!probe && (section[i].Characteristics & IMAGE_SCN_MEM_EXECUTE))
            probe = (unsigned char *)bytes + 16;
        for (offset = 0; offset < size; offset += 4096) checksum += bytes[offset];
        if (size) checksum += bytes[size - 1];
    }
    marker_fn = (int_fn)GetProcAddress(module, "image_marker");
    bump_fn = (int_fn)GetProcAddress(module, "image_bump");
    owner_fn = (int_fn)GetProcAddress(module, "image_owner");
    pointer = (pointer_fn)(void *)GetProcAddress(module, "image_pointer");
    if (marker_fn)
    {
        const char *value = pointer();
        marker = marker_fn();
        count = bump_fn();
        if ((uintptr_t)value < (uintptr_t)module || (uintptr_t)value >= (uintptr_t)module + image_size ||
            strcmp(value, "cef-image-cache") || (DWORD)owner_fn() != GetCurrentProcessId()) return 0;
    }
    version = (version_fn)GetProcAddress(module, "cef_version_info");
    hash = (hash_fn)(void *)GetProcAddress(module, "cef_api_hash");
    if (version)
    {
        const char *value = hash(0);
        int major = version(0);
        if (major <= 0 || !value || strlen(value) != 40 ||
            (uintptr_t)value < (uintptr_t)module || (uintptr_t)value >= (uintptr_t)module + image_size) return 0;
        memcpy(api_hash, value, 40);
        printf("{\"version\":%d,", major);
    }
    else printf("{\"version\":0,");
    printf("\"pid\":%lu,\"base\":%lu,\"size\":%lu,\"probe\":%u,\"marker\":%d,"
           "\"count\":%d,\"checksum\":%lu,\"api_hash\":\"%s\"}\n",
           GetCurrentProcessId(), (unsigned long)module, image_size, *probe, marker, count, checksum, api_hash);
    fflush(stdout);
    return 1;
}

int wmain(int argc, wchar_t **argv)
{
    void *reserved = NULL;

    if (argc != 2 && argc != 4) return 2;
    if (!GetFullPathNameW(argv[1], 32768, path, NULL)) return 3;
    if (argc == 4)
    {
        void *address = (void *)(uintptr_t)wcstoul(argv[2], NULL, 0);
        SIZE_T size = wcstoul(argv[3], NULL, 0);
        reserved = VirtualAlloc(address, size, MEM_RESERVE, PAGE_NOACCESS);
        if (reserved != address) return 4;
    }
    if (!describe()) return 5;
    for (;;)
    {
        int command = getchar();
        DWORD old, unused;

        if (command == 'q' || command == EOF) break;
        if (command == 'u')
        {
            if (!FreeLibrary(module)) return 6;
            module = NULL;
            puts("{\"unloaded\":true}");
        }
        else if (command == 'l')
        {
            if (module || !describe()) return 7;
            continue;
        }
        else if (command == 's')
        {
            typedef LONG (__cdecl *shared_fn)(void);
            shared_fn shared = (shared_fn)GetProcAddress(module, "image_shared_bump");
            printf("{\"shared\":%ld}\n", shared());
        }
        else if (command == 'w' || command == 'r')
        {
            if (!module) return 8;
            if (command == 'w')
            {
                if (!VirtualProtect(probe, 1, PAGE_EXECUTE_WRITECOPY, &old)) return 9;
                *probe ^= 1;
                FlushInstructionCache(GetCurrentProcess(), probe, 1);
                if (!VirtualProtect(probe, 1, old, &unused)) return 10;
            }
            printf("{\"probe\":%u}\n", *probe);
        }
        else return 11;
        fflush(stdout);
    }
    if (module) FreeLibrary(module);
    if (reserved) VirtualFree(reserved, 0, MEM_RELEASE);
    return 0;
}
