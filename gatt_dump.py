#!/usr/bin/env python3
"""Dump the band's GATT services/characteristics and their properties."""
import asyncio
import sys
from bleak import BleakClient

if len(sys.argv) < 2:
    print("usage: gatt_dump.py <DEVICE_UUID>   (get it from scan.py)")
    sys.exit(1)
ADDR = sys.argv[1]


async def main():
    async with BleakClient(ADDR) as client:
        print(f"Connected: {client.address}\n")
        for svc in client.services:
            print(f"[Service] {svc.uuid}")
            for ch in svc.characteristics:
                print(f"   {ch.uuid}  props={ch.properties}")


if __name__ == "__main__":
    asyncio.run(main())
