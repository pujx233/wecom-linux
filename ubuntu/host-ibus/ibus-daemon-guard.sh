#!/bin/sh
# Keep distro upgrades on the distro daemon unless every matching component agrees.
fix_dir="$HOME/.local/lib/wecom-ibus-cancel"
if [ "$(/usr/bin/dpkg-query -W -f='${Version}' ibus 2>/dev/null)" = '1.5.34~rc2-1' ] &&
   /usr/bin/sha256sum --status -c "$fix_dir/compatible.sha256"; then
    exec "$fix_dir/ibus-daemon" "$@"
fi
exec /usr/bin/ibus-daemon "$@"
