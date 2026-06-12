# Copy this to config.sh and fill in your own values.
#   cp config.example.sh config.sh
#
# BAND_UUID: the CoreBluetooth UUID printed by `./venv/bin/python scan.py`
#            (macOS shows a per-Mac UUID, not the band's MAC address).
# AUTH_KEY : your band's 16-byte auth key (32 hex chars), extracted with
#            huami-token from your Zepp account. See README.
BAND_UUID="XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"
AUTH_KEY="00000000000000000000000000000000"

# Optional: WiZ smart bulb IP for the heart-rate-to-light feature.
# Leave empty to auto-discover on the network.
WIZ_IP=""
