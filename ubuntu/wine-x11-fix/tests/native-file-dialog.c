#define WIN32_LEAN_AND_MEAN
#define COBJMACROS
#include <windows.h>
#include <shobjidl.h>
#include <shlobj.h>
#include <shellapi.h>
#include <stdio.h>
#include <string.h>

static IFileDialog *dialog;
static unsigned int ticks, accepted, selection_changed, type_changed, folder_changed, veto;
static DWORD calling_thread;
static BOOL callbacks_valid = TRUE, close_requested, custom;
static BOOL quit_requested, fallback_requested;

static void text_json(const WCHAR *text)
{
    char utf8[32768];
    unsigned char *p;
    WideCharToMultiByte(CP_UTF8, 0, text, -1, utf8, sizeof(utf8), NULL, NULL);
    putchar('"');
    for (p = (unsigned char *)utf8; *p; p++)
    {
        if (*p == '"' || *p == '\\') putchar('\\');
        if (*p < 32) printf("\\u%04x", *p);
        else putchar(*p);
    }
    putchar('"');
}

static void check_callback(IFileDialog *dlg)
{
    IOleWindow *window;
    HWND hwnd;
    callbacks_valid = callbacks_valid && calling_thread == GetCurrentThreadId();
    if (SUCCEEDED(IFileDialog_QueryInterface(dlg, &IID_IOleWindow, (void **)&window)))
    {
        callbacks_valid = callbacks_valid && SUCCEEDED(IOleWindow_GetWindow(window, &hwnd)) && IsWindow(hwnd);
        IOleWindow_Release(window);
    }
    else callbacks_valid = FALSE;
}

static HRESULT WINAPI events_query(IFileDialogEvents *iface, REFIID iid, void **out)
{
    *out = NULL;
    if (!IsEqualGUID(iid, &IID_IUnknown) && !IsEqualGUID(iid, &IID_IFileDialogEvents)) return E_NOINTERFACE;
    *out = iface;
    return S_OK;
}
static ULONG WINAPI events_ref(IFileDialogEvents *iface) { return 2; }
static HRESULT WINAPI events_ok(IFileDialogEvents *iface, IFileDialog *dlg)
{
    IShellItem *item = NULL;
    accepted++;
    check_callback(dlg);
    callbacks_valid = callbacks_valid && SUCCEEDED(IFileDialog_GetCurrentSelection(dlg, &item));
    if (item) IShellItem_Release(item);
    return veto && accepted == 1 ? S_FALSE : S_OK;
}
static HRESULT WINAPI events_changing(IFileDialogEvents *iface, IFileDialog *dlg, IShellItem *folder)
{
    check_callback(dlg);
    return S_OK;
}
static HRESULT WINAPI events_folder(IFileDialogEvents *iface, IFileDialog *dlg)
{
    folder_changed++;
    check_callback(dlg);
    return S_OK;
}
static HRESULT WINAPI events_selection(IFileDialogEvents *iface, IFileDialog *dlg)
{
    selection_changed++;
    check_callback(dlg);
    return S_OK;
}
static HRESULT WINAPI events_share(IFileDialogEvents *iface, IFileDialog *dlg, IShellItem *item,
                                   FDE_SHAREVIOLATION_RESPONSE *response)
{
    *response = FDESVR_DEFAULT;
    return S_OK;
}
static HRESULT WINAPI events_type(IFileDialogEvents *iface, IFileDialog *dlg)
{
    type_changed++;
    check_callback(dlg);
    return S_OK;
}
static HRESULT WINAPI events_overwrite(IFileDialogEvents *iface, IFileDialog *dlg, IShellItem *item,
                                       FDE_OVERWRITE_RESPONSE *response)
{
    *response = FDEOR_ACCEPT;
    return S_OK;
}
static IFileDialogEventsVtbl events_vtbl = {
    events_query, events_ref, events_ref, events_ok, events_changing, events_folder, events_selection,
    events_share, events_type, events_overwrite
};

static LRESULT CALLBACK proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    if (msg == WM_TIMER)
    {
        ticks++;
        if ((close_requested || custom) && ticks == 10) IFileDialog_Close(dialog, E_ABORT);
        if (fallback_requested && ticks == 10) IFileDialog_Close(dialog, E_ABORT);
        if (quit_requested && ticks == 10) PostQuitMessage(37);
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

static int check_manager(const char *mode)
{
    WCHAR directory[32768], first[32768], second[32768];
    PIDLIST_ABSOLUTE parent, items[2];
    PCUITEMID_CHILD children[2];
    HRESULT hr;
    GetEnvironmentVariableW(L"WECOM_QA_FILES", directory, ARRAYSIZE(directory));
    swprintf(first, ARRAYSIZE(first), L"%ls\\文件 空格'引号$().txt", directory);
    swprintf(second, ARRAYSIZE(second), L"%ls\\第二个.LOG", directory);
    if (!strcmp(mode, "manager-dir"))
    {
        SHELLEXECUTEINFOW exec = {.cbSize = sizeof(exec), .fMask = SEE_MASK_FLAG_NO_UI,
                                 .lpVerb = L"open", .lpFile = directory, .nShow = SW_SHOW};
        hr = ShellExecuteExW(&exec) ? S_OK : E_FAIL;
    }
    else if (!strcmp(mode, "manager-explorer"))
    {
        WCHAR parameters[32768];
        swprintf(parameters, ARRAYSIZE(parameters), L"/select,\"%ls\"", first);
        hr = (UINT_PTR)ShellExecuteW(NULL, L"open", L"explorer.exe", parameters, NULL, SW_SHOW) > 32 ? S_OK : E_FAIL;
    }
    else
    {
        hr = SHParseDisplayName(first, NULL, &items[0], 0, NULL);
        if (FAILED(hr)) return 3;
        if (!strcmp(mode, "manager-one")) hr = SHOpenFolderAndSelectItems(items[0], 0, NULL, 0);
        else
        {
            hr = SHParseDisplayName(directory, NULL, &parent, 0, NULL);
            if (FAILED(hr)) return 3;
            hr = SHParseDisplayName(second, NULL, &items[1], 0, NULL);
            if (FAILED(hr)) return 3;
            children[0] = ILFindLastID(items[0]);
            children[1] = ILFindLastID(items[1]);
            hr = SHOpenFolderAndSelectItems(parent, 2, children, 0);
            ILFree(items[1]);
            ILFree(parent);
        }
        ILFree(items[0]);
    }
    printf("{\"hr\":%lu}\n", (DWORD)hr);
    return FAILED(hr);
}

int main(int argc, char **argv)
{
    IFileDialogEvents events = {&events_vtbl};
    IFileOpenDialog *open;
    IShellItemArray *results;
    IShellItem *folder, *item;
    WCHAR directory[32768], *path;
    COMDLG_FILTERSPEC filters[] = {{L"文本文件", L"*.txt;*.log"}, {L"所有文件", L"*.*"}};
    WNDCLASSW cls = {.lpfnWndProc = proc, .lpszClassName = L"NativeDialogProbe"};
    FILEOPENDIALOGOPTIONS options;
    HWND owner;
    HRESULT hr;
    DWORD cookie, count = 0, i;
    BOOL readonly = argc > 1 && !strcmp(argv[1], "save-readonly");
    BOOL unsupported_save = argc > 1 && !strcmp(argv[1], "save-unsupported");
    BOOL save_veto = argc > 1 && !strcmp(argv[1], "save-veto");
    BOOL filter_save = argc > 1 && !strncmp(argv[1], "save-filter", 11);
    BOOL save = argc > 1 && (!strcmp(argv[1], "save") || readonly || unsupported_save || save_veto || filter_save);
    BOOL reuse_custom = argc > 1 && !strcmp(argv[1], "reuse-custom");
    BOOL reuse = argc > 1 && (!strcmp(argv[1], "reuse") || reuse_custom);
    BOOL stale_result = FALSE;
    unsigned int quit_code = 0;
    MSG message;

    veto = save_veto || (argc > 1 && !strcmp(argv[1], "veto"));
    close_requested = argc > 1 && (!strcmp(argv[1], "close") || !strcmp(argv[1], "slow-close"));
    custom = argc > 1 && !strcmp(argv[1], "custom");
    quit_requested = argc > 1 && !strcmp(argv[1], "quit");
    fallback_requested = unsupported_save || (argc > 1 && !strcmp(argv[1], "unavailable"));
    calling_thread = GetCurrentThreadId();
    CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);
    if (argc > 1 && !strncmp(argv[1], "manager-", 8)) return check_manager(argv[1]);
    RegisterClassW(&cls);
    owner = CreateWindowW(cls.lpszClassName, L"原生文件选择测试", WS_OVERLAPPEDWINDOW | WS_VISIBLE,
                          300, 180, 400, 200, NULL, NULL, NULL, NULL);
    hr = CoCreateInstance(save ? &CLSID_FileSaveDialog : &CLSID_FileOpenDialog, NULL, CLSCTX_INPROC_SERVER,
                          &IID_IFileDialog, (void **)&dialog);
    if (FAILED(hr)) return 2;
    IFileDialog_GetOptions(dialog, &options);
    if (!save) options |= FOS_FORCEFILESYSTEM | FOS_ALLOWMULTISELECT;
    if (argc > 1 && !strcmp(argv[1], "folder")) options |= FOS_PICKFOLDERS;
    if (unsupported_save) options |= FOS_PICKFOLDERS;
    IFileDialog_SetOptions(dialog, options);
    if (filter_save)
    {
        filters[0].pszSpec = L"*.txt";
        filters[1].pszName = L"日志文件";
        filters[1].pszSpec = L"*.log";
    }
    IFileDialog_SetFileTypes(dialog, 2, filters);
    IFileDialog_SetFileTypeIndex(dialog, filter_save ? 1 : 2);
    IFileDialog_SetTitle(dialog, L"选择文件/文件夹 — 中文标题");
    IFileDialog_SetOkButtonLabel(dialog, L"选择");
    if (save)
    {
        IFileDialog_SetFileName(dialog, L"中文报告.txt");
        if (strcmp(argv[1], "save-filter-no-default")) IFileDialog_SetDefaultExtension(dialog, L"txt");
    }
    if (custom)
    {
        IFileDialogCustomize *controls;
        IFileDialog_QueryInterface(dialog, &IID_IFileDialogCustomize, (void **)&controls);
        IFileDialogCustomize_AddCheckButton(controls, 100, L"自定义控件", TRUE);
        IFileDialogCustomize_Release(controls);
    }
    if (GetEnvironmentVariableW(L"WECOM_QA_FILES", directory, ARRAYSIZE(directory)) &&
        SUCCEEDED(SHCreateItemFromParsingName(directory, NULL, &IID_IShellItem, (void **)&folder)))
    {
        IFileDialog_SetFolder(dialog, folder);
        IShellItem_Release(folder);
    }
    IFileDialog_Advise(dialog, &events, &cookie);
    if (readonly)
    {
        wcscat(directory, L"\\readonly.txt");
        SetFileAttributesW(directory, FILE_ATTRIBUTE_READONLY);
    }
    SetTimer(owner, 1, 50, NULL);
    hr = IFileDialog_Show(dialog, owner);
    if (readonly) SetFileAttributesW(directory, FILE_ATTRIBUTE_NORMAL);
    if (reuse)
    {
        if (FAILED(hr)) return 4;
        if (reuse_custom)
        {
            IFileDialogCustomize *controls;
            IFileDialog_QueryInterface(dialog, &IID_IFileDialogCustomize, (void **)&controls);
            IFileDialogCustomize_AddCheckButton(controls, 100, L"自定义控件", TRUE);
            IFileDialogCustomize_Release(controls);
            custom = TRUE;
            ticks = 0;
        }
        hr = IFileDialog_Show(dialog, owner);
        stale_result = SUCCEEDED(IFileDialog_GetResult(dialog, &item));
        if (stale_result) IShellItem_Release(item);
    }
    if (quit_requested && PeekMessageW(&message, NULL, WM_QUIT, WM_QUIT, PM_REMOVE)) quit_code = message.wParam;
    KillTimer(owner, 1);
    printf("{\"hr\":%lu,\"ticks\":%u,\"accepted\":%u,\"selection_changed\":%u,\"folder_changed\":%u,"
           "\"type_changed\":%u,\"callbacks_valid\":%s,\"owner_enabled\":%s,\"paths\":[",
           (DWORD)hr, ticks, accepted, selection_changed, folder_changed, type_changed,
           callbacks_valid ? "true" : "false", IsWindowEnabled(owner) ? "true" : "false");
    if (SUCCEEDED(hr))
    {
        if (save)
        {
            if (SUCCEEDED(IFileDialog_GetResult(dialog, &item)))
            {
                IShellItem_GetDisplayName(item, SIGDN_FILESYSPATH, &path);
                text_json(path);
                CoTaskMemFree(path);
                IShellItem_Release(item);
                count = 1;
            }
        }
        else
        {
            IFileDialog_QueryInterface(dialog, &IID_IFileOpenDialog, (void **)&open);
            if (SUCCEEDED(IFileOpenDialog_GetResults(open, &results)))
            {
                IShellItemArray_GetCount(results, &count);
                for (i = 0; i < count; i++)
                {
                    IShellItemArray_GetItemAt(results, i, &item);
                    IShellItem_GetDisplayName(item, SIGDN_FILESYSPATH, &path);
                    if (i) putchar(',');
                    text_json(path);
                    CoTaskMemFree(path);
                    IShellItem_Release(item);
                }
                IShellItemArray_Release(results);
            }
            IFileOpenDialog_Release(open);
        }
    }
    printf("],\"count\":%lu,\"quit_code\":%u,\"stale_result\":%s}\n", count, quit_code,
           stale_result ? "true" : "false");
    IFileDialog_Unadvise(dialog, cookie);
    IFileDialog_Release(dialog);
    DestroyWindow(owner);
    CoUninitialize();
    return 0;
}
