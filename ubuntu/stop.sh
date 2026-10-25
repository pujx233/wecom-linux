#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
test -f "$root/prefix/system.reg"
WINEPREFIX="$root/prefix" "$root/wine/bin/wineserver" -k
WINEPREFIX="$root/prefix" "$root/wine/bin/wineserver" -w
