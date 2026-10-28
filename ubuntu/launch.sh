#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export WECOM_PREFIX="${WECOM_PREFIX:-$root/prefix}"
export WECOM_WINE_BIN="$root/wine/bin/wine"
export WECOM_WINESERVER="$root/wine/bin/wineserver"
export WECOM_WIN32U_PATH="$root/wine/lib/wine/x86_64-unix/win32u.so"
export WECOM_VPROT_FIX=0
export WECOM_TRAY_ICON_FIX=0
export WECOM_GNOME_MENU_FIX=0
export WECOM_GNOME_POPUP_FIX=0
export WINE_X11_OWNED_FRAME=1
export WINE_WECOM_SHADOW_STACK=1
export WINE_WECOM_FIRST_PRESENT_ARGB=1
export WINE_X11_FIXED_TRANSIENT_ARGB=1
export WINE_X11_FIXED_TRANSIENT_UTILITY=1
export XMODIFIERS="${XMODIFIERS:-@im=ibus}"
log_dir="${WECOM_LOG_DIR:-$root/logs}"
mkdir -p -- "$log_dir"
# Match the main process's DPI mode before WeMail initializes its Qt/CEF windows.
WINEPREFIX="$WECOM_PREFIX" WINESERVER="$WECOM_WINESERVER" WINEDEBUG=-all \
  "$WECOM_WINE_BIN" reg add \
  'HKLM\Software\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\WeMail.exe' \
  /v dpiAwareness /t REG_DWORD /d 1 /f /reg:32 >>"$log_dir/launch.log" 2>&1
exec bash "$root/template/wecom-compat/scripts/launch-wecom.sh" >>"$log_dir/launch.log" 2>&1
