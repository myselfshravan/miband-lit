#!/bin/sh
# Start the Mi Band 5 dashboard: band service (BLE) + Streamlit UI.
# Make sure the band is disconnected from your phone first.

set -e
cd "$(dirname "$0")"

# Secrets live in config.sh (gitignored). Copy config.example.sh to start.
[ -f config.sh ] || { echo "Missing config.sh — run: cp config.example.sh config.sh  then edit it"; exit 1; }
. ./config.sh
: "${BAND_UUID:?Set BAND_UUID in config.sh}"
: "${AUTH_KEY:?Set AUTH_KEY in config.sh}"

# Kill any leftover processes so we never run two at once (two band services
# fighting over the band's single connection causes auth-fail / not-found churn).
pkill -f band_service.py >/dev/null 2>&1 && sleep 2
pkill -f wiz_pulse.py >/dev/null 2>&1 || true
pkill -f "streamlit run dashboard.py" >/dev/null 2>&1 || true

if command -v blueutil >/dev/null 2>&1; then
  echo "Cycling Bluetooth to free the band..."
  blueutil -p 0; sleep 3; blueutil -p 1; sleep 6
fi

# Band service (BLE), WiZ bulb sync, and Streamlit all run in the background
# and log to files. The live hacker-feed console takes the foreground terminal.
MODE="${MODE:-continuous}" ./venv/bin/python -u band_service.py "$BAND_UUID" "$AUTH_KEY" > band_service.log 2>&1 &
SERVICE_PID=$!

WIZ_PID=""
if [ "${WIZ_BULB:-1}" = "1" ]; then
  WIZ_IP="${WIZ_IP:-}" ./venv/bin/python -u wiz_pulse.py > wiz_pulse.log 2>&1 &
  WIZ_PID=$!
fi

./venv/bin/streamlit run dashboard.py --server.headless true > streamlit.log 2>&1 &
STREAMLIT_PID=$!

# Stop everything when the console exits.
trap "echo 'Stopping...'; kill $SERVICE_PID $WIZ_PID $STREAMLIT_PID 2>/dev/null" EXIT INT TERM

# Foreground: the live terminal feed (the star of the demo).
sleep 2
exec ./venv/bin/python -u console.py
