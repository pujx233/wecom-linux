#!/usr/bin/env python3
"""Check CEF image sharing, relocations, isolation and lifetime in account-free Wine prefixes."""
import argparse
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import struct
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent


def fingerprint(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_json(process):
    with selectors.DefaultSelector() as ready:
        ready.register(process.stdout, selectors.EVENT_READ)
        assert ready.select(30), 'DLL fixture timed out'
        line = process.stdout.readline()
    assert line, f'DLL fixture exited early: {process.poll()}'
    value = json.loads(line)
    assert 'error' not in value, value
    return value


def image_stats(pid, base, size):
    result, active = {}, False
    for line in Path(f'/proc/{pid}/smaps').read_text().splitlines():
        parts = line.split()
        if parts and '-' in parts[0] and len(parts) >= 5:
            start, end = [int(value, 16) for value in parts[0].split('-')]
            active = start < base + size and end > base
        elif active and parts[-1:] == ['kB']:
            key = parts[0].rstrip(':')
            result[key] = result.get(key, 0) + int(parts[1])
    return result


def find_pid(key, value, image=None):
    expected = f'{key}={value}'.encode()
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            if expected not in (process / 'environ').read_bytes().split(b'\0'):
                continue
            if image and not image_stats(process.name, image['base'], image['size']).get('Rss'):
                continue
            if not image and (process / 'comm').read_text().strip() != 'wineserver':
                continue
            return int(process.name)
        except (OSError, ValueError):
            continue
    raise AssertionError(f'Cannot find fixture process for {key}')


class Prefix:
    def __init__(self, runtime, root, enabled, preload=None):
        self.runtime, self.root = runtime, root
        print('START ' + root.name, flush=True)
        root.mkdir()
        self.prefix = root / 'prefix'
        self.clients = []
        self.log = (root / 'wine.log').open('wb')
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith('WINE') and key not in
                    ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'LD_PRELOAD', 'LD_LIBRARY_PATH')}
        self.env.update(WINEPREFIX=str(self.prefix), WINESERVER=str(runtime / 'bin/wineserver'),
                        WINEDEBUG='-all', WECOM_SHARED_CEF_IMAGE=str(int(enabled)),
                        WINEDLLOVERRIDES='winewayland.drv,mscoree,mshtml,winemenubuilder=',
                        DBUS_SESSION_BUS_ADDRESS='unix:path=/nonexistent-cef-cache-qa',
                        XDG_CACHE_HOME=str(root / 'cache'), XDG_CONFIG_HOME=str(root / 'config'))
        if not enabled:
            # A newer baseline can also share libcef.dll through the generic PE image cache.
            self.env['WECOM_SHARED_PE_IMAGE'] = '0'
        if preload:
            self.env['LD_PRELOAD'] = str(preload)
        subprocess.run([str(runtime / 'bin/wine'), 'wineboot.exe', '-i'], env=self.env,
                       stdout=self.log, stderr=self.log, check=True, timeout=60)

    def start(self, dll, marker=None, reserve=None):
        tag = f'{self.root.name}:{len(self.clients)}'
        command = [str(self.runtime / 'bin/wine'), str(dll.parent / 'loader.exe'), str(dll)]
        if reserve:
            command += [hex(reserve['base']), hex(reserve['size'])]
        process = subprocess.Popen(command, env=self.env | {'WECOM_CEF_QA_SAMPLE': tag},
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, text=True)
        client = {'process': process}
        self.clients.append(client)
        client['info'] = info = read_json(process)
        client['pid'] = find_pid('WECOM_CEF_QA_SAMPLE', tag, info)
        if marker is not None:
            assert info['marker'] == marker and info['count'] == 1, info
        return client

    def send(self, client, command):
        client['process'].stdin.write(command)
        client['process'].stdin.flush()
        return read_json(client['process'])

    def caches(self, check_seals=False):
        pid = find_pid('WINEPREFIX', str(self.prefix))
        result, seen = [], set()
        for path in Path(f'/proc/{pid}/fd').iterdir():
            try:
                if 'memfd:wine-cef-image' not in os.readlink(path):
                    continue
                with path.open('r+b', buffering=0) as handle:
                    fd = handle.fileno()
                    st = os.fstat(fd)
                    key = (st.st_dev, st.st_ino)
                    if key in seen:
                        continue
                    seen.add(key)
                    magic, base, size = struct.unpack('<8sQQ', os.pread(fd, 24, 0))
                    seals = fcntl.fcntl(fd, fcntl.F_GET_SEALS)
                    assert magic == b'WineCEF2' and st.st_size == size, (magic, size)
                    assert seals & 15 == 15, seals
                    if check_seals:
                        for operation in [lambda: os.pwrite(fd, b'x', 0),
                                          lambda: os.ftruncate(fd, size + 4096),
                                          lambda: os.ftruncate(fd, size - 4096)]:
                            try:
                                operation()
                            except OSError as error:
                                assert error.errno == errno.EPERM, error
                            else:
                                raise AssertionError('An immutable cache accepted a modification')
                    result.append({'base': base, 'size': size, 'inode': st.st_ino, 'seals': seals})
            except FileNotFoundError:
                continue
        return result

    def wait_caches(self, count):
        deadline = time.monotonic() + 5
        while True:
            found = self.caches()
            if len(found) == count:
                return found
            assert time.monotonic() < deadline, (count, found)
            time.sleep(.02)

    def stop(self, client):
        process = client['process']
        if process.poll() is None:
            process.communicate('q', timeout=10)

    def close(self):
        try:
            for client in self.clients:
                self.stop(client)
        finally:
            subprocess.run([str(self.runtime / 'bin/wineserver'), '-k'], env=self.env,
                           stdout=self.log, stderr=self.log)
            subprocess.run([str(self.runtime / 'bin/wineserver'), '-w'], env=self.env,
                           stdout=self.log, stderr=self.log, timeout=15)
            self.log.close()


def cow_test(prefix, clients):
    original = clients[0]['info']['probe']
    assert prefix.send(clients[0], 'w')['probe'] == original ^ 1
    for client in clients[1:]:
        assert prefix.send(client, 'r')['probe'] == client['info']['probe']
    assert prefix.send(clients[0], 'w')['probe'] == original


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--baseline-runtime', type=Path)
    parser.add_argument('--cef-dir', type=Path, required=True, help='Vendor CEF folder; no account directory is read')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--inside', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    runtime, cef_dir, output = args.runtime.resolve(), args.cef_dir.resolve(), args.output.resolve()
    if not args.inside:
        output.mkdir(mode=0o700, parents=True, exist_ok=False)
        command = ['bwrap', '--unshare-net', '--unshare-ipc', '--ro-bind', '/', '/', '--bind', str(output), str(output),
                   '--tmpfs', '/tmp', '--tmpfs', f'/run/user/{os.getuid()}', '--dev', '/dev', '--proc', '/proc', '--',
                   sys.executable, str(HERE / 'run.py'), '--inside', '--runtime', str(runtime),
                   '--cef-dir', str(cef_dir), '--output', str(output)]
        if args.baseline_runtime:
            command += ['--baseline-runtime', str(args.baseline_runtime.resolve())]
        return subprocess.call(command)
    report = {'passed': False, 'account_used': False, 'host_desktop_used': False, 'network_isolated': True, 'cases': {}}
    fixture = output / 'loader.exe'
    subprocess.run(['i686-w64-mingw32-gcc', '-O2', '-Wall', '-Wextra', '-municode', str(HERE / 'loader.c'),
                    '-o', str(fixture)], check=True)
    shim = output / 'no-cache.so'
    subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', str(HERE / 'no-cache.c'),
                    '-o', str(shim), '-ldl'], check=True)
    images = {}
    for label, marker in [('a', 101), ('b', 202), ('shared', 303)]:
        directory = output / label
        directory.mkdir()
        images[label] = dll = directory / 'libcef.dll'
        subprocess.run(['i686-w64-mingw32-gcc', '-shared', '-O2', '-Wall', '-Wextra',
                        '-DIMAGE_MARKER=' + str(marker), str(HERE / 'image.c'), '-o', str(dll),
                        '-Wl,--dynamicbase,--nxcompat,--image-base,0x10000000'], check=True)
        shutil.copy2(fixture, directory / 'loader.exe')
        if label == 'shared':
            data = bytearray(dll.read_bytes())
            pe = struct.unpack_from('<I', data, 60)[0]
            table = pe + 24 + struct.unpack_from('<H', data, pe + 20)[0]
            for index in range(struct.unpack_from('<H', data, pe + 6)[0]):
                header = table + index * 40
                if data[header:header + 8].rstrip(b'\0') == b'.shared':
                    flags = struct.unpack_from('<I', data, header + 36)[0]
                    struct.pack_into('<I', data, header + 36, flags | 0x10000000)
                    break
            else:
                raise AssertionError('The shared-section fixture has no .shared section')
            dll.write_bytes(data)
    real = output / 'cef'
    real.mkdir()
    for name in ['libcef.dll', 'chrome_elf.dll']:
        shutil.copy2(cef_dir / name, real / name)
    shutil.copy2(fixture, real / 'loader.exe')
    high = output / 'high-relocation'
    high.mkdir()
    images['high'] = high / 'libcef.dll'
    data = bytearray(images['a'].read_bytes())
    pe = struct.unpack_from('<I', data, 60)[0]
    table = pe + 24 + struct.unpack_from('<H', data, pe + 20)[0]
    sections = []
    for index in range(struct.unpack_from('<H', data, pe + 6)[0]):
        header = table + index * 40
        sections.append(struct.unpack_from('<IIII', data, header + 8))
    reloc_rva, reloc_size = struct.unpack_from('<II', data, pe + 24 + 96 + 5 * 8)
    reloc_offset = next(raw + reloc_rva - rva for size, rva, raw_size, raw in sections
                        if rva <= reloc_rva < rva + raw_size)
    position = reloc_offset
    replaced = False
    while position < reloc_offset + reloc_size and not replaced:
        page, block_size = struct.unpack_from('<II', data, position)
        for offset in range(position + 8, position + block_size, 2):
            entry = struct.unpack_from('<H', data, offset)[0]
            if page == 0x1000 and entry >> 12 == 3 and entry & 0xfff <= 0xffd:
                # Image bases are 64K aligned: HIGH on the upper word is equivalent to HIGHLOW here.
                struct.pack_into('<H', data, offset, 0x1000 | ((entry & 0xfff) + 2))
                replaced = True
                break
        position += block_size
    assert replaced, 'No text relocation found for the unsupported-cache relocation test'
    images['high'].write_bytes(data)
    shutil.copy2(fixture, high / 'loader.exe')
    source_before = {name: fingerprint(cef_dir / name) for name in ['libcef.dll', 'chrome_elf.dll']}
    report['source_sha256'] = source_before
    prefix = Prefix(runtime, output / 'enabled', True)
    try:
        clients = [prefix.start(images['a'], 101) for _ in range(6)]
        assert len(prefix.caches(check_seals=True)) == 1
        cow_test(prefix, clients)
        conflict = prefix.start(images['a'], 101, reserve=clients[0]['info'])
        assert conflict['info']['base'] != clients[0]['info']['base']
        clients.append(conflict)
        other = prefix.start(images['b'], 202)
        assert len(prefix.caches(check_seals=True)) == 2
        report['cases']['concurrency_relocation_identity_and_cow'] = True
        for client in clients + [other]:
            assert prefix.send(client, 'u')['unloaded']
        prefix.wait_caches(0)
        report['cases']['last_unload_releases_cache'] = True
        clients[0]['info'] = prefix.send(clients[0], 'l')
        assert clients[0]['info']['marker'] == 101 and clients[0]['info']['count'] == 1
        prefix.wait_caches(1)
        for client in clients + [other]:
            prefix.stop(client)
        prefix.wait_caches(0)
        shared = [prefix.start(images['shared'], 303) for _ in range(3)]
        values = [prefix.send(client, 's')['shared'] for client in shared]
        assert values == [1, 2, 3] and not prefix.caches(), values
        for client in shared:
            prefix.stop(client)
        report['cases']['ordinary_shared_writable_sections'] = True
        unusual = prefix.start(images['high'], 101)
        assert not prefix.caches()
        prefix.stop(unusual)
        report['cases']['unsupported_cache_relocation_uses_native_loader'] = True
        clients = [prefix.start(real / 'libcef.dll') for _ in range(3)]
        for client in clients:
            assert client['info']['version'] == 107 and len(client['info']['api_hash']) == 40
        assert len({client['info']['api_hash'] for client in clients}) == 1
        cow_test(prefix, clients)
        metrics = [image_stats(client['pid'], client['info']['base'], client['info']['size']) for client in clients]
        report['candidate_image_pss_mib'] = round(sum(row['Pss'] for row in metrics) / 1024, 2)
        report['candidate_caches'] = prefix.caches(check_seals=True)
        os.kill(clients[0]['pid'], signal.SIGKILL)
        assert prefix.send(clients[1], 'r')['probe'] == clients[1]['info']['probe']
        for client in clients:
            prefix.stop(client)
        prefix.wait_caches(0)
        report['cases']['cef_initialization_exports_and_client_crash'] = True
    finally:
        prefix.close()
    for label, enabled, preload in [('disabled', False, None), ('allocation-failure', True, shim)]:
        prefix = Prefix(runtime, output / label, enabled, preload)
        try:
            client = prefix.start(images['a'], 101)
            assert not prefix.caches(), label
            report['cases'][label] = True
        finally:
            prefix.close()
    if args.baseline_runtime:
        prefix = Prefix(args.baseline_runtime.resolve(), output / 'baseline', False)
        try:
            clients = [prefix.start(real / 'libcef.dll') for _ in range(3)]
            metrics = [image_stats(client['pid'], client['info']['base'], client['info']['size']) for client in clients]
            report['baseline_image_pss_mib'] = round(sum(row['Pss'] for row in metrics) / 1024, 2)
            assert report['candidate_image_pss_mib'] < report['baseline_image_pss_mib'] * .5, (
                report['candidate_image_pss_mib'], report['baseline_image_pss_mib'])
        finally:
            prefix.close()
    assert source_before == {name: fingerprint(cef_dir / name) for name in source_before}
    report['passed'] = True
    (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
