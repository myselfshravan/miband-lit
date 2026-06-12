#!/usr/bin/env python3
"""Long-running Mi Band 5 service.

Owns the single BLE connection: authenticates, streams heart rate into the
shared SQLite store, and drains the commands table (notifications / vibrate)
to the band. The Streamlit dashboard never touches BLE - it only reads
readings and writes commands, which this process picks up.

Usage:
    ./venv/bin/python band_service.py <DEVICE_UUID> <AUTH_KEY_HEX>
    (or set MIBAND_ADDR / MIBAND_KEY env vars)
"""
import asyncio
import fcntl
import os
import sys
import time
from pathlib import Path

from Crypto.Cipher import AES
from bleak import BleakClient, BleakScanner

import store

LOCK_PATH = Path(__file__).with_name(".band_service.lock")


def acquire_singleton_lock():
    """Ensure only one band service runs at a time.

    Two services fighting over the band's single BLE connection causes the
    'Auth failed -> not found -> connected' churn, so we hard-block a second
    instance. Returns the lock file handle (keep it alive for the process).
    """
    fh = open(LOCK_PATH, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Another band_service is already running (lock held). Exiting.")
        print("If that's wrong, run:  pkill -f band_service.py")
        sys.exit(1)
    fh.write(str(os.getpid()))
    fh.flush()
    return fh

# --- Characteristic UUIDs ---
UUID_AUTH = "00000009-0000-3512-2118-0009af100700"
UUID_HR_MEASURE = "00002a37-0000-1000-8000-00805f9b34fb"
UUID_HR_CONTROL = "00002a39-0000-1000-8000-00805f9b34fb"
UUID_NEW_ALERT = "00002a46-0000-1000-8000-00805f9b34fb"   # ANS text notification
UUID_IMMEDIATE_ALERT = "00002a06-0000-1000-8000-00805f9b34fb"  # vibrate only

AUTH_REQ_RANDOM = b"\x02\x00"
AUTH_SEND_ENC = b"\x03\x00"
HR_STOP_MANUAL = b"\x15\x02\x00"
HR_STOP_CONT = b"\x15\x01\x00"
HR_START_MANUAL = b"\x15\x02\x01"
HR_START_CONT = b"\x15\x01\x01"
HR_PING = b"\x16"

# Alert Notification Service category ids
ALERT_CATEGORIES = {
    "email": 0x01,
    "call": 0x03,
    "missed_call": 0x04,
    "sms": 0x05,
    "simple": 0x00,
}


def parse_key(s: str) -> bytes:
    key = bytes.fromhex(s.strip().lower().removeprefix("0x"))
    if len(key) != 16:
        raise ValueError(f"auth key must be 16 bytes, got {len(key)}")
    return key


async def authenticate(client: BleakClient, key: bytes) -> bool:
    done = asyncio.Event()
    ok = False

    async def handler(_sender, data: bytearray):
        nonlocal ok
        head = bytes(data[:3])
        if head == b"\x10\x02\x01":
            enc = AES.new(key, AES.MODE_ECB).encrypt(bytes(data[3:]))
            await client.write_gatt_char(UUID_AUTH, AUTH_SEND_ENC + enc, response=False)
        elif head == b"\x10\x03\x01":
            ok = True
            done.set()
        else:
            done.set()

    await client.start_notify(UUID_AUTH, handler)
    await client.write_gatt_char(UUID_AUTH, AUTH_REQ_RANDOM, response=False)
    try:
        await asyncio.wait_for(done.wait(), timeout=15)
    except asyncio.TimeoutError:
        return False
    return ok


async def handle_command(client: BleakClient, kind: str, payload: dict):
    if kind == "vibrate":
        # Immediate Alert: 0x02 = high alert (strong buzz), 0x01 = mild.
        level = 0x02 if payload.get("strong", True) else 0x01
        await client.write_gatt_char(UUID_IMMEDIATE_ALERT, bytes([level]), response=False)
    elif kind == "notify":
        category = ALERT_CATEGORIES.get(payload.get("category", "sms"), 0x05)
        text = str(payload.get("text", ""))[:80]  # keep within a single write
        msg = bytes([category, 0x01]) + text.encode("utf-8", errors="ignore")
        await client.write_gatt_char(UUID_NEW_ALERT, msg, response=True)
    elif kind == "stop_vibrate":
        await client.write_gatt_char(UUID_IMMEDIATE_ALERT, b"\x00", response=False)
    else:
        print(f"Unknown command kind: {kind}")


async def run_session(address: str, key: bytes):
    store.set_status("connection", "scanning")
    print("Locating band...")
    device = await BleakScanner.find_device_by_address(address, timeout=15.0)
    if device is None:
        store.set_status("connection", "not_found")
        print("Band not found while scanning.")
        return

    async with BleakClient(device) as client:
        print(f"Connected: {client.address}")
        store.set_status("connection", "connected")

        if not await authenticate(client, key):
            print("Auth failed.")
            store.set_status("connection", "auth_failed")
            return
        print("Auth: SUCCESS")
        store.set_status("connection", "authenticated")

        def hr_handler(_sender, data: bytearray):
            if len(data) >= 2 and data[1] > 0:
                bpm = data[1]
                store.add_reading(bpm)
                store.set_status("last_bpm", bpm)
                store.set_status("last_seen", time.time())
                print(f"HR: {bpm} bpm")

        await client.start_notify(UUID_HR_MEASURE, hr_handler)
        mode = os.environ.get("MODE", "manual").lower()
        await client.write_gatt_char(UUID_HR_CONTROL, HR_STOP_MANUAL, response=True)
        await client.write_gatt_char(UUID_HR_CONTROL, HR_STOP_CONT, response=True)
        if mode == "continuous":
            await client.write_gatt_char(UUID_HR_CONTROL, HR_START_CONT, response=True)
        else:
            await client.write_gatt_char(UUID_HR_CONTROL, HR_START_MANUAL, response=True)
        print(f"Heart-rate measurement started (mode={mode}).")

        # Two concurrent loops: HR keepalive, and command draining.
        # The band runs a ~15-20s measurement session then stops, so we ping
        # to keep it alive and restart the session periodically for coverage.
        start_cmd = HR_START_CONT if mode == "continuous" else HR_START_MANUAL
        stop_cmd = HR_STOP_CONT if mode == "continuous" else HR_STOP_MANUAL
        ping_every = float(os.environ.get("HR_PING_EVERY", "10"))
        restart_every = float(os.environ.get("HR_RESTART", "14"))

        async def hr_loop():
            tick = 2.0
            t = last_ping = last_restart = 0.0
            while client.is_connected:
                await asyncio.sleep(tick)
                t += tick
                if t - last_ping >= ping_every:
                    await client.write_gatt_char(UUID_HR_CONTROL, HR_PING, response=True)
                    last_ping = t
                if t - last_restart >= restart_every:
                    # Re-kick the measurement WITHOUT a STOP first — issuing STOP
                    # mid-session reliably kills the stream on this firmware.
                    await client.write_gatt_char(UUID_HR_CONTROL, start_cmd, response=True)
                    last_restart = t

        async def command_loop():
            while client.is_connected:
                for cmd_id, kind, payload in store.pending_commands():
                    try:
                        await handle_command(client, kind, payload)
                        store.mark_command(cmd_id, "done")
                        print(f"Sent command #{cmd_id}: {kind} {payload}")
                    except Exception as e:
                        store.mark_command(cmd_id, "error")
                        print(f"Command #{cmd_id} failed: {e}")
                await asyncio.sleep(1)

        try:
            await asyncio.gather(hr_loop(), command_loop())
        except asyncio.CancelledError:
            pass
        finally:
            store.set_status("connection", "disconnected")
            try:
                await client.write_gatt_char(UUID_HR_CONTROL, HR_STOP_MANUAL, response=True)
            except Exception:
                pass


async def main(address: str, key: bytes):
    store.init_db()
    # Reconnect automatically if the link drops.
    while True:
        try:
            await run_session(address, key)
        except Exception as e:
            print(f"Session error: {e}")
            store.set_status("connection", "error")
        print("Reconnecting in 8s... (Ctrl-C to quit)")
        await asyncio.sleep(8)


if __name__ == "__main__":
    addr = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("MIBAND_ADDR")
    raw_key = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("MIBAND_KEY")
    if not addr or not raw_key:
        print(__doc__)
        sys.exit(1)
    _lock = acquire_singleton_lock()  # held for the life of the process
    try:
        asyncio.run(main(addr, parse_key(raw_key)))
    except KeyboardInterrupt:
        print("\nService stopped.")
