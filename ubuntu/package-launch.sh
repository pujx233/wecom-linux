#!/usr/bin/env bash
set -euo pipefail
unset WINEARCH WINESERVER WINELOADER WINELOADERNOEXEC WINEDLLPATH WINESERVERSOCKET
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
read -r version revision < "$root/application-version"
if [[ "$(cat "$state/prefix/.wecom-application" 2>/dev/null || true)" != "$revision" ]]; then
  # An existing prefix owns account data; update only the packaged application files.
  if WINEPREFIX="$state/prefix" timeout 3 "$root/wine/bin/wineserver" -w; then
    # Version registry writes start Wine too; recover an idle prefix before them.
    python3 "$root/template/wecom-compat/scripts/prepare-startup.py" --prefix "$state/prefix"
    app='drive_c/Program Files (x86)/WXWork'
    cp -a --reflink=auto --no-preserve=links -- "$root/template/$app/." "$state/prefix/$app/"
    backup='AppData/Roaming/Tencent/WeMail/WeMailBak/Base'
    cp -a --reflink=auto --no-preserve=links -- "$root/template/drive_c/users/wecom/$backup/." \
      "$state/prefix/drive_c/users/$(id -un)/$backup/"
    for setting in "Version=$version" "WeMeetDir=C:\\Program Files (x86)\\WXWork\\$version\\WeMeet"; do
      WINEPREFIX="$state/prefix" WINESERVER="$root/wine/bin/wineserver" WINEDEBUG=-all \
        "$root/wine/bin/wine" reg add 'HKCU\Software\Tencent\WXWork' \
        /v "${setting%%=*}" /t REG_SZ /d "${setting#*=}" /f /reg:32
    done
    printf '%s\n' "$revision" > "$state/prefix/.wecom-application"
  else
    status=$?
    printf '%s\n' '企业微信尚未完全退出，或 Wine 状态检查失败；请退出后重新启动以完成升级。' >&2
    exit "$status"
  fi
fi
flock -u 9
exec 9>&-
export WECOM_PREFIX="$state/prefix"
export WECOM_LOG_DIR="$state/logs"
exec bash "$root/launch.sh"
