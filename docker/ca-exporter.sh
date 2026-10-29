#!/bin/sh
set -eu

source_certificate=/caddy-data/caddy/pki/authorities/local/root.crt
destination_certificate=/public-ca/root.crt

while :; do
    if [ -s "$source_certificate" ] && ! cmp -s "$source_certificate" "$destination_certificate" 2>/dev/null; then
        temporary=/public-ca/.root.crt.tmp
        cp "$source_certificate" "$temporary"
        chmod 0644 "$temporary"
        mv -f "$temporary" "$destination_certificate"
    fi
    sleep 2
done
