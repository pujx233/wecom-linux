#!/bin/sh
set -eu
test "$#" -eq 2 || { printf 'Usage: %s /absolute/wine-11.20.tar.gz /absolute/new-output\n' "$0" >&2; exit 2; }
archive=$1
output=$2
case "$archive:$output" in /*:/*) ;; *) exit 2 ;; esac
test -f "$archive"
test ! -e "$output"
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
expected=98b21b4ebdf7d9e2baa4a3508514285cf449f455603f82d3364b014c0e79b793
actual=$(sha256sum "$archive")
test "${actual%% *}" = "$expected"
mkdir -p "$output/source" "$output/build"
tar -xzf "$archive" --strip-components=1 -C "$output/source"
patch -d "$output/source" -p1 < "$root/wine-11.20-x11-popups.patch"
cd "$output/build"
../source/configure --enable-win64 --without-mingw --without-wayland
grep -q '^#define SONAME_LIBDBUS_1 ' include/config.h
make -j "${WECOM_BUILD_JOBS:-4}" server/wineserver dlls/winex11.drv/winex11.so dlls/win32u/win32u.so
sha256sum server/wineserver dlls/winex11.drv/winex11.so dlls/win32u/win32u.so
mkdir "$output/build-explorer"
cd "$output/build-explorer"
../source/configure --enable-win64 --without-x --without-wayland
make -j "${WECOM_BUILD_JOBS:-4}" programs/explorer/x86_64-windows/explorer.exe
sha256sum programs/explorer/x86_64-windows/explorer.exe
