#!/usr/bin/env python3
"""Package a verified, never-logged-in WeCom template and its private Wine runtime."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--baseline', required=True, type=Path)
parser.add_argument('--baseline-manifest', required=True, type=Path)
parser.add_argument('--runtime', required=True, type=Path)
parser.add_argument('--helpers', required=True, type=Path)
parser.add_argument('--wine-source', required=True, type=Path)
parser.add_argument('--stage', required=True, type=Path)
parser.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
repo = Path(__file__).resolve().parents[1]
spec = json.loads((repo / 'ubuntu/release.json').read_text())


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(data)
    return result.hexdigest()


def overlay(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.packaging')
    shutil.copy2(source, temporary)
    os.replace(temporary, target)


assert not args.stage.exists(), 'Use a new staging directory'
assert digest(args.wine_source) == spec['wine_source_sha256']
baseline = json.loads(args.baseline_manifest.read_text())
assert baseline['all_archive_bytes_and_base_files_match'] is True
assert baseline['archive_sha256'] == spec['prelogin_archive_sha256']
assert {str(path.relative_to(args.baseline)) for path in args.baseline.rglob('*')} == set(baseline['manifest'])
hash_cache = {}
for name, entry in baseline['manifest'].items():
    path = args.baseline / name
    info = path.lstat()
    if entry['type'] == 'file':
        assert stat.S_ISREG(info.st_mode) and info.st_size == entry['size'], name
        key = (info.st_dev, info.st_ino, info.st_mtime_ns)
        if key not in hash_cache:
            hash_cache[key] = digest(path)
        assert hash_cache[key] == entry['sha256'], name
    elif entry['type'] == 'symlink':
        assert path.is_symlink() and os.readlink(path) == entry['target'], name
    else:
        assert stat.S_ISDIR(info.st_mode), name
print('Verified the immutable prelogin baseline', flush=True)
files = args.stage / 'opt/apps/com.qq.wecom.spark/files'
files.mkdir(parents=True)
shutil.copytree(args.baseline / 'prefix', files / 'template', symlinks=True, copy_function=os.link)
shutil.copytree(args.runtime, files / 'wine', symlinks=True, copy_function=os.link)
template = files / 'template'
for path in list(template.rglob('*')):
    if path.is_symlink():
        target = os.readlink(path)
        if '/home/' in target or path.name.startswith('com'):
            path.unlink()
    elif path.is_file() and path.suffix.lower() in ('.log', '.dmp', '.mdmp', '.lock', '.pyc'):
        path.unlink()
profile = template / 'drive_c/users/sai'
profile.rename(profile.with_name('wecom'))
for name in ('user.reg', 'userdef.reg', 'system.reg'):
    path = template / name
    text = path.read_text().replace('sai', 'wecom')
    temporary = path.with_suffix('.packaging')
    temporary.write_text(text)
    os.replace(temporary, path)
compat = template / 'wecom-compat'
shutil.rmtree(compat)
for directory in ('scripts', 'configs'):
    shutil.copytree(repo / directory, compat / directory, symlinks=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'gnome-*'))
for name in ('ime-bridge.so', 'titlebar-managed.exe', 'set-status-font.exe'):
    assert digest(args.helpers / name) == spec['helpers_sha256'][name], name
    overlay(args.helpers / name, compat / 'scripts' / name)
cef = template / 'drive_c/Program Files (x86)/WXWork/5.0.12.6018/compatible_web/libcef.dll'
temporary = cef.with_suffix('.packaging')
subprocess.run(['python3', str(repo / 'ubuntu/patch-cef-x86.py'), '--source', str(cef),
                '--output', str(temporary)], check=True)
os.replace(temporary, cef)
assert digest(cef) == spec['artifacts_sha256']['libcef.dll']
for name, relative in spec['wine_components'].items():
    assert digest(files / relative) == spec['artifacts_sha256'][name], name
for relative in ('drive_c/windows/explorer.exe', 'drive_c/windows/system32/explorer.exe'):
    overlay(files / 'wine/lib/wine/x86_64-windows/explorer.exe', template / relative)

# Strip only Wine's PE debug data. Keep every application and vendor DLL byte-for-byte.
original_wine_files = {}
for directory in ('x86_64-windows', 'i386-windows'):
    for path in (files / 'wine/lib/wine' / directory).iterdir():
        if path.suffix.lower() not in ('.dll', '.exe') or not path.is_file():
            continue
        original = digest(path)
        temporary = path.with_suffix(path.suffix + '.stripped')
        subprocess.run(['objcopy', '--strip-debug', str(path), str(temporary)], check=True)
        before, after = path.read_bytes(), temporary.read_bytes()
        loaded = []
        for data in (before, after):
            pe = struct.unpack_from('<I', data, 60)[0]
            count = struct.unpack_from('<H', data, pe + 6)[0]
            optional = struct.unpack_from('<H', data, pe + 20)[0]
            sections = []
            for index in range(count):
                offset = pe + 24 + optional + index * 40
                name, size, address, raw, pointer = struct.unpack_from('<8sIIII', data, offset)
                # COFF long section names hold non-runtime DWARF data in this Wine build.
                if not name.startswith((b'/', b'.debug')):
                    sections.append((name, address, size, data[pointer:pointer + raw]))
            loaded.append(sections)
        assert loaded[0] == loaded[1], 'Stripping changed a runtime section: ' + str(path)
        os.replace(temporary, path)
        original_wine_files[original] = path
for path in template.rglob('*'):
    if path.is_file() and not path.is_symlink() and path.suffix.lower() in ('.dll', '.exe'):
        replacement = original_wine_files.get(digest(path))
        if replacement:
            path.unlink()
            os.link(replacement, path)

# Share identical bytes in the archive, without replacing files by external symlinks.
by_size = {}
for path in files.rglob('*'):
    if path.is_file() and not path.is_symlink():
        by_size.setdefault(path.stat().st_size, []).append(path)
for paths in by_size.values():
    if len(paths) < 2:
        continue
    by_hash = {}
    for path in paths:
        value = (digest(path), stat.S_IMODE(path.stat().st_mode))
        if value in by_hash and not os.path.samefile(path, by_hash[value]):
            path.unlink()
            os.link(by_hash[value], path)
        else:
            by_hash[value] = path
packaged = {name: digest(files / relative) for name, relative in spec['wine_components'].items()}
print('Wine PE runtime sections preserved; identical files deduplicated', flush=True)
for name, target in (('launch.sh', 'launch.sh'), ('package-launch.sh', 'start.sh'),
                     ('relocate-prefix.py', 'relocate-prefix.py')):
    overlay(repo / 'ubuntu' / name, files / target)
    (files / target).chmod(0o755)
doc = args.stage / 'usr/share/doc/com.qq.wecom.spark'
doc.mkdir(parents=True)
overlay(args.wine_source, doc / 'wine-11.20.tar.gz')
for name in ('README.md', 'build.sh', 'Dockerfile', 'wine-11.20-x11-popups.patch'):
    overlay(repo / 'ubuntu/wine-x11-fix' / name, doc / name)
overlay(repo / 'ubuntu/release.json', doc / 'release.json')
(doc / 'packaged-runtime.json').write_text(json.dumps({
    'artifacts_sha256': packaged, 'wine_pe_debug_removed': True,
    'non_debug_pe_sections_byte_identical': True, 'vendor_files_stripped': False,
    'archive_identical_file_hardlinks': True,
}, indent=2) + '\n')
overlay(repo / 'THIRD-PARTY.md', doc / 'copyright')
overlay(repo / 'licenses/Wine-COPYING.LIB', doc / 'Wine-COPYING.LIB')
overlay(repo / 'README.md', doc / 'README.zh-CN.md')
overlay(repo / 'ubuntu/com.qq.wecom.spark.desktop',
        args.stage / 'usr/share/applications/com.qq.wecom.spark.desktop')
overlay(args.baseline / 'wecom.svg', args.stage / 'usr/share/icons/hicolor/scalable/apps/com.qq.wecom.spark.svg')
inodes = {}
for path in args.stage.rglob('*'):
    if path.is_file() and not path.is_symlink():
        info = path.stat()
        inodes[(info.st_dev, info.st_ino)] = (info.st_size + 1023) // 1024
installed = sum(inodes.values())
control = args.stage / 'DEBIAN/control'
control.parent.mkdir()
control.write_text(f'''Package: com.qq.wecom.spark
Version: {spec['package_version']}
Architecture: amd64
Maintainer: pujx233 <pujx0415@qq.com>
Section: non-free/net
Priority: optional
Installed-Size: {installed}
Depends: bash, coreutils, util-linux, python3, libpython3-stdlib, libc6 (>= 2.43), libx11-6,
 libxext6, libfreetype6, libfontconfig1, libdbus-1-3, libxrandr2, libxrender1,
 libxcursor1, libxi6, libxfixes3, libxcomposite1, libxinerama1, libglib2.0-0t64
Recommends: xwayland, libasound2t64, libpulse0, libvulkan1
Homepage: https://github.com/pujx233/wecom-linux
Description: 企业微信
 企业微信 5.0.12.6018，内置私有 Wine 11.20 的 Ubuntu 26.04 amd64 适配测试版。
 包含右键/透明窗口、跨进程绘制、聊天记录首帧及邮件光标修订。
 已知托盘点击/右键和“更多操作”定位仍有限制，部分弹窗尚未完整验收。
 不需要额外桌面，不修改 GNOME、Mutter、系统 Wine 或桌面设置。
 首次启动创建独立的未登录用户目录，不包含发布者的账号或聊天记录。
''')
subprocess.run(['desktop-file-validate', str(args.stage / 'usr/share/applications/com.qq.wecom.spark.desktop')],
               check=True)
args.output.parent.mkdir(parents=True, exist_ok=True)
subprocess.run(['dpkg-deb', '--root-owner-group', '-Zxz', '-z6', '--threads-max=4',
                '--build', str(args.stage), str(args.output)], check=True)
print(json.dumps({'package': args.output.name, 'sha256': digest(args.output),
                  'bytes': args.output.stat().st_size}, ensure_ascii=False), flush=True)
