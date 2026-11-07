#!/usr/bin/env python3
"""Wait for an idle prefix, stopping Wine's desktop only after application clients have exited."""
import os
from pathlib import Path
import subprocess
import sys

LOADERS = {'wine', 'wine64', 'wine-preloader', 'wine64-preloader', 'wineserver'}
SERVICES = {'explorer.exe', 'services.exe', 'winedevice.exe', 'plugplay.exe',
            'svchost.exe', 'rpcss.exe', 'lsass.exe', 'conhost.exe', 'titlebar-managed.exe'}


def application_running(prefix, proc=Path('/proc')):
    for process in proc.iterdir():
        if not process.name.isdigit():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            loader = Path(os.readlink(process / 'exe').removesuffix(' (deleted)')).name
            if loader not in LOADERS or loader == 'wineserver':
                continue
            environment = (process / 'environ').read_bytes().split(b'\0')
            value = next((entry.partition(b'=')[2] for entry in environment if entry.startswith(b'WINEPREFIX=')), None)
            if not value or Path(os.fsdecode(value)).resolve() != prefix:
                continue
            argv = [os.fsdecode(s) for s in (process / 'cmdline').read_bytes().split(b'\0') if s]
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        if not argv:
            continue
        command = argv[2] if len(argv) > 2 and argv[:2] == ['start.exe', '/exec'] else argv[0]
        image = command.replace('\\', '/').rsplit('/', 1)[-1].strip('"').lower()
        if image in SERVICES:
            continue
        return True
    return False


def wait_idle(prefix, server):
    env = os.environ | {'WINEPREFIX': str(prefix)}
    result = subprocess.run(['timeout', '3', str(server), '-w'], env=env)
    if result.returncode != 124:
        return result.returncode
    if application_running(prefix):
        return 124
    result = subprocess.run([str(server), '-k'], env=env)
    if result.returncode not in (0, 1):
        return result.returncode
    return subprocess.run([str(server), '-w'], env=env).returncode


if __name__ == '__main__':
    raise SystemExit(wait_idle(Path(sys.argv[1]).resolve(strict=True), Path(sys.argv[2]).resolve(strict=True)))
