#!/usr/bin/env bash
set -euo pipefail
: "${WECOM_PREFIX:?Set WECOM_PREFIX to the intended WeCom prefix}"
WECOM_PREFIX="$(cd -- "$WECOM_PREFIX" && pwd -P)"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
wecom_locale=$(python3 "$script_dir/select-locale.py")
unset LC_ALL
export LANG="$wecom_locale" LC_CTYPE="$wecom_locale" LC_MESSAGES="$wecom_locale"
app="$WECOM_PREFIX/drive_c/Program Files (x86)/WXWork/WXWork.exe"
app_args=()
if [[ "${WECOM_CEF_IME_FIX:-0}" == 1 ]]; then
  # This CEF version supports IMM32; Wine's native IME updates use that interface.
  app_args+=(--disable-features=TSFImeSupport)
fi
test -f "$WECOM_PREFIX/system.reg"
test -f "$app"
overrides="$(cat "$script_dir/../configs/dll-overrides.txt")"
cd -- "$(dirname -- "$app")"
wine_env=(env -u LC_ALL -u WINEARCH -u WINESERVER -u WINELOADER -u WINELOADERNOEXEC -u WINEDLLPATH
  -u WINESERVERSOCKET
  WINEPREFIX="$WECOM_PREFIX" WINEDLLOVERRIDES="$overrides" WINEDEBUG="${WINEDEBUG:--all}")
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
if [[ "${WECOM_EMBEDDED_UI_DPI_FIX:-0}" == 1 ]]; then
  # Wine does not implement Windows' cross-process SetParent DPI reset. Start the
  # embedded mail/Flutter UIs SYSTEM_AWARE like their WeCom host, after idle-prefix recovery.
  image_options='HKLM\Software\Microsoft\Windows NT\CurrentVersion\Image File Execution Options'
  for image in WeMail.exe FlutterPlugins.exe; do
    "${wine_env[@]}" "$wine_bin" reg add "$image_options\\$image" /v dpiAwareness /t REG_DWORD /d 1 /f /reg:32
  done
  meeting_options="$image_options\\wwmapp.exe"
  if [[ "${WECOM_WINE_INITIAL_THREAD_DPI:-0}" == 1 ]]; then
    # WeMeet creates its message windows before it sets the process DPI mode.
    "${wine_env[@]}" "$wine_bin" reg add "$meeting_options" \
      /v wineInitialThreadDpiAwareness /t REG_DWORD /d 3 /f /reg:32
    if old_dpi=$("${wine_env[@]}" "$wine_bin" reg query "$meeting_options" /v dpiAwareness /reg:32 2>/dev/null) &&
        [[ "$old_dpi" =~ REG_DWORD[[:blank:]]+0x0[[:space:]]*$ ]]; then
      "${wine_env[@]}" "$wine_bin" reg delete "$meeting_options" /v dpiAwareness /f /reg:32 ||
        ! "${wine_env[@]}" "$wine_bin" reg query "$meeting_options" /v dpiAwareness /reg:32 >/dev/null 2>&1
    fi
  else
    "${wine_env[@]}" "$wine_bin" reg add "$meeting_options" /v dpiAwareness /t REG_DWORD /d 0 /f /reg:32
  fi
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
if [[ "${WECOM_IME_FIX:-1}" != 0 && "${WECOM_CEF_IME_FIX:-0}" != 1 ]]; then
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
if [[ -n "${WECOM_IBUS_XIM_HELPER:-}" ]]; then
  wine_env=(/usr/bin/python3 "$WECOM_IBUS_XIM_HELPER" "${wine_env[@]}")
fi
if [[ "${WINE_X11_OWNED_FRAME:-0}" == 1 && "${WECOM_REUSE_DESKTOP:-0}" != 1 ]]; then
  exec "${wine_env[@]}" "$wine_bin" explorer.exe /desktop 'C:\Program Files (x86)\WXWork\WXWork.exe' "${app_args[@]}"
fi
exec "${wine_env[@]}" "$wine_bin" "$app" "${app_args[@]}"
