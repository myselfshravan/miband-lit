#!/usr/bin/env python3
"""Scan for nearby BLE devices and highlight anything that looks like a Mi Band.

On macOS the 'address' is a CoreBluetooth UUID (not a MAC). Copy the UUID of
your band and use it as MIBAND_ADDR for the other scripts.
"""
import asyncio
from bleak import BleakScanner

# Standard Heart Rate service - Mi Band advertises it.
HR_SERVICE = "0000180d-0000-1000-8000-00805f9b34fb"


async def main():
    print("Scanning for 10s... (make sure the band is disconnected from your phone)\n")
    devices = await BleakScanner.discover(timeout=10.0, return_adv=True)

    found = []
    for addr, (dev, adv) in devices.items():
        name = dev.name or adv.local_name or ""
        looks_like_band = (
            "band" in name.lower()
            or "mi smart" in name.lower()
            or HR_SERVICE in [s.lower() for s in adv.service_uuids]
        )
        line = f"{'>>> ' if looks_like_band else '    '}{addr}  rssi={adv.rssi}  name={name!r}"
        print(line)
        if looks_like_band:
            found.append((addr, name))

    print()
    if found:
        print("Likely Mi Band candidates:")
        for addr, name in found:
            print(f"  {addr}  ({name})")
    else:
        print("No obvious Mi Band found. If nothing shows, the band is probably still")
        print("connected to your phone - close Zepp / turn off the phone's Bluetooth and retry.")


if __name__ == "__main__":
    asyncio.run(main())
