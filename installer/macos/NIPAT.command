#!/bin/sh
set -eu
resources=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
status=0
"$resources/python/bin/python3.12" -I -B "$resources/app/installer/macos/launch.py" "$@" || status=$?
if [ "$status" -ne 0 ] && [ -t 0 ]; then
    printf '\nNIPAT non ha completato il comando. Premere Invio per chiudere.\n'
    read -r answer || true
fi
exit "$status"
