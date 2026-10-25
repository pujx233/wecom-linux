import ctypes as C
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

root = Path('/work')
work = root / os.environ.get('WECOM_COMPONENT_QA_DIR', 'component-qa')
variant = os.environ['TRAY_VARIANT']
dpi = int(os.environ.get('TRAY_DPI', '192'))
alpha_test = os.environ.get('TRAY_ALPHA') == '1'
checker_test = os.environ.get('TRAY_CHECKER') == '1'
assert variant in ('baseline', 'candidate') and dpi in (96, 192)
runtime = root / 'probe-runtime'
prefix = root / ('qa-prefix-' + variant)
assert (prefix / 'system.reg').is_file()
for relative in ('lib/wine/x86_64-windows/explorer.exe',):
    shutil.copyfile(work / os.environ.get('TRAY_EXPLORER', 'explorer-' + variant + '.exe'), runtime / relative)
for relative in ('drive_c/windows/explorer.exe', 'drive_c/windows/system32/explorer.exe'):
    shutil.copyfile(work / os.environ.get('TRAY_EXPLORER', 'explorer-' + variant + '.exe'), prefix / relative)
if os.environ.get('TRAY_DRIVER'):
    shutil.copyfile(work / os.environ['TRAY_DRIVER'], runtime / 'lib/wine/x86_64-unix/winex11.so')
env = os.environ.copy()
env.update(DISPLAY=':86', WINEPREFIX=str(prefix), WINEDEBUG='-all',
           WINESERVER=str(runtime / 'bin/wineserver'), XMODIFIERS='@im=none')
for name in ('WAYLAND_DISPLAY', 'XAUTHORITY', 'LD_PRELOAD', 'WINEDLLPATH'):
    env.pop(name, None)
log_path = work / ('tray-test-' + variant + '-' + str(dpi) + '.log')
log = log_path.open('wb')
xvfb = subprocess.Popen(['Xvfb', ':86', '-screen', '0', '800x600x24', '-nolisten', 'tcp', '-ac'],
                        stdout=log, stderr=log)
app = None


class Client(C.Structure):
    _fields_ = [('type', C.c_int), ('serial', C.c_ulong), ('send_event', C.c_int), ('display', C.c_void_p),
                ('window', C.c_ulong), ('message_type', C.c_ulong), ('format', C.c_int), ('data', C.c_long * 5)]


class Event(C.Union):
    _fields_ = [('client', Client), ('pad', C.c_long * 24)]


class XImage(C.Structure):
    _fields_ = [(n, C.c_int) for n in ('width', 'height', 'xoffset', 'format')]
    _fields_ += [('data', C.c_void_p)]
    _fields_ += [(n, C.c_int) for n in ('byte_order', 'bitmap_unit', 'bitmap_bit_order', 'bitmap_pad',
                                     'depth', 'bytes_per_line', 'bits_per_pixel')]


try:
    time.sleep(0.4)
    wine = str(runtime / 'bin/wine')
    subprocess.run([wine, 'reg', 'add', r'HKCU\Control Panel\Desktop', '/v', 'LogPixels',
                    '/t', 'REG_DWORD', '/d', str(dpi), '/f'], env=env, stdout=log, stderr=log, check=True)
    subprocess.run([str(runtime / 'bin/wineserver'), '-k'], env=env, check=True)
    subprocess.run([str(runtime / 'bin/wineserver'), '-w'], env=env, check=True)
    x = C.CDLL('libX11.so.6')
    ptr, win, integer = C.c_void_p, C.c_ulong, C.c_int
    signatures = {
        'XOpenDisplay': ([C.c_char_p], ptr), 'XDefaultRootWindow': ([ptr], win),
        'XInternAtom': ([ptr, C.c_char_p, integer], win),
        'XCreateSimpleWindow': ([ptr, win, integer, integer, C.c_uint, C.c_uint, C.c_uint, win, win], win),
        'XSetSelectionOwner': ([ptr, win, win, win], integer),
        'XChangeProperty': ([ptr, win, win, win, integer, integer, ptr, integer], integer),
        'XSelectInput': ([ptr, win, C.c_long], integer), 'XMapWindow': ([ptr, win], integer),
        'XPending': ([ptr], integer), 'XNextEvent': ([ptr, ptr], integer),
        'XReparentWindow': ([ptr, win, win, integer, integer], integer),
        'XResizeWindow': ([ptr, win, C.c_uint, C.c_uint], integer),
        'XSendEvent': ([ptr, win, integer, C.c_long, ptr], integer), 'XSync': ([ptr, integer], integer),
        'XGetImage': ([ptr, win, integer, integer, C.c_uint, C.c_uint, win, integer], C.POINTER(XImage)),
        'XDestroyImage': ([ptr], integer), 'XCloseDisplay': ([ptr], integer),
    }
    for name, (args, result) in signatures.items():
        getattr(x, name).argtypes, getattr(x, name).restype = args, result
    display = x.XOpenDisplay(b':86')
    assert display
    atom = lambda name: x.XInternAtom(display, name.encode(), 0)
    host = x.XCreateSimpleWindow(display, x.XDefaultRootWindow(display), 0, 0, 16, 16, 0, 0, 0)
    x.XSelectInput(display, host, 1 << 17)
    x.XSetSelectionOwner(display, atom('_NET_SYSTEM_TRAY_S0'), host, 0)
    visual = C.c_ulong(0x21)
    x.XChangeProperty(display, host, atom('_NET_SYSTEM_TRAY_VISUAL'), atom('VISUALID'),
                      32, 0, C.byref(visual), 1)
    x.XMapWindow(display, host)
    x.XSync(display, 0)
    argument = '--alpha' if alpha_test else '--checker' if checker_test else None
    command = [wine, str(work / 'tray-icon-test.exe')] + ([argument] if argument else [])
    app = subprocess.Popen(command, env=env, stdout=log, stderr=log)
    icon = None
    event = Event()
    end = time.monotonic() + 12
    while time.monotonic() < end:
        while x.XPending(display):
            x.XNextEvent(display, C.byref(event))
            c = event.client
            if c.type == 33 and c.message_type == atom('_NET_SYSTEM_TRAY_OPCODE') and c.data[1] == 0:
                icon = c.data[2]
                x.XReparentWindow(display, icon, host, 0, 0)
                x.XResizeWindow(display, icon, 16, 16)
                embedded = Event()
                embedded.client = Client(type=33, display=display, window=icon, message_type=atom('_XEMBED'),
                                         format=32, data=(C.c_long * 5)(0, 0, 0, host, 0))
                x.XSendEvent(display, icon, 0, 0, C.byref(embedded))
                x.XMapWindow(display, icon)
                x.XSync(display, 0)
        if icon:
            break
        assert app.poll() is None, 'Tray test exited before docking'
        time.sleep(0.02)
    assert icon, 'No tray docking request'
    time.sleep(1)
    image = x.XGetImage(display, icon, 0, 0, 16, 16, C.c_ulong(-1).value, 2)
    assert image
    info = image.contents
    assert info.bits_per_pixel == 32 and info.byte_order == 0
    pixels = C.string_at(info.data, info.bytes_per_line * info.height)
    red = sum(pixels[n] < 50 and pixels[n + 1] < 50 and pixels[n + 2] > 200
              for n in range(0, len(pixels), 4))
    result = {'variant': variant, 'dpi': dpi, 'native_size': [16, 16], 'red_border_pixels': red,
              'border_retained': red >= 48, 'host_desktop_used': False, 'account_data_used': False}
    pixel = lambda px, py: list(pixels[py * info.bytes_per_line + px * 4:
                                     py * info.bytes_per_line + px * 4 + 4])
    if alpha_test:
        result.update(depth=info.depth, corner_bgra=pixel(0, 0), edge_bgra=pixel(4, 8),
                      center_bgra=pixel(8, 8))
        result['alpha_retained'] = info.depth == 32 and pixel(0, 0) == [0, 0, 0, 0] and \
                                   pixel(4, 8) == [0, 0, 128, 128] and pixel(8, 8) == [0, 0, 255, 255]
    if checker_test:
        result['checker_retained'] = all(pixel(px, py) == ([255, 0, 0, 255] if px % 2 else [0, 0, 255, 255])
                                          for py in range(16) for px in range(16))
        result['first_row_bgra'] = [pixel(px, 0) for px in range(16)]
    suffix = '-alpha' if alpha_test else '-checker' if checker_test else ''
    (work / ('tray-result-' + variant + '-' + str(dpi) + suffix + '.json')).write_text(
        json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
    x.XDestroyImage(image)
    x.XCloseDisplay(display)
finally:
    subprocess.run([str(runtime / 'bin/wineserver'), '-k'], env=env)
    subprocess.run([str(runtime / 'bin/wineserver'), '-w'], env=env)
    if app:
        app.wait(timeout=5)
    xvfb.terminate()
    xvfb.wait(timeout=5)
    log.close()

if not result['alpha_retained' if alpha_test else 'checker_retained' if checker_test else 'border_retained']:
    raise SystemExit(1)
