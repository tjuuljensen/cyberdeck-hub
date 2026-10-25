#!/usr/bin/env bash
set -euo pipefail

data_root=${CYBERDECK_ROOT:-/srv/cyberdeck}
private_root=${CYBERDECK_PRIVATE:-$data_root/private}
install -d -o cyberdeck -g cyberdeck -m 0755 "$data_root" "$data_root/zim" "$data_root/public"
install -d -o cyberdeck -g cyberdeck -m 0700 "$private_root"

session_key=${CYBERDECK_SESSION_KEY_FILE:-$private_root/session.key}
if [[ ! -s $session_key ]]; then
    umask 077
    openssl rand -out "$session_key" 48
    chown cyberdeck:cyberdeck "$session_key"
    chmod 0600 "$session_key"
fi
export CYBERDECK_SESSION_KEY_FILE=$session_key

exec /usr/bin/supervisord -n -c /etc/supervisor/supervisord.conf
