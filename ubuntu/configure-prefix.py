#!/usr/bin/env python3
"""Apply desktop DPI and packaged fonts to an idle WeCom prefix."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import struct
import sys


def xsettings_dpi(data):
    if len(data) < 12 or data[0] not in (0, 1):
        return None
    order = '<' if data[0] == 0 else '>'
    offset = 12
    try:
        for _ in range(struct.unpack_from(order + 'I', data, 8)[0]):
            kind, length = struct.unpack_from(order + 'BxH', data, offset)
            offset += 4
            name = data[offset:offset + length]
            offset = (offset + length + 3) & ~3
            offset += 4  # last-change serial
            if kind == 0:
                value = struct.unpack_from(order + 'i', data, offset)[0]
                offset += 4
                if name == b'Xft/DPI' and value > 0:
                    return round(value / 1024)
            elif kind == 1:
                length = struct.unpack_from(order + 'I', data, offset)[0]
                offset = (offset + 4 + length + 3) & ~3
            elif kind == 2:
                offset += 8
            else:
                return None
    except struct.error:
        return None
    return None


def x11_dpi():
    x11 = ctypes.CDLL('libX11.so.6')
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    x11.XDefaultScreen.argtypes = [ctypes.c_void_p]
    x11.XDefaultScreen.restype = ctypes.c_int
    x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XGetSelectionOwner.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XGetSelectionOwner.restype = ctypes.c_ulong
    x11.XGetWindowProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long,
                                     ctypes.c_long, ctypes.c_int, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                                     ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_ulong),
                                     ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_void_p)]
    x11.XFree.argtypes = [ctypes.c_void_p]
    x11.XResourceManagerString.argtypes = [ctypes.c_void_p]
    x11.XResourceManagerString.restype = ctypes.c_char_p
    display = x11.XOpenDisplay(None)
    if not display:
        raise RuntimeError('Cannot detect desktop DPI without an X11 display; set WECOM_DPI explicitly')
    try:
        atom = x11.XInternAtom(display, f'_XSETTINGS_S{x11.XDefaultScreen(display)}'.encode(), False)
        owner = x11.XGetSelectionOwner(display, atom)
        if owner:
            atom = x11.XInternAtom(display, b'_XSETTINGS_SETTINGS', False)
            actual, format_ = ctypes.c_ulong(), ctypes.c_int()
            count, after, data = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p()
            status = x11.XGetWindowProperty(display, owner, atom, 0, 65536, False, 0, ctypes.byref(actual),
                                            ctypes.byref(format_), ctypes.byref(count), ctypes.byref(after),
                                            ctypes.byref(data))
            try:
                if status == 0 and format_.value == 8 and not after.value and data:
                    dpi = xsettings_dpi(ctypes.string_at(data, count.value))
                    if dpi:
                        return dpi
            finally:
                if data:
                    x11.XFree(data)
        resources = (x11.XResourceManagerString(display) or b'').decode('latin-1')
        match = re.search(r'^Xft\.dpi:\s*([\d.]+)\s*$', resources, re.MULTILINE)
        return round(float(match[1])) if match else None
    finally:
        x11.XCloseDisplay(display)


def desktop_dpi():
    dpi = x11_dpi()
    if dpi:
        return dpi
    if os.environ.get('NIRI_SOCKET'):
        result = subprocess.run(['niri', 'msg', '--json', 'focused-output'], capture_output=True,
                                text=True, check=True, timeout=3)
        return round(96 * json.loads(result.stdout)['logical']['scale'])
    if 'KDE' in os.environ.get('XDG_CURRENT_DESKTOP', '').split(':') and shutil.which('kscreen-doctor'):
        result = subprocess.run(['kscreen-doctor', '-j'], capture_output=True, text=True, check=True, timeout=3)
        outputs = [output for output in json.loads(result.stdout)['outputs'] if output['enabled']]
        primary = next((output for output in outputs if output.get('priority') == 1), outputs[0])
        return round(96 * primary['scale'])
    try:
        from gi.repository import Gio, GLib
    except ImportError:
        pass
    else:
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            state = bus.call_sync('org.gnome.Mutter.DisplayConfig', '/org/gnome/Mutter/DisplayConfig',
                                  'org.gnome.Mutter.DisplayConfig', 'GetCurrentState', None, None,
                                  Gio.DBusCallFlags.NONE, 3000, None).unpack()
            logical = next(monitor for monitor in state[2] if monitor[4])
            return round(96 * logical[2])
        except GLib.Error:
            pass  # Other desktops need not expose Mutter's display service.
    return 96


def registry_dpi(prefix, key):
    text = (prefix / 'user.reg').read_text()
    section = '[' + key.replace('\\', '\\\\') + ']'
    if section not in text:
        return None
    values = text.split(section, 1)[1].split('\n[', 1)[0]
    match = re.search(r'^"LogPixels"=dword:([0-9a-fA-F]+)$', values, re.MULTILINE)
    return int(match[1], 16) if match else None


def configure(root, prefix):
    wine = root / 'wine/bin/wine'
    server = root / 'wine/bin/wineserver'
    env = os.environ | {'WINEPREFIX': str(prefix), 'WINESERVER': str(server), 'WINEDEBUG': '-all'}
    idle = subprocess.run(['timeout', '3', str(server), '-w'], env=env)
    if idle.returncode == 124:
        return  # An already running client keeps its current configuration.
    idle.check_returncode()
    stamp = prefix / '.wecom-display-fonts.json'
    previous = json.loads(stamp.read_text()) if stamp.exists() else {}
    current = registry_dpi(prefix, r'Control Panel\Desktop') or None
    override = os.environ.get('WECOM_DPI')
    manual = current is not None and not override and (previous.get('manual', False) or
                                                     current != previous.get('dpi', 192))
    dpi = current if manual else int(override) if override and override != 'auto' else desktop_dpi()
    if not isinstance(dpi, int) or not 48 <= dpi <= 768:
        raise ValueError('WECOM_DPI must be an integer between 48 and 768, or auto')
    configs = root / 'template/wecom-compat/configs'
    font_configs = [configs / name for name in ('fonts-install.reg', 'fonts-replacements.reg')]
    font_revision = hashlib.sha256((root / 'application-version').read_bytes() +
                                  b''.join(path.read_bytes() for path in font_configs)).hexdigest()
    fonts = root / 'template/drive_c/windows/Fonts'
    runtime_revision = (root / 'application-version').read_text().strip()
    modules = ['comdlg32.dll', 'shell32.dll']
    update_runtime = previous.get('runtime') != runtime_revision
    if update_runtime:
        for architecture, directory in (('i386-windows', 'syswow64'), ('x86_64-windows', 'system32')):
            for name in modules:
                destination = prefix / 'drive_c/windows' / directory / name
                temporary = destination.with_suffix('.wecom-new')
                shutil.copy2(root / 'wine/lib/wine' / architecture / name, temporary)
                os.replace(temporary, destination)
        for architecture, directory in (('x86_64-windows', 'drive_c/windows'),
                                        ('x86_64-windows', 'drive_c/windows/system32'),
                                        ('i386-windows', 'drive_c/windows/syswow64')):
            destination = prefix / directory / 'explorer.exe'
            temporary = destination.with_suffix('.wecom-new')
            shutil.copy2(root / 'wine/lib/wine' / architecture / 'explorer.exe', temporary)
            os.replace(temporary, destination)
    destination = prefix / 'drive_c/windows/Fonts'
    update_fonts = previous.get('fonts') != font_revision or any(not (destination / path.name).is_file()
                                                               for path in fonts.iterdir() if path.is_file())
    keys = (r'Control Panel\Desktop', r'Software\Wine\Fonts')
    update_dpi = any(registry_dpi(prefix, key) != dpi for key in keys)
    if update_fonts or update_dpi:
        subprocess.run(['python3', str(root / 'template/wecom-compat/scripts/prepare-startup.py'),
                        '--prefix', str(prefix)], check=True)
        try:
            if update_fonts:
                destination.mkdir(exist_ok=True)
                for path in fonts.iterdir():
                    if path.is_file():
                        temporary = destination / (path.name + '.wecom-new')
                        shutil.copy2(path, temporary)
                        os.replace(temporary, destination / path.name)
                for path in font_configs:
                    subprocess.run([str(wine), 'reg', 'import', str(path)], env=env, check=True)
            if update_dpi:
                for key in keys:
                    subprocess.run([str(wine), 'reg', 'add', 'HKCU\\' + key, '/v', 'LogPixels',
                                    '/t', 'REG_DWORD', '/d', str(dpi), '/f'], env=env, check=True)
        finally:
            result = subprocess.run([str(server), '-k'], env=env)
            if result.returncode not in (0, 1):
                result.check_returncode()
            subprocess.run([str(server), '-w'], env=env, check=True)
    temporary = stamp.with_suffix('.new')
    temporary.write_text(json.dumps({'dpi': dpi, 'manual': manual, 'fonts': font_revision,
                                    'runtime': runtime_revision}) + '\n')
    os.replace(temporary, stamp)
    print(f'WeCom prefix: {dpi} DPI ({"manual" if manual or override and override != "auto" else "desktop"}), '
          f'fonts {"updated" if update_fonts else "current"}')


if __name__ == '__main__':
    configure(Path(sys.argv[1]).resolve(strict=True), Path(sys.argv[2]).resolve(strict=True))
