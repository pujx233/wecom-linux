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
import tempfile
import zipfile

parser = argparse.ArgumentParser(description=__doc__)
source = parser.add_mutually_exclusive_group(required=True)
source.add_argument('--baseline', type=Path)
source.add_argument('--base-package', type=Path)
parser.add_argument('--baseline-manifest', type=Path)
parser.add_argument('--runtime', required=True, type=Path)
parser.add_argument('--helpers', required=True, type=Path)
parser.add_argument('--wine-source', required=True, type=Path)
parser.add_argument('--installer', required=True, type=Path)
parser.add_argument('--stage', required=True, type=Path)
parser.add_argument('--output', required=True, type=Path)
parser.add_argument('--stage-only', action='store_true')
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
assert digest(repo / 'ubuntu/wine-x11-fix/wine-11.20-x11-popups.patch') == spec['wine_patch_sha256'], \
    'Wine patch does not match the runtime release manifest'
required_components = ['wine/bin/wineserver', 'wine/lib/wine/x86_64-unix/ntdll.so',
                       'wine/lib/wine/x86_64-unix/win32u.so', 'wine/lib/wine/x86_64-unix/winex11.so',
                       'wine/lib/wine/x86_64-unix/wineps.so', 'wine/lib/wine/x86_64-unix/winewayland.so',
                       'wine/lib/wine/x86_64-unix/mountmgr.so',
                       'wine/lib/wine/x86_64-windows/wineboot.exe']
for architecture in ('i386-windows', 'x86_64-windows'):
    for name in ('imm32.dll', 'cfgmgr32.dll', 'setupapi.dll', 'ntoskrnl.exe'):
        required_components.append(f'wine/lib/wine/{architecture}/{name}')
for relative in required_components:
    assert relative in spec['wine_components'].values(), 'Incomplete Wine component manifest: ' + relative
args.stage.parent.mkdir(parents=True, exist_ok=True)
assert digest(args.wine_source) == spec['wine_source_sha256']
assert digest(args.installer) == spec['installer_sha256'], 'Unsupported application installer'
base_files = None
if args.base_package:
    assert digest(args.base_package) in spec['base_package_sha256'], 'Unsupported base package'
    base_package = tempfile.TemporaryDirectory(prefix='wecom-prelogin-', dir=args.stage.parent)
    extracted = Path(base_package.name)
    subprocess.run(['dpkg-deb', '--extract', str(args.base_package), str(extracted)], check=True)
    base_files = extracted / 'opt/apps/com.qq.wecom.spark/files'
    template_source = base_files / 'template'
    icon_source = extracted / 'usr/share/icons/hicolor/scalable/apps/com.qq.wecom.spark.svg'
    print('Verified the published package containing the prelogin template', flush=True)
else:
    if not args.baseline_manifest:
        parser.error('--baseline requires --baseline-manifest')
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
    template_source = args.baseline / 'prefix'
    icon_source = args.baseline / 'wecom.svg'
    print('Verified the immutable prelogin baseline', flush=True)
files = args.stage / 'opt/apps/com.qq.wecom.spark/files'
files.mkdir(parents=True)
shutil.copytree(template_source, files / 'template', symlinks=True)
shutil.copytree(args.runtime, files / 'wine', symlinks=True)
template = files / 'template'
if args.baseline:
    profile = template / 'drive_c/users/sai'
    profile.rename(profile.with_name('wecom'))
    for name in ('user.reg', 'userdef.reg', 'system.reg'):
        path = template / name
        text = path.read_text().replace('sai', 'wecom')
        temporary = path.with_suffix('.packaging')
        temporary.write_text(text)
        os.replace(temporary, path)
application = template / 'drive_c/Program Files (x86)/WXWork'
with tempfile.TemporaryDirectory(prefix='wecom-installer-', dir=args.stage.parent) as temporary:
    vendor = Path(temporary)
    subprocess.run(['7zz', 'x', '-y', '-o' + str(vendor), str(args.installer)], check=True)
    assert (vendor / spec['wecom_version']).is_dir(), 'Installer version mismatch'
    shutil.rmtree(application)
    shutil.copytree(vendor / '$PROGRAMFILES/WXWork', application)
    shutil.copytree(vendor / spec['wecom_version'], application / spec['wecom_version'])
    for name in ('WXWork.exe', 'Uninstall.exe'):
        overlay(vendor / name, application / name)
    versioned = application / spec['wecom_version']
    for archive, directory in (('wemeet.zip', 'WeMeet'), ('FlutterPlugins.zip', 'FlutterPlugins'),
                               ('dict.zip', 'hotword'),
                               ('wecomagent-runtime-python-windows-x86-3.10.zip', 'WeComAgent')):
        with zipfile.ZipFile(versioned / archive) as source:
            source.extractall(versioned / directory)
        if archive != 'wemeet.zip':
            (versioned / archive).unlink()
    overlay(versioned / 'WeComAgent/wecom-agent.exe', versioned / 'WeComAgent/wecom.exe')
    backup = Path('Tencent/WeMail/WeMailBak/Base')
    shutil.copytree(vendor / '$APPDATA' / backup,
                    template / 'drive_c/users/wecom/AppData/Roaming' / backup, dirs_exist_ok=True)
settings = (template / 'user.reg').read_text().split(r'[Software\\Tencent\\WXWork]', 1)[1].split('\n\n', 1)[0]
previous = next(line.split('"')[3] for line in settings.splitlines() if line.startswith('"Version"='))
for name in ('user.reg', 'system.reg'):
    path = template / name
    text = path.read_text()
    path.write_text(text.replace(previous, spec['wecom_version']))
for path in list(template.rglob('*')):
    if path.is_symlink():
        target = os.readlink(path)
        if '/home/' in target or path.name.startswith('com'):
            path.unlink()
    elif path.is_file() and path.suffix.lower() in ('.log', '.dmp', '.mdmp', '.lock', '.pyc'):
        path.unlink()
compat = template / 'wecom-compat'
shutil.rmtree(compat)
for directory in ('scripts', 'configs'):
    shutil.copytree(repo / directory, compat / directory, symlinks=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'gnome-*'))
for name in ('ime-bridge.so', 'titlebar-managed.exe', 'set-status-font.exe'):
    assert digest(args.helpers / name) == spec['helpers_sha256'][name], name
    overlay(args.helpers / name, compat / 'scripts' / name)
cef = template / 'drive_c/Program Files (x86)/WXWork' / spec['wecom_version'] / 'compatible_web/libcef.dll'
if digest(cef) != spec['artifacts_sha256']['libcef.dll']:
    temporary = cef.with_suffix('.packaging')
    subprocess.run(['python3', str(repo / 'ubuntu/patch-cef-x86.py'), '--source', str(cef),
                    '--output', str(temporary)], check=True)
    os.replace(temporary, cef)
assert digest(cef) == spec['artifacts_sha256']['libcef.dll']
for name, relative in spec['wine_components'].items():
    assert digest(files / relative) == spec['artifacts_sha256'][name], name
for relative in ('drive_c/windows/explorer.exe', 'drive_c/windows/system32/explorer.exe'):
    overlay(files / 'wine/lib/wine/x86_64-windows/explorer.exe', template / relative)
overlay(files / 'wine/lib/wine/x86_64-windows/wineboot.exe', template / 'drive_c/windows/system32/wineboot.exe')
for architecture, directory in (('x86_64-windows', 'system32'), ('i386-windows', 'syswow64')):
    for name in ('imm32.dll', 'cfgmgr32.dll', 'setupapi.dll', 'ntoskrnl.exe'):
        overlay(files / 'wine/lib/wine' / architecture / name, template / 'drive_c/windows' / directory / name)

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
        if base_files:
            old = base_files / path.relative_to(files)
            if old.is_file():
                original_wine_files[digest(old)] = path
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
(files / 'application-version').write_text(spec['wecom_version'] + ' ' + spec['package_version'] + '\n')
(template / '.wecom-application').write_text(spec['package_version'] + '\n')
doc = args.stage / 'usr/share/doc/com.qq.wecom.spark'
doc.mkdir(parents=True)
overlay(args.wine_source, doc / 'wine-11.20.tar.gz')
for name in ('README.md', 'CODE-REVIEW.md', 'build.sh', 'Dockerfile', 'wine-11.20-x11-popups.patch'):
    overlay(repo / 'ubuntu/wine-x11-fix' / name, doc / name)
assert digest(doc / 'wine-11.20-x11-popups.patch') == spec['wine_patch_sha256'], 'Wine patch changed during packaging'
overlay(repo / 'ubuntu/release.json', doc / 'release.json')
overlay(repo / 'ubuntu/validation.json', doc / 'validation.json')
overlay(repo / 'ubuntu/wine-x11-fix/tests/gdiplus-render-check.cpp', doc / 'tests/gdiplus-render-check.cpp')
(doc / 'packaged-runtime.json').write_text(json.dumps({
    'artifacts_sha256': packaged, 'wine_pe_debug_removed': True,
    'non_debug_pe_sections_byte_identical': True, 'vendor_files_stripped': False,
    'archive_identical_file_hardlinks': True,
}, indent=2) + '\n')
overlay(repo / 'THIRD-PARTY.md', doc / 'copyright')
overlay(repo / 'licenses/Wine-COPYING.LIB', doc / 'Wine-COPYING.LIB')
overlay(repo / 'README.md', doc / 'README.zh-CN.md')
adapter = doc / 'adapter'
for directory in ('ubuntu', 'scripts', 'configs', 'licenses'):
    shutil.copytree(repo / directory, adapter / directory, symlinks=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
for name in ('README.md', 'UBUNTU.md', 'THIRD-PARTY.md'):
    overlay(repo / name, adapter / name)
overlay(repo / 'ubuntu/com.qq.wecom.spark.desktop',
        args.stage / 'usr/share/applications/com.qq.wecom.spark.desktop')
overlay(icon_source, args.stage / 'usr/share/icons/hicolor/scalable/apps/com.qq.wecom.spark.svg')
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
 libxcursor1, libxi6, libxfixes3, libxcomposite1, libxdamage1, libxinerama1, libglib2.0-0t64
Recommends: xwayland, libasound2t64, libpulse0, libvulkan1
Homepage: https://github.com/pujx233/wecom-linux
Description: 企业微信
 企业微信 {spec['wecom_version']}，内置私有 Wine 11.20 的 Ubuntu 26.04 amd64 适配测试版。
 包含透明窗口合成、拖动、图片缩放、聊天记录绘制及邮件光标修订。
 已知托盘“更多操作”定位仍有限制，完整功能及其他桌面尚未全面验收。
 不需要额外桌面，不修改 GNOME、Mutter、系统 Wine 或桌面设置。
 首次启动创建独立的未登录用户目录，不包含发布者的账号或聊天记录。
''')
subprocess.run(['desktop-file-validate', str(args.stage / 'usr/share/applications/com.qq.wecom.spark.desktop')],
               check=True)
# The archive installs as root; every user must be able to copy the prelogin template.
args.stage.chmod(0o755)
for path in args.stage.rglob('*'):
    if not path.is_symlink():
        mode = 0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644
        path.chmod(mode)
if args.stage_only:
    print(json.dumps({'stage': str(args.stage), 'prepared': True}), flush=True)
    raise SystemExit(0)
args.output.parent.mkdir(parents=True, exist_ok=True)
subprocess.run(['dpkg-deb', '--root-owner-group', '-Zxz', '-z6', '--threads-max=4',
                '--build', str(args.stage), str(args.output)], check=True)
print(json.dumps({'package': args.output.name, 'sha256': digest(args.output),
                  'bytes': args.output.stat().st_size}, ensure_ascii=False), flush=True)
