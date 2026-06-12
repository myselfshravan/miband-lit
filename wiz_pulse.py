#!/usr/bin/env python3
"""Drive a WiZ smart bulb's colour from your live heart rate.

Reads the latest BPM from the shared store (written by band_service.py) and
maps it to a colour: green at rest, through yellow/orange, to red when your
heart rate climbs. Run it alongside the band service.

    ./venv/bin/python wiz_pulse.py            # auto-discover the bulb
    WIZ_IP=192.168.1.42 ./venv/bin/python wiz_pulse.py

Tune the range with HR_LOW / HR_HIGH env vars (defaults 50 / 150 bpm).

The WizLight class is reused from my wiz-hack project
(https://github.com/myselfshravan/wiz-hack) — WiZ bulbs take JSON over UDP:38899.
"""
import colorsys
import json
import os
import socket
import time

import store


class WizLight:
    def __init__(self, ip=None):
        self.ip = ip
        self.port = 38899

    def send_command(self, method, params=None):
        message = {"id": 1, "method": method, "params": params or {}}
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            if self.ip:
                sock.sendto(json.dumps(message).encode(), (self.ip, self.port))
                sock.settimeout(1)
                try:
                    response, _ = sock.recvfrom(1024)
                    return json.loads(response.decode())
                except socket.timeout:
                    return {"error": "No response from light"}
            else:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.sendto(json.dumps(message).encode(), ("255.255.255.255", self.port))
                lights = []
                sock.settimeout(2)
                while True:
                    try:
                        response, addr = sock.recvfrom(1024)
                        lights.append({"ip": addr[0], "response": json.loads(response.decode())})
                    except socket.timeout:
                        break
                return lights
        finally:
            sock.close()

    def set_color(self, r, g, b, brightness=100):
        return self.send_command(
            "setPilot", {"r": r, "g": g, "b": b, "dimming": int(brightness)}
        )


def discover_ip():
    found = WizLight().send_command("getPilot")
    if isinstance(found, list) and found:
        ip = found[0]["ip"]
        print(f"Discovered WiZ bulb at {ip}")
        return ip
    return None


def bpm_to_rgb(bpm: int, low: float, high: float):
    """Map BPM to RGB. low->green (hue 120), high->red (hue 0),
    passing through yellow/orange. Higher heart rate = redder."""
    t = max(0.0, min(1.0, (bpm - low) / (high - low)))
    hue = (120 * (1 - t)) / 360.0          # 120deg (green) down to 0deg (red)
    r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
    return int(r * 255), int(g * 255), int(b * 255)


MIN_SPAN = 16.0  # don't map a tiny HR range across the whole gradient


def auto_range(fallback):
    """Derive the colour range from recent HR so the full green->red sweep
    maps onto your actual fluctuation (a fixed 50-150 squashes a resting HR
    into one colour). Returns (low, high)."""
    vals = [b for _, b in store.recent_readings(180)]
    if len(vals) < 3:
        return fallback
    lo, hi = float(min(vals)), float(max(vals))
    if hi - lo < MIN_SPAN:
        mid = (hi + lo) / 2
        lo, hi = mid - MIN_SPAN / 2, mid + MIN_SPAN / 2
    return lo, hi


def main():
    store.init_db()
    # If HR_LOW/HR_HIGH are set, use them fixed. Otherwise auto-scale.
    env_low, env_high = os.environ.get("HR_LOW"), os.environ.get("HR_HIGH")
    auto = env_low is None and env_high is None
    low = float(env_low) if env_low else 70.0
    high = float(env_high) if env_high else 110.0

    fps = float(os.environ.get("WIZ_FPS", "12"))
    ease = float(os.environ.get("WIZ_EASE", "0.15"))   # 0..1 per frame
    dt = 1.0 / fps

    ip = os.environ.get("WIZ_IP") or discover_ip()
    if not ip:
        print("No WiZ bulb found. Make sure it's on the same Wi-Fi, or set WIZ_IP.")
        return
    bulb = WizLight(ip)
    mode = "auto-scaling" if auto else f"{int(low)}-{int(high)} bpm"
    print(f"Gliding bulb {ip} to heart rate ({mode}, green->red). Ctrl-C to stop.")

    # The displayed colour eases toward the target so the light flows smoothly
    # between sparse readings instead of snapping.
    cur = [0.0, 255.0, 0.0]    # start green (resting)
    last_bpm = None
    frame = 0
    while True:
        # Refresh the auto range every ~5s so it tracks your current HR band.
        if auto and frame % int(fps * 5) == 0:
            low, high = auto_range((low, high))
        frame += 1

        reading = store.latest_reading()
        fresh = reading and (time.time() - reading[0] < 20)
        if fresh:
            bpm = reading[1]
            target = bpm_to_rgb(bpm, low, high)
            if bpm != last_bpm:
                print(f"{bpm} bpm  [{int(low)}-{int(high)}]  -> rgb{target}")
                last_bpm = bpm
        else:
            target = (40, 0, 80)   # dim purple = no fresh data

        # Ease each channel a fraction toward the target every frame.
        cur = [c + (t - c) * ease for c, t in zip(cur, target)]
        bulb.set_color(int(cur[0]), int(cur[1]), int(cur[2]), 100)
        time.sleep(dt)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
