#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
out="${1:-$root/.local-build/helpers}"
mkdir -p -- "$out"
gcc -std=c11 -shared -fPIC -Wall -Wextra -Werror -O2 \
  "$root/scripts/ime-bridge.c" -o "$out/ime-bridge.so" -ldl
for helper in titlebar-managed set-status-font; do
  clang-21 --target=i686-pc-windows-msvc -ffreestanding -fno-stack-protector \
    -Wall -Wextra -Werror -Wno-unused-parameter \
    -c "$root/scripts/$helper.c" -o "$out/$helper.obj"
  i686-w64-mingw32-gcc -nostdlib -Wl,--entry=_mainCRTStartup -Wl,--subsystem,console \
    "$out/$helper.obj" -o "$out/$helper.exe" -lkernel32 -luser32
done
