#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

/* API stand-ins only. The queue, worker, removal and relation functions are
 * extracted unchanged from the supplied Wine source by run-queue.py. */
typedef int BOOL;
typedef unsigned char UCHAR;
typedef unsigned long ULONG, DWORD;
typedef unsigned DEVICE_RELATION_TYPE;
typedef wchar_t WCHAR;
typedef void *HDEVINFO, *HKEY;
typedef pthread_mutex_t CRITICAL_SECTION;
typedef pthread_cond_t CONDITION_VARIABLE;
#define TRUE 1
#define FALSE 0
#define WINAPI
#define CALLBACK
#define INFINITE (~0u)
#define MAX_DEVICE_ID_LEN 200
#define BusRelations 0
#define IRP_MJ_PNP 1
#define IRP_MN_QUERY_DEVICE_RELATIONS 2
#define IRP_MN_SURPRISE_REMOVAL 3
#define IRP_MN_REMOVE_DEVICE 4
#define STATUS_NOT_SUPPORTED 1
#define STATUS_PENDING 2
#define NotificationEvent 0
#define Executive 0
#define KernelMode 0
#define DEVPROP_TYPE_STRING_LIST 1
#define DECLARE_CRITICAL_SECTION(name) static CRITICAL_SECTION name = PTHREAD_MUTEX_INITIALIZER
#define CONDITION_VARIABLE_INIT PTHREAD_COND_INITIALIZER
#define CONTAINING_RECORD(pointer, type, member) ((type *)((char *)(pointer) - offsetof(type, member)))
#define TRACE(...) ((void)0)
#define ERR(...) ((void)0)
#define FIXME(...) ((void)0)
#define ExFreePool free

typedef struct device_object DEVICE_OBJECT;
typedef struct { ULONG Count; DEVICE_OBJECT *Objects[]; } DEVICE_RELATIONS;
struct device_object
{
    atomic_int refs;
    unsigned queries, additions, removals;
    DEVICE_OBJECT **reported;
    unsigned reported_count;
    BOOL block_first;
    WCHAR *children_property;
    size_t children_bytes;
    WCHAR id[MAX_DEVICE_ID_LEN];
};
struct wine_device
{
    DEVICE_OBJECT device_obj;
    DEVICE_RELATIONS *children;
    HKEY dyn_data_key;
    BOOL removed;
};
typedef struct { DWORD cbSize; DEVICE_OBJECT *device; } SP_DEVINFO_DATA;
typedef struct { int Status; uintptr_t Information; } IO_STATUS_BLOCK;
typedef struct { int MinorFunction; struct { struct { int Type; } QueryDeviceRelations; } Parameters; }
    IO_STACK_LOCATION;
typedef struct { IO_STACK_LOCATION stack; IO_STATUS_BLOCK IoStatus, *result; } IRP;
typedef int KEVENT;

static struct wine_device objects[1025];
static unsigned object_count;
static unsigned sibling_writes, children_writes;
static size_t sibling_bytes;
static int DEVPKEY_Device_Children, DEVPKEY_Device_Siblings;
static pthread_mutex_t control = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t progress = PTHREAD_COND_INITIALIZER;
static BOOL query_entered, release_query, stopping;
static atomic_bool fail_allocation;

static void EnterCriticalSection(CRITICAL_SECTION *cs) { assert(!pthread_mutex_lock(cs)); }
static void LeaveCriticalSection(CRITICAL_SECTION *cs) { assert(!pthread_mutex_unlock(cs)); }
static void WakeConditionVariable(CONDITION_VARIABLE *cv) { assert(!pthread_cond_signal(cv)); }
static void SleepConditionVariableCS(CONDITION_VARIABLE *cv, CRITICAL_SECTION *cs, unsigned timeout)
{
    (void)timeout;
    if (!stopping) assert(!pthread_cond_wait(cv, cs));
    if (stopping)
    {
        LeaveCriticalSection(cs);
        pthread_exit(NULL);
    }
}
static void ObReferenceObject(DEVICE_OBJECT *device) { assert(atomic_fetch_add(&device->refs, 1) > 0); }
static void ObDereferenceObject(DEVICE_OBJECT *device)
{
    assert(atomic_fetch_sub(&device->refs, 1) > 0);
    pthread_mutex_lock(&control);
    pthread_cond_broadcast(&progress);
    pthread_mutex_unlock(&control);
}
static void *queue_realloc(void *pointer, size_t size)
{
    if (atomic_exchange(&fail_allocation, FALSE)) return NULL;
    return realloc(pointer, size);
}
#define realloc queue_realloc

static void RegDeleteKeyW(HKEY key, const WCHAR *name) { (void)key; (void)name; }
static void RegCloseKey(HKEY key) { (void)key; }
static void send_pnp_irp(DEVICE_OBJECT *device, UCHAR code)
{
    if (code == IRP_MN_REMOVE_DEVICE)
    {
        struct wine_device *wine_device = CONTAINING_RECORD(device, struct wine_device, device_obj);
        unsigned i;
        ++device->removals;
        if (wine_device->children)
        {
            for (i = 0; i < wine_device->children->Count; ++i)
                ObDereferenceObject(wine_device->children->Objects[i]);
            free(wine_device->children);
        }
        ObDereferenceObject(device);
    }
}
static HDEVINFO SetupDiCreateDeviceInfoList(void *type, void *window) { (void)type; (void)window; return (void *)1; }
static void SetupDiDestroyDeviceInfoList(HDEVINFO set) { (void)set; }
static DEVICE_OBJECT *IoGetAttachedDevice(DEVICE_OBJECT *device) { return device; }
static void KeInitializeEvent(KEVENT *event, int type, BOOL state) { (void)event; (void)type; (void)state; }
static IRP *IoBuildSynchronousFsdRequest(int code, DEVICE_OBJECT *device, void *buffer, int size,
                                      void *offset, KEVENT *event, IO_STATUS_BLOCK *result)
{
    IRP *irp = calloc(1, sizeof(*irp));
    (void)code; (void)device; (void)buffer; (void)size; (void)offset; (void)event;
    assert(irp);
    irp->result = result;
    return irp;
}
static IO_STACK_LOCATION *IoGetNextIrpStackLocation(IRP *irp) { return &irp->stack; }
static int IoCallDriver(DEVICE_OBJECT *device, IRP *irp)
{
    DEVICE_RELATIONS *relations;
    unsigned i;
    pthread_mutex_lock(&control);
    ++device->queries;
    relations = malloc(offsetof(DEVICE_RELATIONS, Objects[device->reported_count]));
    assert(relations);
    relations->Count = device->reported_count;
    for (i = 0; i < device->reported_count; ++i)
    {
        relations->Objects[i] = device->reported[i];
        ObReferenceObject(relations->Objects[i]);
    }
    if (device->block_first && device->queries == 1)
    {
        query_entered = TRUE;
        pthread_cond_broadcast(&progress);
        while (!release_query) pthread_cond_wait(&progress, &control);
    }
    pthread_mutex_unlock(&control);
    irp->result->Status = 0;
    irp->result->Information = (uintptr_t)relations;
    free(irp);
    return 0;
}
static void KeWaitForSingleObject(KEVENT *event, int reason, int mode, BOOL alert, void *timeout)
{
    (void)event; (void)reason; (void)mode; (void)alert; (void)timeout;
    abort();
}
static void enumerate_new_device(DEVICE_OBJECT *device, HDEVINFO set, DEVICE_OBJECT *parent)
{
    (void)set; (void)parent;
    ++device->additions;
}
static int get_device_instance_id(DEVICE_OBJECT *device, WCHAR *id) { wcscpy(id, device->id); return 0; }
static BOOL SetupDiOpenDeviceInfoW(HDEVINFO set, const WCHAR *id, void *window, int flags, SP_DEVINFO_DATA *info)
{
    unsigned i;
    (void)set; (void)window; (void)flags;
    for (i = 0; i < object_count; ++i)
        if (!wcscmp(id, objects[i].device_obj.id)) { info->device = &objects[i].device_obj; return TRUE; }
    return FALSE;
}
typedef unsigned char BYTE;
static void SetupDiSetDevicePropertyW(HDEVINFO set, SP_DEVINFO_DATA *info, int *key, int type,
                                     BYTE *value, size_t bytes, int flags)
{
    (void)set; (void)type; (void)flags;
    if (key == &DEVPKEY_Device_Siblings) { ++sibling_writes; sibling_bytes += bytes; return; }
    assert(key == &DEVPKEY_Device_Children);
    ++children_writes;
    free(info->device->children_property);
    info->device->children_property = malloc(bytes);
    assert(info->device->children_property);
    memcpy(info->device->children_property, value, bytes);
    info->device->children_bytes = bytes;
}

#include "production.inc"

static DEVICE_OBJECT *new_device(void)
{
    DEVICE_OBJECT *device = &objects[object_count].device_obj;
    assert(object_count < sizeof(objects) / sizeof(objects[0]));
    atomic_init(&device->refs, 1);
    swprintf(device->id, MAX_DEVICE_ID_LEN, L"FIXTURE\\DEVICE\\%u", object_count++);
    return device;
}
static void check(BOOL condition, const char *message)
{
    if (!condition)
    {
        fprintf(stderr, "FAIL: %s; pending=%zu children_writes=%u siblings_writes=%u siblings_bytes=%zu\n",
                message, invalidated_devices_count, children_writes, sibling_writes, sibling_bytes);
        exit(1);
    }
}
static void *run_worker(void *unused) { (void)unused; device_enum_thread_proc(NULL); return NULL; }
static void *produce(void *pointer)
{
    unsigned i;
    for (i = 0; i < 10000; ++i) IoInvalidateDeviceRelations(pointer, BusRelations);
    return NULL;
}
static void test_queue(void)
{
    DEVICE_OBJECT *parent = new_device(), *child = new_device(), *dead = new_device(), *other = new_device();
    DEVICE_OBJECT *reported[] = {child};
    pthread_t worker, producers[4];
    unsigned i;

    for (i = 0; i < 10000; ++i) IoInvalidateDeviceRelations(parent, BusRelations);
    check(invalidated_devices_count == 1, "duplicate pending invalidations were not coalesced");
    check(atomic_load(&parent->refs) == 2, "pending queue does not own exactly one reference");
    IoInvalidateDeviceRelations(dead, BusRelations);
    ObReferenceObject(dead); /* External observer keeps the removed object inspectable. */
    send_remove_device_irp(dead, IRP_MN_SURPRISE_REMOVAL);
    check(invalidated_devices_count == 2, "surprise removal prematurely discarded pending work");
    send_remove_device_irp(dead, IRP_MN_REMOVE_DEVICE);
    check(invalidated_devices_count == 1 && atomic_load(&dead->refs) == 1,
          "terminal removal did not cancel the pending reference");
    IoInvalidateDeviceRelations(dead, BusRelations);
    check(invalidated_devices_count == 1, "removed device was queued again");
    ObDereferenceObject(dead);

    atomic_store(&fail_allocation, TRUE);
    IoInvalidateDeviceRelations(other, BusRelations);
    check(invalidated_devices_count == 1 && atomic_load(&other->refs) == 1,
          "allocation failure lost the old queue or leaked a reference");

    parent->block_first = TRUE;
    assert(!pthread_create(&worker, NULL, run_worker, NULL));
    pthread_mutex_lock(&control);
    while (!query_entered) pthread_cond_wait(&progress, &control);
    parent->reported = reported;
    parent->reported_count = 1;
    pthread_mutex_unlock(&control);
    for (i = 0; i < 4; ++i) assert(!pthread_create(&producers[i], NULL, produce, parent));
    for (i = 0; i < 4; ++i) assert(!pthread_join(producers[i], NULL));
    EnterCriticalSection(&invalidated_devices_cs);
    check(invalidated_devices_count == 1 && atomic_load(&parent->refs) == 3,
          "in-flight invalidation did not retain one separate follow-up pass");
    LeaveCriticalSection(&invalidated_devices_cs);
    pthread_mutex_lock(&control);
    release_query = TRUE;
    pthread_cond_broadcast(&progress);
    while (parent->queries < 2 || atomic_load(&parent->refs) != 1) pthread_cond_wait(&progress, &control);
    pthread_mutex_unlock(&control);
    check(parent->queries == 2 && child->additions == 1 && dead->queries == 0,
          "worker lost or duplicated the follow-up change, or enumerated a removed device");
    EnterCriticalSection(&invalidated_devices_cs);
    stopping = TRUE;
    WakeConditionVariable(&invalidated_devices_cv);
    LeaveCriticalSection(&invalidated_devices_cs);
    assert(!pthread_join(worker, NULL));
    check(invalidated_devices_count == 0, "queue not drained");
    printf("{\"case\":\"queue\",\"passed\":true,\"notifications\":50000,\"enumerations\":%u}\n", parent->queries);
}
static void test_relations(void)
{
    DEVICE_OBJECT *parent = new_device(), *reported[1000];
    unsigned i;
    for (i = 0; i < 1000; ++i) reported[i] = new_device();
    parent->reported = reported;
    parent->reported_count = 1000;
    handle_bus_relations(parent);
    check(sibling_writes == 0, "siblings were materialized once per child");
    check(children_writes == 1 && parent->children_bytes > sizeof(WCHAR), "parent children list missing");
    IoInvalidateDeviceRelations(reported[500], BusRelations);
    check(invalidated_devices_count == 1 && atomic_load(&reported[500]->refs) == 3,
          "queued child does not own a reference in addition to its parent and driver");
    parent->reported_count = 0;
    handle_bus_relations(parent);
    check(invalidated_devices_count == 0, "removed child remained in the invalidation queue");
    check(children_writes == 2 && parent->children_bytes == sizeof(WCHAR) && !parent->children_property[0],
          "empty bus retained stale children");
    for (i = 0; i < 1000; ++i)
        check(reported[i]->additions == 1 && reported[i]->removals == 1 && !atomic_load(&reported[i]->refs),
              "child lifetime references are unbalanced");
    printf("{\"case\":\"relations\",\"passed\":true,\"children\":1000,"
           "\"children_writes\":%u,\"siblings_writes\":%u,\"siblings_bytes\":%zu}\n",
           children_writes, sibling_writes, sibling_bytes);
}
int main(int argc, char **argv)
{
    check(argc == 2, "expected queue or relations case");
    if (!strcmp(argv[1], "queue")) test_queue();
    else if (!strcmp(argv[1], "relations")) test_relations();
    else return 2;
    return 0;
}
