#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
state="${XDG_DATA_HOME:-$HOME/.local/share}/wecom"
mkdir -p -m 700 -- "$state"
exec 9>"$state/setup.lock"
flock 9
if [[ ! -f "$state/prefix/system.reg" ]]; then
  temporary="$(mktemp -d "$state/setup.XXXXXXXX")"
  trap 'rm -rf -- "$temporary"' EXIT
  cp -a --reflink=auto --no-preserve=links -- "$root/template/." "$temporary/prefix"
  python3 "$root/relocate-prefix.py" "$temporary/prefix" "$(id -un)"
  mv -- "$temporary/prefix" "$state/prefix"
  rmdir -- "$temporary"
  trap - EXIT
fi
flock -u 9
exec 9>&-
export WECOM_PREFIX="$state/prefix"
export WECOM_LOG_DIR="$state/logs"
exec bash "$root/launch.sh"
