#!/usr/bin/env bash
set -euo pipefail
: "${WECOM_PREFIX:?Set WECOM_PREFIX to the intended WeCom prefix}"
WECOM_PREFIX="$(cd -- "$WECOM_PREFIX" && pwd -P)"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
app="$WECOM_PREFIX/drive_c/Program Files (x86)/WXWork/WXWork.exe"
test -f "$WECOM_PREFIX/system.reg"
test -f "$app"
overrides="$(cat "$script_dir/../configs/dll-overrides.txt")"
cd -- "$(dirname -- "$app")"
wine_env=(env -u LC_ALL -u WINEARCH -u WINESERVER -u WINELOADER -u WINELOADERNOEXEC -u WINEDLLPATH
  LANG=zh_CN.UTF-8 LC_CTYPE=zh_CN.UTF-8 LC_MESSAGES=zh_CN.UTF-8
  WINEPREFIX="$WECOM_PREFIX" WINEDLLOVERRIDES="$overrides" WINEDEBUG=-all)
wine_bin="${WECOM_WINE_BIN:-/usr/bin/wine}"
test -x "$wine_bin"
if [[ -n "${WECOM_WINESERVER:-}" ]]; then
  test -x "$WECOM_WINESERVER"
  wine_env+=(WINESERVER="$WECOM_WINESERVER")
fi
runtime="${WECOM_VPROT_RUNTIME:-${XDG_DATA_HOME:-$HOME/.local/share}/wecom-runtimes/wine-11.19-vprot-e38a364b}"
if [[ "${WECOM_VPROT_FIX:-1}" != 0 ]] &&
    [[ -e "$runtime" || -n "${WECOM_VPROT_RUNTIME:-}" ]]; then
  if [[ "$runtime" == /* ]] && [[ "$(pacman -Q wine 2>/dev/null)" == 'wine 11.19-1' ]] &&
      [[ -x "$runtime/lib/wine/x86_64-unix/wine" ]] &&
      [[ ! -L "$runtime/lib/wine/x86_64-unix/wine" ]] &&
      [[ -x "$runtime/lib/wine/x86_64-unix/wine-preloader" ]] &&
      [[ ! -L "$runtime/lib/wine/x86_64-unix/wine-preloader" ]] &&
      [[ ! -L "$runtime/lib/wine/x86_64-unix/ntdll.so" ]] &&
      (cd -- "$runtime" && sha256sum --status -c "$script_dir/../configs/wine-vprot-runtime.sha256"); then
    wine_bin="$runtime/lib/wine/x86_64-unix/wine"
    wine_env+=(WINEDLLPATH=/usr/lib/wine WINESERVER=/usr/bin/wineserver)
  else
    printf '%s\n' 'WeCom vprot runtime mismatch or missing; using system Wine. Revalidate the patch after upgrading Wine.' >&2
  fi
fi
if command -v python3 >/dev/null && [[ -f "$script_dir/prepare-startup.py" ]]; then
  python3 "$script_dir/prepare-startup.py" --prefix "$WECOM_PREFIX" \
    >>"$WECOM_PREFIX/wecom-startup.log" 2>&1
fi
if [[ "${WECOM_TRAY_ICON_FIX:-1}" != 0 ]] && command -v python3 >/dev/null && [[ -f "$script_dir/tray-icon.py" ]]; then
  python3 "$script_dir/tray-icon.py" --prefix "$WECOM_PREFIX" \
    </dev/null >>"$WECOM_PREFIX/wecom-tray-icon.log" 2>&1 &
fi
if [[ "${WECOM_GNOME_MENU_FIX:-1}" != 0 && "${XDG_SESSION_TYPE:-}" == wayland && -n "${DISPLAY:-}" &&
      ":${XDG_CURRENT_DESKTOP:-}:" == *:GNOME:* ]] &&
    command -v python3 >/dev/null && [[ -f "$script_dir/gnome-menu-fix.py" ]]; then
  WECOM_PREFIX="$WECOM_PREFIX" python3 "$script_dir/gnome-menu-fix.py" \
    </dev/null >>"$WECOM_PREFIX/wecom-gnome-menu.log" 2>&1 &
fi
if [[ "${WECOM_GNOME_POPUP_FIX:-1}" != 0 && "${XDG_SESSION_TYPE:-}" == wayland && -n "${DISPLAY:-}" &&
      ":${XDG_CURRENT_DESKTOP:-}:" == *:GNOME:* ]] && [[ -f "$script_dir/gnome-popup-fix.exe" ]]; then
  "${wine_env[@]}" "$wine_bin" "$script_dir/gnome-popup-fix.exe" \
    </dev/null >>"$WECOM_PREFIX/wecom-gnome-popup.log" 2>&1 &
fi
if [[ "${WECOM_TITLEBAR_FIX:-1}" != 0 ]]; then
  test -f "$script_dir/titlebar-managed.exe"
  tray_geometry=""
  if command -v python3 >/dev/null && [[ -f "$script_dir/tray-geometry.py" ]]; then
    tray_geometry="$(python3 "$script_dir/tray-geometry.py" 2>>"$WECOM_PREFIX/wecom-titlebar.log")"
  fi
  "${wine_env[@]}" WECOM_TRAY_GEOMETRY="$tray_geometry" "$wine_bin" "$script_dir/titlebar-managed.exe" -watch \
    </dev/null >>"$WECOM_PREFIX/wecom-titlebar.log" 2>&1 &
fi
if [[ "${WECOM_IME_FIX:-1}" != 0 ]]; then
  ime_bridge="$script_dir/ime-bridge.so"
  if [[ -f "$ime_bridge" ]]; then
    # LD_PRELOAD cannot represent filenames containing spaces or colons.
    if [[ "$ime_bridge" == *[[:space:]:]* ]]; then
      printf '%s\n' 'WeCom IME bridge skipped: helper path contains whitespace or a colon.' >&2
    else
      wine_env+=(LD_PRELOAD="$ime_bridge${LD_PRELOAD:+:$LD_PRELOAD}")
    fi
  fi
fi
exec "${wine_env[@]}" "$wine_bin" "$app"
