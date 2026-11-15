#!/usr/bin/env python3
"""Exercise demand-paged PE sections, relocations, COW and cache lifetime without an account or desktop."""
import argparse
import errno
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import struct
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('cef_cache_tests', HERE.parent / 'cef-image-cache/run.py')
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)


class Prefix(common.Prefix):
    def __init__(self, runtime, root, enabled=True, preload=None, failure_stage=None):
        os.environ['WECOM_SHARED_PE_IMAGE'] = str(int(enabled))
        if failure_stage:
            os.environ['WECOM_QA_CACHE_FAILURE_STAGE'] = failure_stage
        else:
            os.environ.pop('WECOM_QA_CACHE_FAILURE_STAGE', None)
        super().__init__(runtime, root, True, preload)

    def start(self, dll, marker=None, reserve=None, flags=0, main=False):
        tag = f'{self.root.name}:{len(self.clients)}'
        command = [str(self.runtime / 'bin/wine'), str(dll if main else dll.parent / 'loader.exe'),
                   '--self' if main else str(dll), str(flags)]
        if reserve:
            command += [hex(reserve['base']), hex(reserve['size'])]
        process = subprocess.Popen(command, env=self.env | {'WECOM_CEF_QA_SAMPLE': tag},
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, text=True)
        client = {'process': process}
        self.clients.append(client)
        client['info'] = info = common.read_json(process)
        expected = ('WECOM_CEF_QA_SAMPLE=' + tag).encode()
        for proc in Path('/proc').iterdir():
            if not proc.name.isdigit():
                continue
            try:
                if expected not in (proc / 'environ').read_bytes().split(b'\0'):
                    continue
                if any(int(line.split('-')[0], 16) == info['base'] and line.endswith(str(dll))
                       for line in (proc / 'maps').read_text().splitlines()):
                    client['pid'] = int(proc.name)
                    break
            except OSError:
                continue
        assert 'pid' in client, 'No client maps the original image header at the reported base'
        if marker is not None:
            assert info['marker'] == marker and info['count'] == 1, info
        return client

    def caches(self, check_seals=False):
        del check_seals
        pid = common.find_pid('WINEPREFIX', str(self.prefix))
        result = {}
        for path in Path(f'/proc/{pid}/fd').iterdir():
            try:
                st = path.stat()
                if not stat.S_ISREG(st.st_mode) or st.st_size < 24:
                    continue
                with path.open('rb', buffering=0) as stream:
                    magic, base, size = struct.unpack('<8sQQ', os.pread(stream.fileno(), 24, 0))
                    if magic != b'WinePE3\0':
                        continue
                    assert not st.st_nlink and not st.st_mode & 0o222 and st.st_size == size
                    fdinfo = path.parent.parent / 'fdinfo' / path.name
                    access = next(line.split()[1] for line in fdinfo.read_text().splitlines()
                                  if line.startswith('flags:'))
                    assert int(access, 8) & os.O_ACCMODE == os.O_RDONLY
                    try:
                        os.pwrite(stream.fileno(), b'x', 0)
                    except OSError as error:
                        assert error.errno == errno.EBADF
                    else:
                        raise AssertionError('Read-only cache accepted a write')
                    result[st.st_ino] = {'base': base, 'size': size, 'inode': st.st_ino}
            except FileNotFoundError:
                continue
        return result

    def image_cache(self, client):
        address = client['info']['base'] + client['info']['probe_rva']
        for line in Path(f"/proc/{client['pid']}/maps").read_text().splitlines():
            fields = line.split()
            start, end = [int(value, 16) for value in fields[0].split('-')]
            if start <= address < end:
                return self.caches().get(int(fields[4]))
        raise AssertionError('Image probe has no mapping')

    def wait_gone(self, inode):
        deadline = time.monotonic() + 5
        while inode in self.caches():
            assert time.monotonic() < deadline, inode
            time.sleep(.02)


def stats(client):
    return common.image_stats(client['pid'], client['info']['base'], client['info']['size'])


def mark_shared(path):
    data = bytearray(path.read_bytes())
    pe = struct.unpack_from('<I', data, 60)[0]
    table = pe + 24 + struct.unpack_from('<H', data, pe + 20)[0]
    for index in range(struct.unpack_from('<H', data, pe + 6)[0]):
        header = table + index * 40
        if data[header:header + 8].rstrip(b'\0') == b'.shared':
            flags = struct.unpack_from('<I', data, header + 36)[0]
            struct.pack_into('<I', data, header + 36, flags | 0x10000000)
            path.write_bytes(data)
            return
    raise AssertionError('Shared fixture has no .shared section')


def unalign_sections(path):
    data = bytearray(path.read_bytes())
    pe = struct.unpack_from('<I', data, 60)[0]
    table = pe + 24 + struct.unpack_from('<H', data, pe + 20)[0]
    count = struct.unpack_from('<H', data, pe + 6)[0]
    offsets = [struct.unpack_from('<I', data, table + i * 40 + 20)[0] for i in range(count)]
    first = min(offset for offset in offsets if offset)
    data[first:first] = bytes(512)
    for index, offset in enumerate(offsets):
        if offset:
            struct.pack_into('<I', data, table + index * 40 + 20, offset + 512)
    symbols = struct.unpack_from('<I', data, pe + 12)[0]
    if symbols:
        struct.pack_into('<I', data, pe + 12, symbols + 512)
    header_size = struct.unpack_from('<I', data, pe + 24 + 60)[0]
    struct.pack_into('<I', data, pe + 24 + 60, header_size + 512)
    path.write_bytes(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--resource-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--inside', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    runtime, resources, output = args.runtime.resolve(), args.resource_dir.resolve(), args.output.resolve()
    if not args.inside:
        output.mkdir(mode=0o700, parents=True, exist_ok=False)
        return subprocess.call(['bwrap', '--unshare-net', '--unshare-ipc', '--ro-bind', '/', '/',
                                '--bind', str(output), str(output), '--tmpfs', '/tmp',
                                '--tmpfs', f'/run/user/{os.getuid()}', '--dev', '/dev', '--proc', '/proc', '--',
                                sys.executable, str(HERE / 'run.py'), '--inside', '--runtime', str(runtime),
                                '--resource-dir', str(resources), '--output', str(output)])
    report = {'passed': False, 'account_used': False, 'host_desktop_used': False,
              'network_isolated': True, 'cases': {}, 'resources': {}, 'sharing': {}}
    fixtures = {}
    for arch, compiler in [('x86', 'i686-w64-mingw32-gcc'), ('x64', 'x86_64-w64-mingw32-gcc')]:
        directory = output / arch
        directory.mkdir()
        subprocess.run([compiler, '-O2', '-Wall', '-Wextra', '-municode', str(HERE / 'loader.c'),
                        '-o', str(directory / 'loader.exe')], check=True)
        for label, marker in [('a', 101), ('b', 202), ('shared', 303)]:
            fixture = directory / label
            fixture.mkdir()
            dll = fixture / 'ordinary.dll'
            subprocess.run([compiler, '-shared', '-O2', '-Wall', '-Wextra', '-DIMAGE_MARKER=' + str(marker),
                            str(HERE / 'image.c'), '-o', str(dll),
                            '-Wl,--dynamicbase,--nxcompat,--image-base,0x10000000'], check=True)
            unalign_sections(dll)
            shutil.copy2(directory / 'loader.exe', fixture / 'loader.exe')
            if label == 'shared':
                mark_shared(dll)
            fixtures[arch, label] = dll
        executable = directory / 'main.exe'
        subprocess.run([compiler, '-O2', '-Wall', '-Wextra', '-municode', str(HERE / 'loader.c'),
                        str(HERE / 'image.c'), '-o', str(executable), '-Wl,--dynamicbase,--nxcompat'], check=True)
        unalign_sections(executable)
        fixtures[arch, 'main'] = executable
    shim = output / 'no-cache.so'
    subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', str(HERE / 'no-cache.c'),
                    '-o', str(shim), '-ldl'], check=True)
    resource_files = []
    for name in ['WXWorkResources.dll', 'WXWorkStrings.dll']:
        directory = output / name
        directory.mkdir()
        shutil.copy2(resources / name, directory / name)
        shutil.copy2(output / 'x86/loader.exe', directory / 'loader.exe')
        resource_files.append(directory / name)
    before_hashes = {p.name: common.fingerprint(resources / p.name) for p in resource_files}
    prefix = Prefix(runtime, output / 'enabled')
    try:
        for arch in ['x86', 'x64']:
            clients = [prefix.start(fixtures[arch, 'a'], 101) for _ in range(4)]
            cache = prefix.image_cache(clients[0])
            assert cache and all(prefix.image_cache(c)['inode'] == cache['inode'] for c in clients)
            common.cow_test(prefix, clients)
            for client in clients:
                prefix.send(client, 't')
            report['sharing'][arch] = {'candidate_pss_mib': round(sum(stats(c)['Pss'] for c in clients) / 1024, 3)}
            conflict = prefix.start(fixtures[arch, 'a'], 101, reserve=clients[0]['info'])
            assert conflict['info']['base'] != clients[0]['info']['base']
            assert prefix.image_cache(conflict)['inode'] == cache['inode']
            other = prefix.start(fixtures[arch, 'b'], 202)
            other_cache = prefix.image_cache(other)
            assert other_cache and other_cache['inode'] != cache['inode']
            os.kill(clients[0]['pid'], signal.SIGKILL)
            assert prefix.send(clients[1], 'r')['probe'] == clients[1]['info']['probe']
            for client in clients[1:] + [conflict, other]:
                assert prefix.send(client, 'u')['unloaded']
            prefix.wait_gone(cache['inode'])
            prefix.wait_gone(other_cache['inode'])
            for index in range(20):
                clients[1]['info'] = prefix.send(clients[1], 'l')
                reloaded = prefix.image_cache(clients[1])
                assert reloaded and clients[1]['info']['count'] == 1
                prefix.send(clients[1], 'u')
                prefix.wait_gone(reloaded['inode'])
            for client in clients + [conflict, other]:
                prefix.stop(client)
            shared = [prefix.start(fixtures[arch, 'shared'], 303) for _ in range(3)]
            assert not any(prefix.image_cache(c) for c in shared)
            assert [prefix.send(c, 's')['shared'] for c in shared] == [1, 2, 3]
            for client in shared:
                prefix.stop(client)
            main_clients = [prefix.start(fixtures[arch, 'main'], 101, main=True) for _ in range(3)]
            main_cache = prefix.image_cache(main_clients[0])
            assert main_cache and all(prefix.image_cache(c)['inode'] == main_cache['inode'] for c in main_clients)
            common.cow_test(prefix, main_clients)
            for client in main_clients:
                prefix.stop(client)
            prefix.wait_gone(main_cache['inode'])
            report['cases'][arch + '_relocations_cow_conflict_identity_crash_lifetime_and_shared_data'] = True
            report['cases'][arch + '_main_executable_shared_without_changing_base'] = True
            print('PASS ' + arch, flush=True)
        for dll in resource_files:
            client = prefix.start(dll, flags=0x20)
            cache = prefix.image_cache(client)
            assert cache
            initial = stats(client)
            assert initial.get('Anonymous', 0) < 128 and initial['Pss'] < client['info']['size'] / 4096
            checksum = prefix.send(client, 't')['checksum']
            touched = stats(client)
            assert touched.get('Anonymous', 0) < 128, touched
            report['resources'][dll.name] = {'candidate_initial_pss_mib': round(initial['Pss'] / 1024, 3),
                                             'candidate_full_anon_mib': round(touched['Anonymous'] / 1024, 3),
                                             'checksum': checksum}
            prefix.stop(client)
            prefix.wait_gone(cache['inode'])
            client = prefix.start(dll)
            assert prefix.image_cache(client) and prefix.send(client, 't')['checksum'] == checksum
            prefix.stop(client)
        report['cases']['real_resource_dlls_demand_paged_clean_and_released'] = True
    finally:
        prefix.close()
    baseline = Prefix(runtime, output / 'disabled', False)
    try:
        for arch in ['x86', 'x64']:
            clients = [baseline.start(fixtures[arch, 'a'], 101) for _ in range(4)]
            assert not any(baseline.image_cache(c) for c in clients)
            for client in clients:
                baseline.send(client, 't')
            size = sum(stats(c)['Pss'] for c in clients) / 1024
            report['sharing'][arch]['baseline_pss_mib'] = round(size, 3)
            print(arch + ' memory ' + json.dumps(report['sharing'][arch]), flush=True)
            assert report['sharing'][arch]['candidate_pss_mib'] < size * .5
            for client in clients:
                baseline.stop(client)
        for dll in resource_files:
            client = baseline.start(dll, flags=0x20)
            initial = stats(client)
            assert baseline.send(client, 't')['checksum'] == report['resources'][dll.name]['checksum']
            report['resources'][dll.name]['baseline_initial_pss_mib'] = round(initial['Pss'] / 1024, 3)
            assert initial['Pss'] > report['resources'][dll.name]['candidate_initial_pss_mib'] * 8
            baseline.stop(client)
        report['cases']['disabled_native_loader_and_resource_contents'] = True
    finally:
        baseline.close()
    for stage in ['create', 'reserve-header', 'reserve-section']:
        failed = Prefix(runtime, output / ('disk-failure-' + stage), True, shim, stage)
        try:
            client = failed.start(fixtures['x86', 'a'], 101)
            assert not failed.image_cache(client), 'Cache survived injected ' + stage + ' failure'
            assert failed.send(client, 'r')['probe'] == client['info']['probe']
            if stage != 'create':
                assert 'qa-cache: reservation rejected' in (failed.root / 'wine.log').read_text()
            name = 'disk_allocation' if stage == 'create' else 'disk_' + stage.replace('-', '_')
            report['cases'][name + '_failure_keeps_native_loader'] = True
        finally:
            failed.close()
    assert before_hashes == {p.name: common.fingerprint(resources / p.name) for p in resource_files}
    report['source_sha256'] = before_hashes
    report['passed'] = True
    (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
