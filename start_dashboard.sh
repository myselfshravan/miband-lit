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

# Kill any leftover band service so we never run two at once (two services
# fighting over the band's single connection causes auth-fail / not-found churn).
if pgrep -f band_service.py >/dev/null 2>&1; then
  echo "Stopping a leftover band service..."
  pkill -f band_service.py; sleep 2
fi

if command -v blueutil >/dev/null 2>&1; then
  echo "Cycling Bluetooth to free the band..."
  blueutil -p 0; sleep 3; blueutil -p 1; sleep 6
fi

echo "Starting band service (BLE)..."
./venv/bin/python -u band_service.py "$BAND_UUID" "$AUTH_KEY" > band_service.log 2>&1 &
SERVICE_PID=$!
echo "  band service pid $SERVICE_PID (logs: band_service.log)"

# Optional: drive a WiZ bulb's colour from heart rate (skips if no bulb).
WIZ_PID=""
if [ "${WIZ_BULB:-1}" = "1" ]; then
  echo "Starting WiZ bulb sync..."
  WIZ_IP="${WIZ_IP:-}" ./venv/bin/python -u wiz_pulse.py > wiz_pulse.log 2>&1 &
  WIZ_PID=$!
  echo "  wiz sync pid $WIZ_PID (logs: wiz_pulse.log)"
fi

# Stop the background processes when the dashboard exits.
trap "echo 'Stopping...'; kill $SERVICE_PID $WIZ_PID 2>/dev/null" EXIT INT TERM

sleep 3
echo "Starting dashboard at http://localhost:8501 ..."
./venv/bin/streamlit run dashboard.py
