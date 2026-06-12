#!/usr/bin/env python3
"""Mi Band 5 realtime heart-rate reader for macOS.

Connects over BLE, performs the Huami authentication handshake using your
band's 16-byte auth key, starts continuous heart-rate measurement, and prints
each BPM reading as it arrives.

Usage:
    ./venv/bin/python heartrate.py <DEVICE_UUID> <AUTH_KEY_HEX>

  DEVICE_UUID   the CoreBluetooth UUID printed by scan.py
  AUTH_KEY_HEX  32 hex chars (16 bytes), from get_authkey.py / huami-token.
                A leading "0x" is fine.

You can also set them via env vars MIBAND_ADDR and MIBAND_KEY and run with
no arguments.
"""
import asyncio
import os
import sys
from Crypto.Cipher import AES
from bleak import BleakClient, BleakScanner

# --- Characteristic UUIDs -------------------------------------------------
# Huami auth characteristic (service 0000fee1-...)
UUID_AUTH = "00000009-0000-3512-2118-0009af100700"
# Standard Heart Rate service characteristics
UUID_HR_MEASURE = "00002a37-0000-1000-8000-00805f9b34fb"   # notify: BPM values
UUID_HR_CONTROL = "00002a39-0000-1000-8000-00805f9b34fb"   # write: control point
# Huami sensor characteristic - needed to keep continuous HR streaming
UUID_SENSOR = "00000001-0000-3512-2118-0009af100700"

# Auth protocol bytes
AUTH_REQ_RANDOM = b"\x02\x00"   # ask the band for a random challenge
AUTH_SEND_ENC = b"\x03\x00"     # send back the encrypted challenge

# HR control point commands
HR_STOP_MANUAL = b"\x15\x02\x00"
HR_STOP_CONT = b"\x15\x01\x00"
HR_START_CONT = b"\x15\x01\x01"
HR_START_MANUAL = b"\x15\x02\x01"   # one-shot measurement; reliably fires the LEDs
HR_PING = b"\x16"                   # keep-alive, must be sent every ~12s


def parse_key(s: str) -> bytes:
    s = s.strip().lower().removeprefix("0x")
    key = bytes.fromhex(s)
    if len(key) != 16:
        raise ValueError(f"auth key must be 16 bytes (32 hex chars), got {len(key)}")
    return key


def encrypt_challenge(key: bytes, challenge: bytes) -> bytes:
    return AES.new(key, AES.MODE_ECB).encrypt(challenge)


async def main(address: str, key: bytes):
    auth_done = asyncio.Event()
    auth_ok = False

    # macOS needs a fresh discovery to resolve the peripheral UUID before
    # connecting; connecting straight to a stale UUID raises "not found".
    print("Locating band...")
    device = await BleakScanner.find_device_by_address(address, timeout=15.0)
    if device is None:
        print("Band not found while scanning. Make sure it's free from the phone")
        print("(toggle the Mac's Bluetooth with `blueutil -p 0 && blueutil -p 1` if it")
        print("was just connected) and try again.")
        return

    async with BleakClient(device) as client:
        print(f"Connected: {client.address}")

        # --- Authentication notification handler ---
        async def auth_handler(_sender, data: bytearray):
            nonlocal auth_ok
            # Responses are prefixed with 0x10 <step> <status>
            head = bytes(data[:3])
            if head == b"\x10\x02\x01":
                # band sent us a random challenge -> encrypt and return it
                challenge = bytes(data[3:])
                enc = encrypt_challenge(key, challenge)
                await client.write_gatt_char(UUID_AUTH, AUTH_SEND_ENC + enc, response=False)
            elif head == b"\x10\x03\x01":
                print("Auth: SUCCESS")
                auth_ok = True
                auth_done.set()
            elif head == b"\x10\x03\x04":
                print("Auth: FAILED - wrong key (band rejected the challenge).")
                auth_done.set()
            else:
                print(f"Auth: unexpected response {head.hex()}")
                auth_done.set()

        await client.start_notify(UUID_AUTH, auth_handler)
        # Kick off the handshake: request a random challenge.
        await client.write_gatt_char(UUID_AUTH, AUTH_REQ_RANDOM, response=False)

        try:
            await asyncio.wait_for(auth_done.wait(), timeout=15)
        except asyncio.TimeoutError:
            print("Auth: timed out waiting for the band to respond.")
            return
        if not auth_ok:
            return

        # --- Heart rate ---
        def hr_handler(_sender, data: bytearray):
            # measurement char: byte0 = flags, byte1 = BPM
            if len(data) >= 2:
                bpm = data[1]
                print(f"HR: {bpm} bpm")

        await client.start_notify(UUID_HR_MEASURE, hr_handler)

        # MODE=manual uses one-shot measurement re-triggered on a timer (the
        # most reliable way to keep the LEDs lit). MODE=continuous (default)
        # uses the band's continuous mode.
        mode = os.environ.get("MODE", "manual").lower()

        # Always clear any previous mode first.
        await client.write_gatt_char(UUID_HR_CONTROL, HR_STOP_MANUAL, response=True)
        await client.write_gatt_char(UUID_HR_CONTROL, HR_STOP_CONT, response=True)

        if mode == "manual":
            await client.write_gatt_char(UUID_HR_CONTROL, HR_START_MANUAL, response=True)
            print("Manual heart-rate measurement started. LEDs should light now.\n")
        else:
            await client.write_gatt_char(UUID_HR_CONTROL, HR_START_CONT, response=True)
            print("Continuous heart-rate started. Wear the band snugly. Ctrl-C to stop.\n")

        # Keep-alive loop. The band needs a 0x16 ping every ~12s or it stops.
        # In manual mode we also re-issue the start to keep re-measuring.
        # Optional DURATION env var makes the script self-terminate cleanly.
        duration = float(os.environ.get("DURATION", "0")) or None
        elapsed = 0.0
        try:
            while client.is_connected:
                await asyncio.sleep(10)
                elapsed += 10
                await client.write_gatt_char(UUID_HR_CONTROL, HR_PING, response=True)
                if mode == "manual":
                    await client.write_gatt_char(UUID_HR_CONTROL, HR_START_MANUAL, response=True)
                if duration and elapsed >= duration:
                    print("Duration reached, stopping.")
                    break
        except asyncio.CancelledError:
            pass
        finally:
            try:
                await client.write_gatt_char(UUID_HR_CONTROL, HR_STOP_CONT, response=True)
                await client.write_gatt_char(UUID_HR_CONTROL, HR_STOP_MANUAL, response=True)
            except Exception:
                pass


if __name__ == "__main__":
    addr = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("MIBAND_ADDR")
    raw_key = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("MIBAND_KEY")
    if not addr or not raw_key:
        print(__doc__)
        sys.exit(1)
    try:
        asyncio.run(main(addr, parse_key(raw_key)))
    except KeyboardInterrupt:
        print("\nStopped.")
