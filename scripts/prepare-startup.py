#!/usr/bin/env python3
"""Quarantine an abandoned WeCom Boost lock before starting an idle prefix."""
import argparse
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import stat
import tempfile

LOCK_NAME = 'WXWORK-TBS-HELPER-LOCK'
WINE_LOADERS = {'wine', 'wine64', 'wineserver', 'wine-preloader', 'wine64-preloader'}
# Linux comm is limited to 15 bytes. A live prefix has a wineserver; include
# loaders too to cover the interval while that server is being started.
WINE_PROCESS_NAMES = {name[:15] for name in WINE_LOADERS}


def invalid_lock(path):
    """Only the observed 12-byte Boost lock with an unfinished header qualifies."""
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size != 12:
            return False
        with path.open('rb') as stream:
            return int.from_bytes(stream.read(4), 'little') in (0, 1)
    except FileNotFoundError:
        return False


def prefix_is_active(prefix, proc_root):
    for process in proc_root.iterdir():
        if not process.name.isdigit():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            if (process / 'comm').read_text().strip() not in WINE_PROCESS_NAMES:
                continue
            executable = os.readlink(process / 'exe').removesuffix(' (deleted)')
            if Path(executable).name not in WINE_LOADERS:
                continue
            # Read environment only for Wine processes, never unrelated apps.
            environment = (process / 'environ').read_bytes().split(b'\0')
            for entry in environment:
                if entry.startswith(b'WINEPREFIX='):
                    value = os.fsdecode(entry.partition(b'=')[2])
                    if value and Path(value).resolve() == prefix:
                        return True
        except (FileNotFoundError, ProcessLookupError):
            continue  # The process exited during inspection.
        # Permission errors propagate: do not repair when activity is unknown.
    return False


def prepare(prefix, proc_root=Path('/proc')):
    prefix = prefix.resolve(strict=True)
    shared = prefix / 'drive_c/ProgramData/boost_interprocess'
    if not shared.is_dir() or shared.is_symlink():
        return []
    candidates = [directory / LOCK_NAME for directory in shared.iterdir()
                  if directory.is_dir() and not directory.is_symlink()
                  and invalid_lock(directory / LOCK_NAME)]
    if not candidates:
        return []

    with (prefix / 'wecom-compat/.startup-prepare.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        if prefix_is_active(prefix, proc_root):
            print('Startup cache: prefix is active; leaving IPC files unchanged.')
            return []
        moved = []
        for path in candidates:
            if not invalid_lock(path):
                continue
            backup_root = prefix / 'setup-backups'
            backup_root.mkdir(exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-')
            backup = Path(tempfile.mkdtemp(prefix='startup-lock-' + stamp,
                                          dir=backup_root))
            destination = backup / LOCK_NAME
            path.rename(destination)
            moved.append(destination)
            print('Startup cache: backed up unfinished Boost lock to '
                  + str(destination.relative_to(prefix)))
        return moved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', required=True, type=Path)
    args = parser.parse_args()
    try:
        prepare(args.prefix)
    except OSError as error:
        # Keep ordinary launch usable; never guess whether a live lock is stale.
        print('Startup cache: skipped repair (' + str(error) + ').')


if __name__ == '__main__':
    main()
