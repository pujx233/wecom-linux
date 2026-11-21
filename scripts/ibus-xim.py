#!/usr/bin/python3
"""Keep a private ibus-x11 frontend available to this Wine launch on GNOME Wayland."""
import fcntl
import itertools
import os
from pathlib import Path
import signal
import sys
import time


def surviving_client(modifier):
    # explorer /desktop may return while WXWork and its subprocesses keep using its XIM name.
    namespace = b'XDG_RUNTIME_DIR=' + os.fsencode(os.environ['XDG_RUNTIME_DIR'])
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            if Path(os.readlink(proc / 'exe')).name not in ('wine', 'wine64', 'wine-preloader', 'wine64-preloader'):
                continue
            fd = os.pidfd_open(int(proc.name))
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        try:
            environment = (proc / 'environ').read_bytes().split(b'\0')
            if modifier in environment and namespace in environment:
                return fd
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            pass
        os.close(fd)
    return None


def supervise(launcher, ready):
    from gi.repository import Gio, GLib
    try:
        from gi.repository import GLibUnix
        signal_add = GLibUnix.signal_add
    except ImportError:
        signal_add = GLib.unix_signal_add

    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    loop = GLib.MainLoop()
    # Reuse X atom names after exit. Concurrent launches reserve distinct names.
    with open(Path(os.environ['XDG_RUNTIME_DIR']) / 'wecom-ibus-xim.lock', 'a') as slots:
        for slot in itertools.count():
            try:
                fcntl.lockf(slots, fcntl.LOCK_EX | fcntl.LOCK_NB, 1, slot)
                break
            except BlockingIOError:
                continue
        name = f'wecom-ibus-{slot}'
        modifier = b'WINE_X11_XIM_MODIFIERS=@im=' + name.encode()
        server = owner = None
        retry = 0
        delay = 1

        def start():
            nonlocal server, retry, delay
            retry = 0
            if owner and server is None:
                command = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.NONE)
                command.setenv('GDK_BACKEND', 'x11', True)
                try:
                    server = command.spawnv(['/usr/libexec/ibus-x11', '--server-name', name])
                except GLib.Error as error:
                    print(f'WeCom ibus-x11: {error.message}', file=sys.stderr)
                    retry = GLib.timeout_add_seconds(delay, start)
                    delay = min(30, delay * 2)
                else:
                    server.wait_async(None, exited, owner, time.monotonic())
            return GLib.SOURCE_REMOVE

        def exited(child, result, generation, started):
            nonlocal server, retry, delay
            child.wait_finish(result)
            server = None
            if owner == generation:
                if time.monotonic() - started >= 30:
                    delay = 1
                retry = GLib.timeout_add_seconds(delay, start)
                delay = min(30, delay * 2)
            else:
                start()

        def appeared(connection, service, generation):
            nonlocal owner
            owner = generation
            start()

        def vanished(connection, service):
            nonlocal owner, retry, delay
            owner = None
            if retry:
                GLib.source_remove(retry)
                retry = 0
            delay = 1

        def client_exited(fd, condition):
            os.close(fd)
            next_fd = surviving_client(modifier)
            if next_fd is None:
                loop.quit()
            else:
                GLib.io_add_watch(next_fd, GLib.PRIORITY_DEFAULT, GLib.IO_IN, client_exited)
            return GLib.SOURCE_REMOVE

        watch = Gio.bus_watch_name_on_connection(bus, 'org.freedesktop.IBus', Gio.BusNameWatcherFlags.NONE,
                                                 appeared, vanished)
        GLib.io_add_watch(launcher, GLib.PRIORITY_DEFAULT, GLib.IO_IN, client_exited)
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: loop.quit() or GLib.SOURCE_REMOVE)
        ready.write(name + '\n')
        ready.close()
        try:
            loop.run()
        finally:
            Gio.bus_unwatch_name(watch)
            if server:
                server.send_signal(signal.SIGTERM)
                server.wait(None)


def main(argv):
    try:
        launcher = os.pidfd_open(os.getpid())
        read_fd, write_fd = os.pipe()
        pid = os.fork()
    except (AttributeError, OSError) as error:
        print(f'WeCom private XIM unavailable: {error}', file=sys.stderr)
        os.execvp(argv[0], argv)
    if pid == 0:
        os.close(read_fd)
        with os.fdopen(write_fd, 'w') as ready, open(os.devnull, 'r+') as null:
            os.dup2(null.fileno(), 0)
            os.dup2(null.fileno(), 1)
            try:
                supervise(launcher, ready)
            except Exception as error:
                print(f'WeCom private XIM unavailable: {error}', file=sys.stderr)
        return
    os.close(write_fd)
    os.close(launcher)
    with os.fdopen(read_fd) as ready:
        name = ready.readline().strip()
    if name:
        os.environ['WINE_X11_XIM_MODIFIERS'] = '@im=' + name
    os.execvp(argv[0], argv)


if __name__ == '__main__':
    main(sys.argv[1:])
