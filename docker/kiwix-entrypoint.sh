#!/bin/sh
set -eu

index=/srv/cyberdeck/kiwix-index.txt
library_dir=/tmp/kiwix
library="$library_dir/library.xml"
mkdir -p "$library_dir"

rebuild_library() {
    candidate="$library_dir/.library-$$.xml"
    rm -f "$candidate"
    printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?><library version="20110515"></library>' > "$candidate"
    if [ -f "$index" ]; then
        while IFS= read -r filename; do
            case "$filename" in
                ''|*[!A-Za-z0-9._-]*|.*) continue ;;
                *.zim) ;;
                *) continue ;;
            esac
            [ -f "/srv/cyberdeck/zim/$filename" ] || continue
            [ ! -L "/srv/cyberdeck/zim/$filename" ] || continue
            kiwix-manage "$candidate" add "/srv/cyberdeck/zim/$filename"
        done < "$index"
    fi
    mv -f "$candidate" "$library"
}

rebuild_library
if [ -f "$index" ]; then
    last_index=$(cksum "$index")
else
    last_index=missing
fi
kiwix-serve --port=8080 --urlRootLocation=/kiwix/ --blockexternal \
    --library "$library" --monitorLibrary &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true; wait "$server_pid" 2>/dev/null || true; exit 0' INT TERM

while :; do
    if ! kill -0 "$server_pid" 2>/dev/null; then
        wait "$server_pid"
        exit $?
    fi
    if [ -f "$index" ]; then
        current_index=$(cksum "$index")
    else
        current_index=missing
    fi
    if [ "$current_index" != "$last_index" ]; then
        rebuild_library
        last_index=$current_index
    fi
    sleep 3
done
