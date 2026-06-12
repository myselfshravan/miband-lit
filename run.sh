#!/bin/sh
# Mi Band 5 live heart rate - one-command launcher.
# Cycles the Mac's Bluetooth first (frees the band / clears any wedged
# connection so it advertises), then connects and streams BPM.
#
# Usage:  ./run.sh            # stream until Ctrl-C
#         DURATION=60 ./run.sh   # stop after ~60s
#
# Make sure the band is disconnected from your phone first (phone Bluetooth
# off / airplane mode).

set -e
cd "$(dirname "$0")"

# Secrets live in config.sh (gitignored). Copy config.example.sh to start.
[ -f config.sh ] || { echo "Missing config.sh — run: cp config.example.sh config.sh  then edit it"; exit 1; }
. ./config.sh
: "${BAND_UUID:?Set BAND_UUID in config.sh}"
: "${AUTH_KEY:?Set AUTH_KEY in config.sh}"

if command -v blueutil >/dev/null 2>&1; then
  echo "Cycling Bluetooth to free the band..."
  blueutil -p 0; sleep 3; blueutil -p 1; sleep 6
fi

exec ./venv/bin/python -u heartrate.py "$BAND_UUID" "$AUTH_KEY"
