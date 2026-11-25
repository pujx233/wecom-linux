#!/usr/bin/env bash
set -euo pipefail
export WECOM_SHARED_CEF_IMAGE="${WECOM_SHARED_CEF_IMAGE:-1}"
export WECOM_SHARED_PE_IMAGE="${WECOM_SHARED_PE_IMAGE:-1}"
unset WINEARCH WINESERVER WINELOADER WINELOADERNOEXEC WINEDLLPATH WINESERVERSOCKET WECOM_REUSE_DESKTOP
# Wine regenerates locale-dependent font links when its ANSI codepage changes.
# Configure and upgrade the prefix in the same locale as launch-wecom.sh.
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
wecom_locale=$(python3 "$root/template/wecom-compat/scripts/select-locale.py")
unset LC_ALL
export LANG="$wecom_locale" LC_CTYPE="$wecom_locale" LC_MESSAGES="$wecom_locale"
export WINE_NATIVE_FILE_DIALOGS="${WINE_NATIVE_FILE_DIALOGS:-1}"
export WINE_NATIVE_FILE_MANAGER="${WINE_NATIVE_FILE_MANAGER:-1}"
state="${XDG_DATA_HOME:-$HOME/.local/share}/wecom"
mkdir -p -m 700 -- "$state"
exec 9>"$state/setup.lock"
flock 9
if [[ ! -f "$state/prefix/system.reg" ]]; then
  restore=()
  staging_parent="$state"
  if [[ -e "$state/prefix" || -L "$state/prefix" ]]; then
    target="$(realpath -e -- "$state/prefix")"
    if [[ ! -d "$target" ]]; then
      printf '企业微信用户目录无法恢复：%s 不是目录。\n' "$target" >&2
      exit 1
    fi
    python3 "$root/prefix-state.py" "$target" "$root/wine/bin/wineserver"
    restore=(--restore-to "$target")
    staging_parent="$target"
  fi
  temporary="$(mktemp -d "$staging_parent/setup.XXXXXXXX")"
  trap 'rm -rf -- "$temporary"' EXIT
  cp -a --reflink=auto --no-preserve=links -- "$root/template/." "$temporary/prefix"
  python3 "$root/relocate-prefix.py" "$temporary/prefix" "$(id -un)" "${restore[@]}"
  if (( ! ${#restore[@]} )); then
    mv -T -- "$temporary/prefix" "$state/prefix"
  fi
  rm -rf -- "$temporary"
  trap - EXIT
fi
read -r version revision < "$root/application-version"
if python3 "$root/prefix-state.py" "$state/prefix" "$root/wine/bin/wineserver"; then
  python3 "$root/configure-prefix.py" "$root" "$state/prefix"
  if [[ "$(cat "$state/prefix/.wecom-application" 2>/dev/null || true)" != "$revision" ]]; then
    # An existing prefix owns account data; update only the packaged application files.
    # Version registry writes start Wine too; recover an idle prefix before them.
    python3 "$root/template/wecom-compat/scripts/prepare-startup.py" --prefix "$state/prefix"
    app='drive_c/Program Files (x86)/WXWork'
    cp -a --reflink=auto --no-preserve=links --remove-destination -- \
      "$root/template/$app/." "$state/prefix/$app/"
    backup='AppData/Roaming/Tencent/WeMail/WeMailBak/Base'
    cp -a --reflink=auto --no-preserve=links --remove-destination -- \
      "$root/template/drive_c/users/wecom/$backup/." \
      "$state/prefix/drive_c/users/$(id -un)/$backup/"
    for setting in "Version=$version" "WeMeetDir=C:\\Program Files (x86)\\WXWork\\$version\\WeMeet"; do
      WINEPREFIX="$state/prefix" WINESERVER="$root/wine/bin/wineserver" WINEDEBUG=-all \
        "$root/wine/bin/wine" reg add 'HKCU\Software\Tencent\WXWork' \
        /v "${setting%%=*}" /t REG_SZ /d "${setting#*=}" /f /reg:32
    done
    printf '%s\n' "$revision" > "$state/prefix/.wecom-application"
  fi
else
  status=$?
  if [[ "$status" != 124 ]]; then
    exit "$status"
  fi
  export WECOM_EMBEDDED_UI_DPI_FIX=0
  if python3 "$root/prefix-state.py" --wecom-running "$state/prefix"; then
    # The running client already has an Explorer desktop. Wait for WeCom's own
    # second instance to finish forwarding this activation before returning.
    export WECOM_REUSE_DESKTOP=1
  fi
  if [[ "$(cat "$state/prefix/.wecom-application" 2>/dev/null || true)" != "$revision" ]]; then
    printf '%s\n' '企业微信正在运行；本次继续使用当前应用文件，完全退出后下次启动完成更新。' >&2
  fi
fi
flock -u 9
exec 9>&-
export WECOM_PREFIX="$state/prefix"
export WECOM_LOG_DIR="$state/logs"
exec bash "$root/launch.sh"
