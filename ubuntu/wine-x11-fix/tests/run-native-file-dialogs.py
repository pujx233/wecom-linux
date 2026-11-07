import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

from gi.repository import Gio, GLib

parser = argparse.ArgumentParser(description="Exercise the native bridge using a private mock D-Bus service.")
parser.add_argument("--runtime", required=True, type=Path)
parser.add_argument("--prefix", type=Path, help="Reuse an owned fixture prefix and its private display")
parser.add_argument("--output", required=True, type=Path)
parser.add_argument("--fixtures", type=Path, help="Precompiled probe32.exe and probe64.exe")
args = parser.parse_args()
if args.prefix is None:
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root / '.wecom-frame-qa').touch()
    (root / '.wecom-native-file-qa').touch()
    (root / 'wine').symlink_to(args.runtime.resolve(strict=True))
    os.environ['WECOM_QA_ROOT'] = str(root)
    sys.path.insert(0, str(Path(__file__).resolve().parent / 'frame-composition'))
    from isolated import desktop

    with desktop(root) as env:
        env.pop('WECOM_QA_PRIVATE_BUS', None)
        command = [sys.executable, str(Path(__file__)), '--runtime', str(args.runtime.resolve()),
                   '--prefix', str(root / 'prefix'), '--output', str(root / 'results')]
        if args.fixtures:
            command += ['--fixtures', str(args.fixtures.resolve())]
        result = subprocess.run(command, env=env)
    raise SystemExit(result.returncode)
if not os.environ.get("WECOM_QA_PRIVATE_BUS"):
    os.execvp(
        "dbus-run-session",
        [
            "dbus-run-session",
            "--",
            "env",
            "WECOM_QA_PRIVATE_BUS=1",
            sys.executable,
            str(Path(__file__).resolve()),
            *sys.argv[1:],
        ],
    )
runtime = args.runtime.resolve(strict=True)
prefix = args.prefix.resolve(strict=True)
root = args.output.resolve()
assert (prefix.parent / ".wecom-native-file-qa").is_file(), "Use a marked, account-free test prefix"
root.mkdir(parents=True, exist_ok=True)
wine = runtime / "bin/wine"
for bits, compiler in ((32, "i686-w64-mingw32-gcc"), (64, "x86_64-w64-mingw32-gcc")):
    if args.fixtures:
        source = args.fixtures.resolve(strict=True) / f"probe{bits}.exe"
        if source != root / source.name:
            shutil.copy2(source, root / source.name)
        continue
    subprocess.run(
        [
            compiler,
            "-Wall",
            "-Werror",
            str(Path(__file__).with_name("native-file-dialog.c")),
            "-o",
            str(root / f"probe{bits}.exe"),
            "-lole32",
            "-lshell32",
            "-luuid",
            "-luser32",
        ],
        check=True,
    )
files = root / "中文目录"
files.mkdir(exist_ok=True)
a = files / "文件 空格'引号$().txt"
b = files / "第二个.LOG"
a.write_text("QA only\n")
b.write_text("QA only\n")
(files / "readonly.txt").write_text("QA only\n")
bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
flags = Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
spoof = Gio.DBusConnection.new_for_address_sync(os.environ["DBUS_SESSION_BUS_ADDRESS"], flags, None, None)
portal = "org.freedesktop.portal.Desktop"
xml = """<node><interface name="org.freedesktop.portal.FileChooser">
<method name="OpenFile"><arg type="s" direction="in"/><arg type="s" direction="in"/>
<arg type="a{sv}" direction="in"/><arg type="o" direction="out"/></method>
<method name="SaveFile"><arg type="s" direction="in"/><arg type="s" direction="in"/>
<arg type="a{sv}" direction="in"/><arg type="o" direction="out"/></method></interface></node>"""
request_xml = """<node><interface name="org.freedesktop.portal.Request"><method name="Close"/></interface></node>"""
manager_xml = """<node><interface name="org.freedesktop.FileManager1"><method name="ShowItems">
<arg type="as" direction="in"/><arg type="s" direction="in"/></method></interface></node>"""
node = Gio.DBusNodeInfo.new_for_xml(xml)
request_node = Gio.DBusNodeInfo.new_for_xml(request_xml)
manager_node = Gio.DBusNodeInfo.new_for_xml(manager_xml)
state = {}
calls = []
close_calls = []
manager_calls = []
objects = []


def name_call(method, name):
    return bus.call_sync(
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus",
        method,
        GLib.Variant("(su)", (name, 0)) if method == "RequestName" else GLib.Variant("(s)", (name,)),
        None,
        Gio.DBusCallFlags.NONE,
        -1,
        None,
    )


def release_portal():
    name_call("ReleaseName", portal)
    return False


def response(connection, sender, path, code, result, wrong=False):
    value = GLib.Variant("(sa{sv})", ("invalid", result)) if wrong else GLib.Variant("(ua{sv})", (code, result))
    connection.emit_signal(sender, path, "org.freedesktop.portal.Request", "Response", value)
    return False


def close(conn, sender, path, iface, method, args, invocation):
    close_calls.append({"bits": state["bits"], "case": state["case"], "path": path})
    invocation.return_value(GLib.Variant("()", ()))


def method(conn, sender, path, iface, method, args, invocation):
    parent, title, options = args.unpack()
    state["requests"] += 1
    mode = state["case"]
    calls.append(
        {"bits": state["bits"], "case": mode, "method": method, "parent": parent, "title": title, "options": options}
    )
    if mode in ("slow-close", "provider-exit-before-reply"):
        call = calls[-1]
        call["replied"] = False

        def delayed_reply():
            call["replied"] = True
            invocation.return_value(GLib.Variant("(o)", ("/org/freedesktop/portal/desktop/request/slow",)))
            return False

        if mode == "provider-exit-before-reply":
            GLib.timeout_add(180, release_portal)
        GLib.timeout_add(5000, delayed_reply)
        return
    if mode == "unavailable":
        invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", "No file chooser")
        return
    path = "/org/freedesktop/portal/desktop/request/" + sender[1:].replace(".", "_") + "/wine"
    objects.append(bus.register_object(path, request_node.interfaces[0], close, None, None))
    if mode != "early-response":
        invocation.return_value(GLib.Variant("(o)", (path,)))
    if mode in ("close", "quit", "custom"):
        return
    if mode == "provider-exit":
        GLib.timeout_add(180, release_portal)
        return
    if mode == "cancel" or (mode == "reuse" and state["requests"] == 2):
        code = 1
        result = {}
    else:
        code = 0
        selected = (
            [files]
            if mode == "folder"
            else [files / "readonly.txt"]
            if mode == "save-readonly"
            else [files / "新报告"]
            if mode in ("save", "save-filter", "save-filter-no-default", "save-veto")
            else [a]
            if mode in ("veto", "reuse", "reuse-custom")
            else [a, b]
        )
        uris = [p.as_uri() for p in selected]
        if mode == "invalid-uri":
            uris = ["file://untrusted.invalid/test.txt"]
        if mode == "missing-file":
            uris = [(files / "不存在.txt").as_uri()]
        current = (
            GLib.Variant("(suu)", ("invalid", 1, 2))
            if mode == "invalid-filter"
            else GLib.Variant("(sa(us))", options["filters"][1 if mode.startswith("save-filter") else 0])
        )
        result = {"uris": GLib.Variant("as", uris), "current_filter": current}
    if mode == "spoof":
        GLib.timeout_add(50, response, spoof, sender, path, 1, {})
    if mode == "early-response":
        response(bus, sender, path, code, result)
        invocation.return_value(GLib.Variant("(o)", (path,)))
    else:
        GLib.timeout_add(180, response, bus, sender, path, code, result, mode == "invalid-response")


def manager(conn, sender, path, iface, method, args, invocation):
    manager_calls.append({"bits": state["bits"], "case": state["case"], "args": args.unpack()})
    if state["case"] == "manager-fallback":
        invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", "No selection support")
    else:
        invocation.return_value(GLib.Variant("()", ()))


bus.register_object("/org/freedesktop/portal/desktop", node.interfaces[0], method, None, None)
bus.register_object("/org/freedesktop/FileManager1", manager_node.interfaces[0], manager, None, None)
name_call("RequestName", portal)
name_call("RequestName", "org.freedesktop.FileManager1")
loop = GLib.MainLoop()
threading.Thread(target=loop.run, daemon=True).start()
commands = root / "commands"
commands.mkdir(exist_ok=True)
xdg = commands / "xdg-open"
xdg.write_text("""#!/usr/bin/python3
import os,json,sys
with open(os.environ['WECOM_QA_OPEN_LOG'],'a') as out:out.write(json.dumps(sys.argv[1:],ensure_ascii=False)+'\\n')
sys.exit(int(os.environ.get('WECOM_QA_OPEN_STATUS','0')))
""")
xdg.chmod(0o755)
open_log = root / "xdg-open-review.jsonl"
open_log.write_text("")
env = os.environ | {
    "DISPLAY": os.environ["DISPLAY"],
    "LANG": "zh_CN.UTF-8",
    "LC_CTYPE": "zh_CN.UTF-8",
    "LC_MESSAGES": "zh_CN.UTF-8",
    "WINEPREFIX": str(prefix),
    "WINESERVER": str(runtime / "bin/wineserver"),
    "WINEDEBUG": "-all",
    "WINE_NATIVE_FILE_DIALOGS": "1",
    "WINE_NATIVE_FILE_MANAGER": "1",
    "WECOM_QA_OPEN_LOG": str(open_log),
    "PATH": str(commands) + ":" + os.environ["PATH"],
    "WECOM_QA_FILES": "Z:" + str(files).replace("/", "\\"),
}
results = []
for bits in (32, 64):
    modes = (
        "open",
        "cancel",
        "folder",
        "veto",
        "save",
        "save-filter",
        "save-filter-no-default",
        "save-veto",
        "save-readonly",
        "save-unsupported",
        "close",
        "slow-close",
        "custom",
        "reuse",
        "reuse-custom",
        "early-response",
        "provider-exit-before-reply",
        "quit",
        "invalid-uri",
        "invalid-response",
        "invalid-filter",
        "missing-file",
        "provider-exit",
        "spoof",
        "unavailable",
        "manager-dir",
        "manager-one",
        "manager-two",
        "manager-explorer",
        "manager-fallback",
    )
    if os.environ.get("WECOM_QA_CASES"):
        modes = tuple(os.environ["WECOM_QA_CASES"].split(","))
    for mode in modes:
        name_call("RequestName", portal)
        state.update(bits=bits, case=mode, requests=0)
        before = len(calls)
        manager_before = len(manager_calls)
        open_before = len(open_log.read_text().splitlines())
        r = subprocess.run(
            [str(wine), str(root / f"probe{bits}.exe"), mode], env=env, capture_output=True, text=True, timeout=30
        )
        (root / f"review-{bits}-{mode}.log").write_text(r.stdout + r.stderr)
        result = next((json.loads(s) for s in r.stdout.splitlines() if s.startswith('{"hr"')), None)
        assert r.returncode == 0 and result, (bits, mode, r.returncode, r.stdout, r.stderr)
        if mode.startswith("manager-"):
            assert result["hr"] == 0, result
            if mode != "manager-dir":
                deadline = time.monotonic() + 5
                while len(manager_calls) == manager_before and time.monotonic() < deadline:
                    time.sleep(0.02)
                assert len(manager_calls) == manager_before + 1, (bits, mode, manager_calls)
                actual = manager_calls[-1]["args"][0]
                assert (
                    actual == [a.as_uri()]
                    if mode in ("manager-one", "manager-explorer")
                    else actual == [a.as_uri(), b.as_uri()]
                ), actual
            if mode in ("manager-dir", "manager-fallback"):
                deadline = time.monotonic() + 5
                while len(open_log.read_text().splitlines()) == open_before and time.monotonic() < deadline:
                    time.sleep(0.02)
                assert len(open_log.read_text().splitlines()) == open_before + 1, (bits, mode)
                assert json.loads(open_log.read_text().splitlines()[-1]) == [str(files)]
        else:
            assert result["owner_enabled"] and result["callbacks_valid"], result
            assert not result["stale_result"], result
            if mode in ("close", "slow-close", "custom", "reuse-custom", "unavailable", "save-unsupported"):
                assert result["hr"] == 0x80004004 and result["ticks"] >= 10, result
            elif mode in ("cancel", "reuse", "quit"):
                assert result["hr"] == 0x800704C7 and not result["paths"], result
                if mode == "reuse":
                    assert result["accepted"] == 1 and len(calls) - before == 2, result
                if mode == "quit":
                    assert result["quit_code"] == 37, result
            elif mode == "save-readonly":
                assert result["hr"] == 0x80070005 and not result["paths"], result
            elif mode in (
                "invalid-uri",
                "invalid-response",
                "missing-file",
                "provider-exit",
                "provider-exit-before-reply",
            ):
                assert result["hr"] != 0 and not result["paths"] and len(calls) - before == 1, result
            else:
                assert result["hr"] == 0 and result["paths"] and (mode == "early-response" or result["ticks"] > 0), (
                    result
                )
                assert result["accepted"] == (2 if mode in ("veto", "save-veto") else 1), result
                assert result["type_changed"] == (1 if mode == "invalid-filter" else 2), result
                if mode.startswith("save-filter"):
                    assert result["paths"][0].endswith("新报告.log"), result
                if mode == "save-veto":
                    assert calls[-1]["options"]["current_name"] == "新报告.txt", calls[-1]
            if mode in ("custom", "save-unsupported"):
                assert len(calls) == before
            if mode in ("slow-close", "provider-exit-before-reply"):
                assert not calls[-1]["replied"], calls[-1]
        results.append({"bits": bits, "mode": mode, **result, "portal_calls": len(calls) - before})
        print(bits, mode, "passed", flush=True)
(root / "review-result.json").write_text(
    json.dumps(
        {
            "passed": True,
            "cases": results,
            "calls": calls,
            "close_calls": close_calls,
            "manager_calls": manager_calls,
            "runtime_components": {
                str(p.relative_to(runtime)): hashlib.sha256(p.read_bytes()).hexdigest()
                for arch in ("i386-windows", "x86_64-windows")
                for p in (
                    runtime / f"lib/wine/{arch}/comdlg32.dll",
                    runtime / f"lib/wine/{arch}/shell32.dll",
                    runtime / f"lib/wine/{arch}/explorer.exe",
                )
            },
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n"
)
stopped = subprocess.run([str(runtime / "bin/wineserver"), "-k"], env=env)
assert stopped.returncode in (0, 1)
loop.quit()
