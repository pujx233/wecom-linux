#!/usr/bin/env python3
"""Build the app-private Xlib with Ubuntu's patches and synchronous XIM callback delivery."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', required=True, type=Path, help='New build directory')
parser.add_argument('--archives', type=Path, help='Directory containing the two pinned Ubuntu source archives')
args = parser.parse_args()
output = args.output.resolve()
output.mkdir(parents=True, exist_ok=False)
root = Path(__file__).resolve().parent
archives = args.archives.resolve() if args.archives else output
sources = {
    'libx11_1.8.13.orig.tar.gz': 'acf0e7cd7541110e6330ecb539441a2d53061f386ec7be6906dfde0de2598470',
    'libx11_1.8.13-1ubuntu0.1.diff.gz': '33cef8a2f61600704330ded455cc4faa5d1ed71cd461b1c7b10c1b3a390b016f',
}
for name, expected in sources.items():
    archive = archives / name
    if not args.archives:
        urllib.request.urlretrieve('https://archive.ubuntu.com/ubuntu/pool/main/libx/libx11/' + name, archive)
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected, name
source = output / 'source'
source.mkdir()
with tarfile.open(archives / 'libx11_1.8.13.orig.tar.gz') as archive:
    archive.extractall(source, filter='data')
source = source / 'libX11-1.8.13'
with gzip.open(archives / 'libx11_1.8.13-1ubuntu0.1.diff.gz', 'rb') as diff:
    subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-d', source], input=diff.read(), check=True)
# Debian source format 1.0 does not apply the distribution's patch series itself.
for name in (source / 'debian/patches/series').read_text().splitlines():
    name = name.split('#', 1)[0].strip()
    if name:
        subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-d', source,
                        '-i', source / 'debian/patches' / name], check=True)
subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-d', source,
                '-i', root / 'pending-callbacks.patch'], check=True)
build = output / 'build'
build.mkdir()
subprocess.run([source / 'configure', '--prefix=/usr', '--disable-static', '--disable-specs',
                '--disable-docs', '--disable-devel-docs', '--enable-ipv6'], cwd=build, check=True)
subprocess.run(['make', '-j', os.environ.get('WECOM_BUILD_JOBS', '4')], cwd=build, check=True)
library = output / 'libX11.so.6'
shutil.copy2(build / 'src/.libs/libX11.so.6.4.0', library)
subprocess.run(['strip', '--strip-unneeded', library], check=True)
record = dict(ubuntu_source='2:1.8.13-1ubuntu0.1', source_sha256=sources,
              patch_sha256=hashlib.sha256((root / 'pending-callbacks.patch').read_bytes()).hexdigest(),
              artifact_sha256=hashlib.sha256(library.read_bytes()).hexdigest())
(output / 'build.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record))
