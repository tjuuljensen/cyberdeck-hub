#!/usr/bin/env bash
set -euo pipefail
shopt -s nullglob
data_root=${CYBERDECK_ROOT:-/srv/cyberdeck}
archives=("$data_root"/zim/*.zim)
(( ${#archives[@]} > 0 )) || { echo 'No ZIM files acquired.' >&2; exit 1; }
# Omit --address: Kiwix defaults to all addresses; explicit 0.0.0.0 is rejected
# by the version installed on the first Debian test host.
exec /usr/bin/kiwix-serve --port=8080 --urlRootLocation=/kiwix/ --blockexternal "${archives[@]}"
