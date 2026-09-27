#!/usr/bin/env python3
"""Add a generated, non-personal portrait PNG to one booted iOS Simulator.

Run before the PhotosPicker UI test (also in CI):
  python3 ios/scripts/seed-simulator-photo.py <simulator-UDID>
Uses only Python stdlib and Xcode's simctl; does not access the user's Photos.
"""
import argparse
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import zlib


def portrait_png() -> bytes:
    width, height = 600, 900
    pixels = bytearray()
    for y in range(height):
        pixels.append(0)
        for x in range(width):
            color = (160 + x // 12, 197 + y // 35, 220) if y < 420 else (35 + x // 9, 125 + y // 30, 148 + x // 20)
            pixels.extend(min(255, channel) for channel in color)
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack("!I", len(data)) + kind + data + struct.pack("!I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(pixels, 6)) + chunk(b"IEND", b"")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("device", help="An explicit booted simulator UDID; never a physical phone")
    options = parser.parse_args()
    listing = json.loads(subprocess.check_output(["xcrun", "simctl", "list", "devices", "booted", "--json"]))
    devices = [device for runtime in listing["devices"].values() for device in runtime]
    if not any(device["udid"] == options.device and device["state"] == "Booted" for device in devices):
        parser.error("Pass the UDID of an already booted iOS Simulator")
    with tempfile.TemporaryDirectory(prefix="inky-ui-photo-") as directory:
        path = Path(directory) / "Inky-UI-Test.png"
        path.write_bytes(portrait_png())
        subprocess.run(["xcrun", "simctl", "addmedia", options.device, str(path)], check=True)
    print(f"Added generated Inky-UI-Test.png to simulator {options.device}")


if __name__ == "__main__":
    main()
