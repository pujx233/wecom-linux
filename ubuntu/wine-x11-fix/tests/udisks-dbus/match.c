/* Real private D-Bus broker and senders; only the device-operation endpoints are replaced. */
#include <dbus/dbus.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define TRACE(...) do {} while (0)
#define p_dbus_error_init dbus_error_init
#define p_dbus_error_free dbus_error_free
#define p_dbus_message_is_signal dbus_message_is_signal
#define p_dbus_message_get_args dbus_message_get_args
#define p_dbus_message_get_path dbus_message_get_path

static unsigned int queries, removals, failures;
static void udisks_new_device(const char *path) { ++queries; }
static void udisks_changed_device(const char *path) { ++queries; }
static void udisks_removed_device(const char *path) { ++removals; }
static int udisks2_add_devices(const char *path) { ++queries; return 1; }
#include "filter.inc"

static DBusConnection *connect_bus(void)
{
    DBusError error = DBUS_ERROR_INIT;
    DBusConnection *connection = dbus_bus_get_private(DBUS_BUS_SESSION, &error);
    if (!connection)
    {
        fprintf(stderr, "private bus connection failed: %s\n", error.message);
        exit(2);
    }
    dbus_connection_set_exit_on_disconnect(connection, FALSE);
    return connection;
}

static void own_name(DBusConnection *connection)
{
    DBusError error = DBUS_ERROR_INIT;
    int result = dbus_bus_request_name(connection, "org.freedesktop.UDisks2", DBUS_NAME_FLAG_DO_NOT_QUEUE, &error);
    if (result != DBUS_REQUEST_NAME_REPLY_PRIMARY_OWNER) exit(3);
}

static DBusMessage *make_signal(const char *path, const char *interface, const char *member, int invalidated)
{
    DBusMessage *message = dbus_message_new_signal(path, interface, member);
    DBusMessageIter iter, array, entry, variant;
    const char *block = "org.freedesktop.UDisks2.Block", *property = "IdLabel", *label = "Synthetic disk";
    const char *device = "/org/freedesktop/UDisks2/block_devices/test";
    dbus_message_iter_init_append(message, &iter);
    if (!strcmp(interface, "org.freedesktop.DBus.Properties"))
    {
        dbus_message_iter_append_basic(&iter, DBUS_TYPE_STRING, &block);
        dbus_message_iter_open_container(&iter, DBUS_TYPE_ARRAY, "{sv}", &array);
        if (!invalidated)
        {
            dbus_message_iter_open_container(&array, DBUS_TYPE_DICT_ENTRY, NULL, &entry);
            dbus_message_iter_append_basic(&entry, DBUS_TYPE_STRING, &property);
            dbus_message_iter_open_container(&entry, DBUS_TYPE_VARIANT, "s", &variant);
            dbus_message_iter_append_basic(&variant, DBUS_TYPE_STRING, &label);
            dbus_message_iter_close_container(&entry, &variant);
            dbus_message_iter_close_container(&array, &entry);
        }
        dbus_message_iter_close_container(&iter, &array);
        dbus_message_iter_open_container(&iter, DBUS_TYPE_ARRAY, "s", &array);
        if (invalidated) dbus_message_iter_append_basic(&array, DBUS_TYPE_STRING, &property);
        dbus_message_iter_close_container(&iter, &array);
    }
    else
    {
        dbus_message_iter_append_basic(&iter, DBUS_TYPE_OBJECT_PATH, &device);
        if (!strcmp(interface, "org.freedesktop.UDisks")) return message;
        if (!strcmp(member, "InterfacesAdded"))
        {
            dbus_message_iter_open_container(&iter, DBUS_TYPE_ARRAY, "{sa{sv}}", &array);
            dbus_message_iter_open_container(&array, DBUS_TYPE_DICT_ENTRY, NULL, &entry);
            dbus_message_iter_append_basic(&entry, DBUS_TYPE_STRING, &block);
            dbus_message_iter_open_container(&entry, DBUS_TYPE_ARRAY, "{sv}", &variant);
            dbus_message_iter_close_container(&entry, &variant);
            dbus_message_iter_close_container(&array, &entry);
            dbus_message_iter_close_container(&iter, &array);
        }
        else
        {
            dbus_message_iter_open_container(&iter, DBUS_TYPE_ARRAY, "s", &array);
            dbus_message_iter_append_basic(&array, DBUS_TYPE_STRING, &block);
            dbus_message_iter_close_container(&iter, &array);
        }
    }
    return message;
}

static void trial(DBusConnection *receiver, DBusConnection *sender, const char *name, const char *path,
                  const char *interface, const char *member, int invalidated,
                  unsigned int expected_queries, unsigned int expected_removals, unsigned int copies)
{
    DBusMessage *message, *barrier;
    unsigned int i, delivered = 0;
    int reached = 0, passed;
    queries = removals = 0;
    for (i = 0; i < copies; ++i)
    {
        message = make_signal(path, interface, member, invalidated);
        dbus_connection_send(sender, message, NULL);
        dbus_message_unref(message);
    }
    /* A directed barrier from the same sender follows all tested signals through the broker. */
    barrier = dbus_message_new_signal("/org/wine/Test", "org.wine.Test", "Barrier");
    dbus_message_set_destination(barrier, dbus_bus_get_unique_name(receiver));
    dbus_connection_send(sender, barrier, NULL);
    dbus_message_unref(barrier);
    dbus_connection_flush(sender);
    for (i = 0; i < 100 && !reached; ++i)
    {
        dbus_connection_read_write(receiver, 50);
        while ((message = dbus_connection_pop_message(receiver)))
        {
            reached = dbus_message_is_signal(message, "org.wine.Test", "Barrier");
            if (!reached)
            {
                if (dbus_message_has_interface(message, "org.freedesktop.DBus.Properties") ||
                    dbus_message_has_interface(message, "org.freedesktop.DBus.ObjectManager") ||
                    dbus_message_has_interface(message, "org.freedesktop.UDisks")) ++delivered;
                udisks_filter(receiver, message, NULL);
            }
            dbus_message_unref(message);
            if (reached) break;
        }
    }
    passed = reached && queries == expected_queries && removals == expected_removals &&
             delivered == expected_queries + expected_removals;
    printf("{\"case\":\"%s\",\"barrier\":%s,\"delivered\":%u,\"queries\":%u,\"removals\":%u,\"passed\":%s}\n",
           name, reached ? "true" : "false", delivered, queries, removals, passed ? "true" : "false");
    failures += !passed;
}

int main(void)
{
    const char *root = "/org/freedesktop/UDisks2", *block = "/org/freedesktop/UDisks2/block_devices/test";
    const char *properties = "org.freedesktop.DBus.Properties", *objects = "org.freedesktop.DBus.ObjectManager";
    DBusConnection *receiver = connect_bus(), *owner = connect_bus(), *other = connect_bus();
    DBusError error = DBUS_ERROR_INIT;
    unsigned int i;
    DBusConnection *all[] = {receiver, owner, other};
#include "rules.inc"
    own_name(owner);
    dbus_bus_add_match(receiver, udisks2_match_interfaces, &error);
    if (dbus_error_is_set(&error)) return 4;
    dbus_bus_add_match(receiver, udisks2_match_properties, &error);
    if (dbus_error_is_set(&error)) return 5;
    trial(receiver, other, "foreign sender burst with real UDisks path", block, properties,
          "PropertiesChanged", 0, 0, 0, 128);
    trial(receiver, owner, "wrong path", "/org/example/device", properties, "PropertiesChanged", 0, 0, 0, 1);
    trial(receiver, owner, "namespace prefix collision", "/org/freedesktop/UDisks2Other/device", properties,
          "PropertiesChanged", 0, 0, 0, 1);
    trial(receiver, owner, "wrong member", block, properties, "UnrelatedSignal", 0, 0, 0, 1);
    trial(receiver, owner, "disk property changed", block, properties, "PropertiesChanged", 0, 1, 0, 1);
    trial(receiver, owner, "disk property invalidated", block, properties, "PropertiesChanged", 1, 1, 0, 1);
    trial(receiver, owner, "namespace root remains accepted", root, properties, "PropertiesChanged", 0, 1, 0, 1);
    trial(receiver, other, "foreign interfaces added", root, objects, "InterfacesAdded", 0, 0, 0, 1);
    trial(receiver, owner, "interfaces added", root, objects, "InterfacesAdded", 0, 1, 0, 1);
    trial(receiver, owner, "interfaces removed", root, objects, "InterfacesRemoved", 0, 0, 1, 1);
    if (dbus_bus_release_name(owner, "org.freedesktop.UDisks2", &error) != DBUS_RELEASE_NAME_REPLY_RELEASED) return 6;
    own_name(other);
    trial(receiver, other, "replacement owner", block, properties, "PropertiesChanged", 0, 1, 0, 1);
    trial(receiver, owner, "previous owner rejected", block, properties, "PropertiesChanged", 0, 0, 0, 1);
    dbus_bus_remove_match(receiver, udisks2_match_interfaces, &error);
    dbus_bus_remove_match(receiver, udisks2_match_properties, &error);
    dbus_bus_add_match(receiver, udisks_match, &error);
    if (dbus_error_is_set(&error)) return 7;
    if (dbus_bus_request_name(other, "org.freedesktop.UDisks", DBUS_NAME_FLAG_DO_NOT_QUEUE, &error) !=
        DBUS_REQUEST_NAME_REPLY_PRIMARY_OWNER) return 8;
    trial(receiver, other, "UDisks1 added", "/org/freedesktop/UDisks", "org.freedesktop.UDisks",
          "DeviceAdded", 0, 1, 0, 1);
    trial(receiver, other, "UDisks1 changed", "/org/freedesktop/UDisks", "org.freedesktop.UDisks",
          "DeviceChanged", 0, 1, 0, 1);
    trial(receiver, other, "UDisks1 removed", "/org/freedesktop/UDisks", "org.freedesktop.UDisks",
          "DeviceRemoved", 0, 0, 1, 1);
    trial(receiver, owner, "foreign UDisks1 sender", "/org/freedesktop/UDisks", "org.freedesktop.UDisks",
          "DeviceChanged", 0, 0, 0, 1);
    for (i = 0; i < sizeof(all) / sizeof(all[0]); ++i)
    {
        dbus_connection_close(all[i]);
        dbus_connection_unref(all[i]);
    }
    return failures != 0;
}
