# I Reverse-Engineered My ₹2000 Mi Band to Read My Heart Rate Live on My Mac

**TLDR:** I cracked the Bluetooth protocol on a Mi Band 5 — auth handshake and all — to stream my live heart rate into my own code, built a real-time dashboard for it, and got it to push notifications back to my wrist. (And yeah, at the end, I made it change my smart light's color too. Couldn't help it.)

---

## On this page

- Why bother
- The auth wall (and how I got past it)
- The sensor that refused to turn on
- The bugs that nearly ended me
- The dashboard: a cockpit for my pulse
- Talking *back* to the band
- The honest part: why "per-beat" is a lie
- The garnish: my heartbeat now controls a light bulb
- The aftermath

---

## Why bother

My Mi Band 5 reads my heart rate all day and ships it to the Zepp app, where it just... sits there. You open the app, you see a number, you close the app. That's the whole experience.

I wanted that number in *my* code. Live, on my Mac, where I could actually do things with it. Not in a walled-garden app — in a terminal I control.

The band talks **Bluetooth Low Energy (BLE)**, my Mac has Bluetooth, and Python has a library called [`bleak`](https://github.com/hbldh/bleak) that speaks BLE through macOS's CoreBluetooth. So in theory: connect, find the heart-rate characteristic, subscribe, done.

In theory.

## The auth wall (and how I got past it)

The first wall hit immediately. The Mi Band 5 will happily let you *connect*, but the moment you ask for sensor data, it refuses unless you prove you know a **16-byte secret key** — one generated when Zepp first paired with the band. No key, no heartbeat.

That key lives on Xiaomi's servers, tied to your account. A great open-source tool, [`huami-token`](https://github.com/argrento/huami-token), logs into your own Zepp account and pulls the keys for your paired devices:

```sh
python huami-token/main.py --method amazfit -e you@example.com -b
```

```
Device 0:
  MAC: FF:B5:FA:EE:7C:9F, Active: Yes
  Key: 0x308b2eb4...   <-- the 16 bytes I needed
```

Now I had to actually *use* it. The Mi Band auth is an AES challenge-response:

1. Ask the band for a random number.
2. The band sends 16 random bytes.
3. Encrypt them with the auth key (AES-128-ECB) and send them back.
4. If your result matches what the band expected → `Auth: SUCCESS`.

```python
from Crypto.Cipher import AES
# band sends a random challenge; we encrypt it with the key and send it back
enc = AES.new(auth_key, AES.MODE_ECB).encrypt(challenge)
await client.write_gatt_char(AUTH_CHAR, b"\x03\x00" + enc)
```

Small thing that cost me time: the auth characteristic only accepts *write-without-response*. My writes kept getting rejected with "Write Not Permitted" until I dumped the band's full GATT table and noticed the property. One flag. Fixed it. First `Auth: SUCCESS` felt great.

## The sensor that refused to turn on

Authenticated. Now just start the heart-rate stream — the protocol says write `0x15 0x01 0x01` to the control characteristic for "continuous mode," subscribe to notifications, done.

I ran it. The terminal filled up with:

```
HR: 0 bpm
HR: 0 bpm
HR: 0 bpm
```

Zero. For fifty straight seconds. The band was *sending* readings — it just thought I had no pulse. I flipped it over: the green optical-sensor LEDs on the back were **off**. The "continuous" command was accepted but never actually powered the sensor on.

After far too long, the fix: on this firmware, the *manual* measurement command (`0x15 0x02 0x01`) is what physically fires the LEDs. Switched to it:

```
Auth: SUCCESS
HR: 95 bpm
HR: 94 bpm
HR: 94 bpm
```

**95 bpm, live, off a band I bought for the price of two biryanis.** Genuinely one of the better moments of the week.

## The bugs that nearly ended me

This is the part the tutorials skip.

**The band ghosts you.** The Mi Band only allows *one* BLE connection at a time. While it's paired to your phone, your Mac can't even see it advertising. Fix: turn the phone's Bluetooth off. Obvious in hindsight; two confused scans in foresight.

**macOS wedges the connection.** Kill a script mid-connection and macOS's `bluetoothd` keeps the band held open at the OS level — so it neither advertises nor accepts new connections. It just disappears. The fix is gloriously dumb: toggle the Mac's Bluetooth off and on to force-drop everything. I now do it automatically on launch.

**The bug that made me question reality.** My logs started looping forever:

```
Connected → Auth failed → not found → Connected → Auth failed → ...
```

I'd changed nothing. Turned out a test process I *thought* I'd killed was still alive — so two scripts were fighting over the band's single connection. One would grab it, the other would corrupt the handshake, both lost, repeat. Two hours gone to a process I forgot to `kill`. I added a hard single-instance lock and it never happened again.

## The dashboard: a cockpit for my pulse

A number in a terminal is cool, but I wanted to *watch* it. So I split the project into two pieces sharing a tiny SQLite database:

- a **band service** that owns the one precious BLE connection and streams heart rate into the DB, and
- everything else, which just reads from that DB.

This matters more than it sounds: BLE allows one connection, and Streamlit re-runs its whole script top-to-bottom on every interaction — it can't hold a live connection. Decoupling through SQLite means the dashboard, the terminal feed, anything, can read the data without ever touching Bluetooth.

Then I built a **Streamlit dashboard**: a live heart-rate chart, current/min/max/average, connection status, and a sidebar to fire actions at the band. Now I had a real cockpit for my own pulse.

## Talking *back* to the band

Reading data stopped being enough. Could I send things *to* the band?

The Mi Band 5 quietly implements the standard Bluetooth **Alert Notification Service**. Write `[category, count] + text` to one characteristic and a notification appears *on the band's screen*; write `0x02` to another and it vibrates.

```python
# this literally makes text show up on your wrist
msg = bytes([0x05, 0x01]) + "Hello from your Mac".encode()
await client.write_gatt_char(NEW_ALERT_CHAR, msg)
```

I fired a message from my laptop and watched it appear on my wrist while the band buzzed. Now it's a two-way channel — my Mac reads my heartbeat *and* can tap me on the shoulder. (Which means anything with an API can now buzz my wrist. Build finished? Buzz. That idea is going somewhere.)

## The honest part: why "per-beat" is a lie

I wanted more precision — per-beat readings, a new value for every single heartbeat. So I ran eight different tests trying to crank up the sample rate, and hit a wall no amount of code could fix:

**The Mi Band 5 doesn't expose individual heartbeats.** It reports an *averaged* BPM number — there's no inter-beat (RR-interval) data over BLE. And even that comes in flaky bursts: the band runs a ~15–20 second measurement session, then stops. Sending a `STOP` to restart it reliably *kills* the stream instead. Moody little device.

Realistic ceiling: about **one reading every few seconds.** Not per-beat. Sometimes not even per-second. Worth knowing before you build anything that assumes a smooth feed — the band simply doesn't give you one. (If you genuinely need beat-level data, that's chest-strap territory, like a Polar H10.)

The fix wasn't more data — it was presenting the data I had better, which brings me to the fun part.

## The garnish: my heartbeat now controls a light bulb

I had an old project lying around — [wiz-hack](https://github.com/myselfshravan/wiz-hack), where I'd reverse-engineered my Philips Wiz smart bulb (it just listens for JSON on a UDP port). So with a live heart rate already streaming into SQLite, this was basically free.

I reused the same `WizLight` class and mapped BPM to color: **green when I'm calm, red when my heart's racing**, sliding through yellow and orange between.

```python
def bpm_to_rgb(bpm, low, high):
    t = max(0, min(1, (bpm - low) / (high - low)))
    hue = (120 * (1 - t)) / 360.0   # 120°=green (calm) → 0°=red (spiked)
    r, g, b = colorsys.hsv_to_rgb(hue, 1, 1)
    return int(r*255), int(g*255), int(b*255)
```

Two small touches made it actually look good. Since the band only updates every few seconds, I made the bulb **ease** smoothly toward each new color at 12fps, so it glides instead of snapping. And I **auto-scale** the color range to my recent heart rate — otherwise my resting 83–109 bpm got squashed into one identical shade of yellow-green and the light looked frozen.

Did some jumping jacks, watched my room go red, sat down, watched it cool back to green. The band, the Mac, and the bulb, all in one loop. A ridiculous garnish on an already-ridiculous project — and the most fun 20 minutes of the whole thing.

## The aftermath

A simple "I just want my heart rate on my Mac" idea turned into a full reverse-engineered BLE pipeline: cracking the auth handshake, fighting the sensor, surviving the Bluetooth gremlins, a live dashboard, and two-way notifications — with a heartbeat-controlled light bulb on top for good measure.

All the code is here: **[myselfshravan/miband-lit](https://github.com/myselfshravan/miband-lit)**.

Huge thanks to [`huami-token`](https://github.com/argrento/huami-token) for the auth-key extraction and to the [Gadgetbridge](https://gadgetbridge.org/) project, whose protocol reverse-engineering made all of this possible.

If you made it this far — go poke at something you own. There's a surprising amount just sitting there, waiting to be talked to. 🫀

---

#bluetooth #miband #python #reverseengineering #ble #iot #buildinpublic #smarthome #wizlight
