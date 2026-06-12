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
colour in real time: **green** at rest → yellow → **red** when it climbs. The
bulb sync starts automatically with `./start_dashboard.sh` (set
`WIZ_BULB=0` to skip it), or run it standalone alongside the band service:

```sh
./venv/bin/python wiz_pulse.py            # auto-discovers bulb + auto-scales range
WIZ_IP=192.168.1.4 ./venv/bin/python wiz_pulse.py
HR_LOW=80 HR_HIGH=115 ./venv/bin/python wiz_pulse.py   # fixed range overrides auto
```

By default the colour range **auto-scales** to your recent HR (last 3 min), so
the full green→red sweep always maps onto your actual fluctuation. A fixed wide
range like 50–150 would squash a resting HR (say 83–109) into one yellow-green
colour — making the bulb look stuck. Set `HR_LOW`/`HR_HIGH` to pin a fixed range.

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

- **Two HR modes, both flaky.** `MODE=manual` fires the sensor in short
  bursts; `MODE=continuous` (the dashboard default) streams real values about
  every 3s. Either way the band runs a ~15–20s measurement *session* then
  stops. Re-issuing `START` re-kicks it; issuing `STOP` mid-session reliably
  kills the stream, so the service never sends `STOP` while running.
- **Cadence ceiling ≈ one reading every few seconds — NOT per-beat.** The Mi
  Band 5 reports an *averaged BPM*, not individual beat timing (no RR-interval
  data over BLE), and even that arrives in unreliable bursts. True per-beat is
  not possible with this hardware.
- **Smoothing fills the gaps.** `wiz_pulse.py` eases the bulb colour toward the
  latest reading at ~12 fps (`WIZ_FPS` / `WIZ_EASE`), so the light *glides*
  between sparse readings and looks continuous even though the data is coarse.

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
