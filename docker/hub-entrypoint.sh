#!/bin/sh
set -eu

python -c 'import webapp; webapp.sync_kiwix_index()'
exec "$@"
