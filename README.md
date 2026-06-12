# miband-lit ⌚️❤️

Read your **Mi Band 5's heart rate live on your Mac** over Bluetooth LE — with a
Streamlit dashboard, and the ability to push text notifications and vibrations
to the band. No Zepp app needed once it's working.

## Setup

```sh
git clone https://github.com/myselfshravan/miband-lit.git
cd miband-lit
python3 -m venv venv
./venv/bin/python -m pip install -r requirements.txt

# Get the auth-key extractor (used once, see below)
git clone https://github.com/argrento/huami-token.git
./venv/bin/python -m pip install loguru

# Your secrets go here (gitignored)
cp config.example.sh config.sh   # then edit with your UUID + auth key
```

Everything runs in the local `venv/`. Run scripts with `./venv/bin/python ...`.

## One-time: get your band's auth key

The band won't stream sensor data until you authenticate with the 16-byte key
that was created when Zepp first paired it. `huami-token` pulls it from your
Zepp account.

```sh
# You log in to YOUR Zepp account; it talks to Zepp's servers, not me.
./venv/bin/python huami-token/main.py --method amazfit -e you@example.com -b
```

It prompts for your Zepp password, then prints each paired device:

```
Device 0:
  MAC: C8:0F:xx:xx:xx:xx, Active: Yes
  Key: 0xagh4d8e1...   <-- this 32-hex-char value is your auth key
```

Copy the key (the part after `0x`). It does not change unless you re-pair the
band, so you only do this once.

## Each time you want to read HR — the easy way

1. **Free the band from your phone** — it only talks to one device at a time.
   Turn Bluetooth OFF on the phone (airplane mode is surest). Just closing
   Zepp is usually not enough.

2. **Run the launcher** (it cycles the Mac's Bluetooth to free the band, then
   connects and streams):

   ```sh
   ./run.sh                 # stream until Ctrl-C
   DURATION=60 ./run.sh     # stop after ~60 seconds
   ```

   Wear the band snugly. You'll see `Auth: SUCCESS`, the green sensor LEDs
   light up, then `HR: NN bpm` lines (~one every several seconds).

Your band's UUID and auth key are already baked into `run.sh`.

## Dashboard (live chart + send notifications)

A Streamlit dashboard shows a live heart-rate chart and lets you push text
notifications and vibrations to the band.

```sh
./start_dashboard.sh
```

This cycles Bluetooth, starts the **band service** (which owns the BLE
connection and writes to `miband.db`), then opens the dashboard at
http://localhost:8501. Stop everything with Ctrl-C in that terminal.

Architecture (why two processes):
- `band_service.py` holds the single BLE connection, streams HR into a shared
  SQLite DB (`miband.db`), and drains a commands table.
- `dashboard.py` (Streamlit) only reads the DB and writes commands. It never
  touches Bluetooth — Streamlit reruns top-to-bottom on every click and can't
  hold a live connection, and the band only allows one connection anyway.

What the dashboard can do:
- Live BPM chart (adjustable window), current/min/max/average, connection status.
- **Send notification** — text shows on the band's screen. The "type" picks the
  ANS category (sms/call/email/…), which changes the icon. Keep it short
  (~80 chars max — it's a single BLE write, no chunking).
- **Vibrate band** — buzzes it (handy as a "find my band" ping).

Band service log: `band_service.log`. It auto-reconnects if the link drops.

## ⚡ Heart rate → WiZ bulb colour

If you have a WiZ smart bulb on the same Wi-Fi, your heart rate drives its
colour in real time: calm **blue** at rest → green → yellow → **red** when it
climbs. The bulb sync starts automatically with `./start_dashboard.sh` (set
`WIZ_BULB=0` to skip it), or run it standalone alongside the band service:

```sh
./venv/bin/python wiz_pulse.py            # auto-discovers the bulb
WIZ_IP=192.168.1.4 ./venv/bin/python wiz_pulse.py
HR_LOW=55 HR_HIGH=140 ./venv/bin/python wiz_pulse.py   # tune the range
```

It just reads the latest BPM from `miband.db` and sends UDP colour commands to
the bulb (WiZ listens on port 38899). The `WizLight` class is reused from my
[wiz-hack](https://github.com/myselfshravan/wiz-hack) project.

### Hook anything else into the band

The same store is a clean integration point in both directions:

```python
import store
# Outbound: buzz your wrist from any script / webhook / cron
store.add_command("notify", {"text": "Deploy finished ✅", "category": "sms"})
# Inbound: react to live heart rate
ts, bpm = store.latest_reading()
```

So AI-token-usage alerts, CI notifications, or anything with an API can push to
the band, and anything can react to your heart rate.

## What actually works (notes from setup)

- **MODE=manual is the default and the one that works.** On this band's
  firmware, the "continuous" HR command is accepted but never powers the
  optical sensor (LEDs stay off, readings are all 0). Manual measurement,
  re-triggered on a timer, is what fires the sensor. Override with
  `MODE=continuous ./venv/bin/python heartrate.py ...` if you ever want to test.
- **Cadence:** manual mode yields a reading roughly every 5–10s, not truly
  per-second. Good enough for live monitoring; per-second isn't available
  without the sensor engaging in continuous mode.

## Manual invocation (without the launcher)

```sh
./venv/bin/python scan.py                          # find the band's UUID
./venv/bin/python heartrate.py <UUID> <AUTH_KEY>   # MODE=manual by default
```

## Troubleshooting

- **`Auth: FAILED - wrong key`** — key is wrong or band was re-paired. Re-run
  huami-token. Make sure you copied the value *after* `0x` and dropped the `0x`.
- **`Auth: timed out`** — usually the band is still bonded to the phone, or it
  reconnected to Zepp mid-handshake. Kill Zepp / phone Bluetooth and retry.
- **scan.py shows nothing / "Band not found"** — the band isn't advertising.
  Either the phone is holding it (turn phone Bluetooth off), or the Mac has a
  wedged half-open connection from a previous run. Fix the Mac side with:
  `blueutil -p 0 && sleep 3 && blueutil -p 1` (the launcher does this for you).
  Also confirm macOS has Bluetooth permission for your terminal app
  (System Settings → Privacy & Security → Bluetooth).
- **Connect hangs with no output** — almost always the phone re-grabbed the
  band, or a wedged Mac connection. Cycle the Mac's Bluetooth and retry.
- **Connects but no HR values** — make sure the band is actually on your wrist;
  the optical sensor won't fire in open air.
```
