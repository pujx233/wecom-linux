/* Synthetic relation properties only; the runner isolates the Wine prefix and system D-Bus. */
#include <windows.h>
#include <setupapi.h>
#include <cfgmgr32.h>
#include <initguid.h>
#include <devpkey.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>

BOOL WINAPI SetupDiSetDevicePropertyW(HDEVINFO, SP_DEVINFO_DATA *, const DEVPROPKEY *, DEVPROPTYPE,
                                      const BYTE *, DWORD, DWORD);

static const GUID test_class = {0x8b5ed1f9, 0xc024, 0x4acd, {0xae, 0xe9, 0xd1, 0x78, 0x6d, 0xd3, 0x15, 0x67}};
static HDEVINFO set;
static SP_DEVINFO_DATA parent = {.cbSize = sizeof(parent)}, children[16];
static WCHAR parent_id[200], ids[16][200];
static unsigned int failures, checks;

static void check(const char *name, BOOL passed)
{
    ++checks;
    if (!passed) ++failures;
    printf("{\"case\":\"%s\",\"passed\":%s}\n", name, passed ? "true" : "false");
}

static void set_property(SP_DEVINFO_DATA *device, const DEVPROPKEY *key, DEVPROPTYPE type,
                         const void *data, DWORD size)
{
    if (!SetupDiSetDevicePropertyW(set, device, key, type, data, size, 0))
    {
        check("set synthetic property", FALSE);
        exit(1);
    }
}

static void set_children(const unsigned int *indexes, unsigned int count)
{
    WCHAR buffer[4000], *p = buffer;
    unsigned int i;
    for (i = 0; i < count; ++i)
    {
        wcscpy(p, ids[indexes[i]]);
        p += wcslen(p) + 1;
    }
    *p++ = 0;
    set_property(&parent, &DEVPKEY_Device_Children, DEVPROP_TYPE_STRING_LIST, buffer, (p - buffer) * sizeof(WCHAR));
}

static DWORD make_expected(WCHAR *buffer, const unsigned int *indexes, unsigned int count)
{
    WCHAR *p = buffer;
    unsigned int i;
    for (i = 0; i < count; ++i)
    {
        wcscpy(p, ids[indexes[i]]);
        p += wcslen(p) + 1;
    }
    *p++ = 0;
    return (p - buffer) * sizeof(WCHAR);
}

static void query(unsigned int child, const DEVPROPKEY *key, const WCHAR *expected, DWORD expected_size)
{
    BYTE buffer[8192], untouched[8192];
    DEVPROPTYPE type;
    DWORD size;
    CONFIGRET cr;
    BOOL ret;

    type = 0xdeadbeef;
    size = 0;
    cr = CM_Get_DevNode_PropertyW(children[child].DevInst, key, &type, NULL, &size, 0);
    check("CM size and type", cr == CR_BUFFER_SMALL && type == DEVPROP_TYPE_STRING_LIST && size == expected_size);
    type = 0xdeadbeef;
    size = 0;
    ret = SetupDiGetDevicePropertyW(set, &children[child], key, &type, NULL, 0, &size, 0);
    check("Setup size and type", !ret && GetLastError() == ERROR_INSUFFICIENT_BUFFER &&
          type == DEVPROP_TYPE_STRING_LIST && size == expected_size);

    memset(buffer, 0xcc, sizeof(buffer));
    memcpy(untouched, buffer, sizeof(buffer));
    size = expected_size - 1;
    cr = CM_Get_DevNode_PropertyW(children[child].DevInst, key, &type, buffer, &size, 0);
    check("CM short buffer untouched", cr == CR_BUFFER_SMALL && size == expected_size &&
          !memcmp(buffer, untouched, sizeof(buffer)));
    ret = SetupDiGetDevicePropertyW(set, &children[child], key, &type, buffer, expected_size - 1, &size, 0);
    check("Setup short buffer untouched", !ret && GetLastError() == ERROR_INSUFFICIENT_BUFFER &&
          size == expected_size && !memcmp(buffer, untouched, sizeof(buffer)));

    size = sizeof(buffer);
    cr = CM_Get_DevNode_PropertyW(children[child].DevInst, key, &type, buffer, &size, 0);
    check("CM exact siblings", cr == CR_SUCCESS && type == DEVPROP_TYPE_STRING_LIST && size == expected_size &&
          !memcmp(buffer, expected, expected_size));
    memset(buffer, 0xcc, sizeof(buffer));
    ret = SetupDiGetDevicePropertyW(set, &children[child], key, &type, buffer, sizeof(buffer), &size, 0);
    check("Setup exact siblings", ret && type == DEVPROP_TYPE_STRING_LIST && size == expected_size &&
          !memcmp(buffer, expected, expected_size));
}

static void missing(unsigned int child)
{
    WCHAR buffer[512];
    DEVPROPTYPE type = 0xdeadbeef;
    DWORD size = sizeof(buffer);
    CONFIGRET cr = CM_Get_DevNode_PropertyW(children[child].DevInst, &DEVPKEY_Device_Siblings,
                                          &type, (BYTE *)buffer, &size, 0);
    check("CM missing relation", cr == CR_NO_SUCH_VALUE && size == 0 && type == 0xdeadbeef);
    type = 0xdeadbeef;
    size = sizeof(buffer);
    check("Setup missing relation", !SetupDiGetDevicePropertyW(set, &children[child], &DEVPKEY_Device_Siblings,
          &type, (BYTE *)buffer, sizeof(buffer), &size, 0) && GetLastError() == ERROR_NOT_FOUND &&
          size == 0 && type == DEVPROP_TYPE_EMPTY);
}

static void keys(unsigned int child, BOOL present)
{
    DEVPROPKEY values[128];
    DWORD count = 128, i, matches = 0;
    CONFIGRET cr = CM_Get_DevNode_Property_Keys(children[child].DevInst, values, &count, 0);
    check("CM key enumeration", cr == CR_SUCCESS && count <= 128);
    if (cr == CR_SUCCESS && count <= 128)
    {
        for (i = 0; i < count; ++i) matches += !memcmp(values + i, &DEVPKEY_Device_Siblings, sizeof(*values));
        check("CM dynamic key exactly once", matches == (unsigned int)present);
    }
    count = matches = 0;
    check("Setup key enumeration", SetupDiGetDevicePropertyKeys(set, &children[child], values, 128, &count, 0));
    if (count <= 128)
    {
        for (i = 0; i < count; ++i) matches += !memcmp(values + i, &DEVPKEY_Device_Siblings, sizeof(*values));
        check("Setup dynamic key exactly once", matches == (unsigned int)present);
    }
}

static DWORD stored_size(const WCHAR *instance, const DEVPROPKEY *property)
{
    WCHAR path[512];
    HKEY key;
    DWORD size = 0;
    LONG result;
    swprintf(path, 512, L"System\\CurrentControlSet\\Enum\\%ls\\Properties\\"
             L"{4340A6C5-93FA-4706-972C-7B648008A5A7}\\%04X", instance, property->pid);
    result = RegOpenKeyExW(HKEY_LOCAL_MACHINE, path, 0, KEY_QUERY_VALUE, &key);
    if (result == ERROR_FILE_NOT_FOUND) return 0;
    check("open synthetic property storage", result == ERROR_SUCCESS);
    if (result) return 0;
    result = RegQueryValueExW(key, NULL, NULL, NULL, NULL, &size);
    check("read synthetic property storage size", result == ERROR_SUCCESS);
    RegCloseKey(key);
    return size;
}

int main(void)
{
    const unsigned int ab[] = {0, 1}, abc[] = {0, 1, 2}, ac[] = {0, 2}, a[] = {0};
    const WCHAR stale[] = L"ROOT\\STALE\\999\0", unrelated[] = L"unrelated\0";
    WCHAR expected[4000], marker[2];
    DEVPROPKEY other = DEVPKEY_Device_Siblings;
    DWORD expected_size, i, count, parent_bytes, total_bytes[2] = {0};
    unsigned int indexes[16];

    if (!GetEnvironmentVariableW(L"WECOM_PNP_QA", marker, 2) || marker[0] != '1') return 2;
    setvbuf(stdout, NULL, _IONBF, 0);
    set = SetupDiCreateDeviceInfoList(&test_class, NULL);
    if (set == INVALID_HANDLE_VALUE) return 3;
    printf("{\"ready\":true}\n");
    if (getchar() == EOF) return 6;
    swprintf(parent_id, 200, L"ROOT\\WINEPNPRELATIONS\\P%08lx", GetCurrentProcessId());
    if (!SetupDiCreateDeviceInfoW(set, parent_id, &test_class, NULL, NULL, 0, &parent)) return 4;
    for (i = 0; i < 16; ++i)
    {
        children[i].cbSize = sizeof(children[i]);
        swprintf(ids[i], 200, L"ROOT\\WINEPNPRELATIONS\\C%08lx%02lu", GetCurrentProcessId(), i);
        if (!SetupDiCreateDeviceInfoW(set, ids[i], &test_class, NULL, NULL, 0, children + i)) return 5;
        set_property(children + i, &DEVPKEY_Device_Parent, DEVPROP_TYPE_STRING, parent_id,
                     (wcslen(parent_id) + 1) * sizeof(WCHAR));
        indexes[i] = i;
    }
    set_property(children, &DEVPKEY_Device_Siblings, DEVPROP_TYPE_STRING_LIST, stale, sizeof(stale));
    set_children(ab, 2);
    expected_size = make_expected(expected, ab + 1, 1);
    query(0, &DEVPKEY_Device_Siblings, expected, expected_size);
    keys(0, TRUE);
    check("stale storage not returned or rewritten", stored_size(ids[0], &DEVPKEY_Device_Siblings) == sizeof(stale));

    set_children(abc, 3);
    expected_size = make_expected(expected, abc + 1, 2);
    query(0, &DEVPKEY_Device_Siblings, expected, expected_size);
    set_children(ac, 2);
    expected_size = make_expected(expected, ac + 1, 1);
    query(0, &DEVPKEY_Device_Siblings, expected, expected_size);
    missing(1);
    keys(1, FALSE);
    set_children(a, 1);
    expected_size = make_expected(expected, NULL, 0);
    query(0, &DEVPKEY_Device_Siblings, expected, expected_size);
    set_children(NULL, 0);
    missing(0);
    keys(0, FALSE);
    set_property(&parent, &DEVPKEY_Device_Children, DEVPROP_TYPE_EMPTY, NULL, 0);
    missing(0);
    set_property(children + 2, &DEVPKEY_Device_Parent, DEVPROP_TYPE_EMPTY, NULL, 0);
    missing(2);

    {
        WCHAR too_long[300], buffer[10];
        DEVPROPTYPE type = 0xdeadbeef;
        DWORD size = sizeof(buffer);
        CONFIGRET cr;
        for (i = 0; i < 299; ++i) too_long[i] = 'X';
        too_long[299] = 0;
        set_property(children + 2, &DEVPKEY_Device_Parent, DEVPROP_TYPE_STRING, too_long, sizeof(too_long));
        cr = CM_Get_DevNode_PropertyW(children[2].DevInst, &DEVPKEY_Device_Siblings, &type,
                                     (BYTE *)buffer, &size, 0);
        check("CM oversized parent is not a sizing response", cr == CR_FAILURE && size == 0 && type == 0xdeadbeef);
        check("Setup oversized parent", !SetupDiGetDevicePropertyW(set, children + 2, &DEVPKEY_Device_Siblings,
              &type, (BYTE *)buffer, sizeof(buffer), &size, 0) && GetLastError() == ERROR_INVALID_DATA &&
              size == 0 && type == DEVPROP_TYPE_EMPTY);
    }

    other.fmtid.Data1 ^= 1;
    set_property(children, &other, DEVPROP_TYPE_STRING_LIST, unrelated, sizeof(unrelated));
    query(0, &other, unrelated, sizeof(unrelated));
    set_property(children, &DEVPKEY_Device_Siblings, DEVPROP_TYPE_EMPTY, NULL, 0);
    set_property(children + 2, &DEVPKEY_Device_Parent, DEVPROP_TYPE_STRING, parent_id,
                 (wcslen(parent_id) + 1) * sizeof(WCHAR));
    parent_bytes = (wcslen(parent_id) + 1) * sizeof(WCHAR);
    for (count = 8; count <= 16; count *= 2)
    {
        unsigned int stage = count == 8 ? 0 : 1;
        set_children(indexes, count);
        total_bytes[stage] = stored_size(parent_id, &DEVPKEY_Device_Children);
        check("canonical children bytes", total_bytes[stage] == make_expected(expected, indexes, count));
        for (i = 0; i < count; ++i)
        {
            WCHAR value[4000];
            DEVPROPTYPE type;
            DWORD size = sizeof(value);
            check("bulk relation query", CM_Get_DevNode_PropertyW(children[i].DevInst, &DEVPKEY_Device_Siblings,
                  &type, (BYTE *)value, &size, 0) == CR_SUCCESS);
            check("query does not materialize siblings", !stored_size(ids[i], &DEVPKEY_Device_Siblings));
            DWORD stored_parent = stored_size(ids[i], &DEVPKEY_Device_Parent);
            check("one parent per child", stored_parent == parent_bytes);
            total_bytes[stage] += stored_parent;
        }
    }
    check("linear canonical relation bytes", total_bytes[1] == 2 * total_bytes[0] - sizeof(WCHAR));
    for (i = 0; i < 16; ++i) SetupDiRemoveDevice(set, children + i);
    SetupDiRemoveDevice(set, &parent);
    SetupDiDestroyDeviceInfoList(set);
    printf("{\"summary\":true,\"checks\":%u,\"failures\":%u,\"canonical_bytes\":[%lu,%lu]}\n",
           checks, failures, total_bytes[0], total_bytes[1]);
    return failures ? 1 : 0;
}
