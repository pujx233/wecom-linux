#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export WECOM_PREFIX="${WECOM_PREFIX:-$root/prefix}"
export WECOM_WINE_BIN="$root/wine/bin/wine"
export WECOM_WINESERVER="$root/wine/bin/wineserver"
export WECOM_WIN32U_PATH="$root/wine/lib/wine/x86_64-unix/win32u.so"
export WECOM_VPROT_FIX=0
export WECOM_EMBEDDED_UI_DPI_FIX=1
export WECOM_TRAY_ICON_FIX=0
export WECOM_GNOME_MENU_FIX=0
export WECOM_GNOME_POPUP_FIX=0
export WINE_X11_OWNED_FRAME=1
export WINE_X11_FRAME_DECORATION_CLASSES=PerryShadowWnd
export WINE_WECOM_SHADOW_STACK=1
export WINE_WECOM_FIRST_PRESENT_ARGB=1
export WINE_X11_FIXED_TRANSIENT_ARGB=1
export WINE_X11_FIXED_TRANSIENT_UTILITY=1
export XMODIFIERS="${XMODIFIERS:-@im=ibus}"
log_dir="${WECOM_LOG_DIR:-$root/logs}"
mkdir -p -- "$log_dir"
exec bash "$root/template/wecom-compat/scripts/launch-wecom.sh" >>"$log_dir/launch.log" 2>&1
