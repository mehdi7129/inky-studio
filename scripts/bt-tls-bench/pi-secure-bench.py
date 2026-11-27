#!/usr/bin/env python3
"""Temporary real-BLE qualification, synthetic echo only, no Wi-Fi changes.

Run with this checkout's server/ on PYTHONPATH. The private bench directory must
be distinct from production data. Radio state is restored on normal exit or
SIGINT/SIGTERM. Kill -9/power loss cannot run cleanup: inspect radio afterwards.
"""
import argparse
import asyncio
import json
import os
import signal
import subprocess
from pathlib import Path

import dbus
from inky_web.provisioning.bluez import BlueZServer
from inky_web.provisioning.identity import load_or_create_identity
from inky_web.provisioning.transport import GATTTransport


async def run(args):
    directory = Path(args.directory).resolve()
    if directory == Path("/var/lib/inky-studio") or Path("/var/lib/inky-studio") in directory.parents:
        raise ValueError("Bench must not use production data")
    identity = load_or_create_identity(directory)
    public = {"id": identity.frame_id, "k": identity.spki_sha256}
    descriptor = os.open(directory / "public-trust.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump(public, output)

    async def echo(message):
        if set(message) != {"echo"} or not isinstance(message["echo"], str) or len(message["echo"]) > 2048:
            return {"error": "invalid_synthetic_command"}
        return {"echo": message["echo"]}

    transport = GATTTransport(identity.ssl_context(), echo)
    server = BlueZServer(transport, identity)
    props = dbus.Interface(dbus.SystemBus().get_object("org.bluez", "/org/bluez/hci0"),
                           "org.freedesktop.DBus.Properties")
    original_power = bool(props.Get("org.bluez.Adapter1", "Powered"))
    blocked = any((entry / "type").read_text().strip() == "bluetooth" and (entry / "soft").read_text().strip() == "1"
                  for entry in Path("/sys/class/rfkill").glob("rfkill*"))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        if args.enable_radio:
            if blocked:
                await asyncio.to_thread(subprocess.run, ["/usr/sbin/rfkill", "unblock", "bluetooth"], check=True, capture_output=True, timeout=5)
            for attempt in range(12):
                try:
                    props.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(True))
                    break
                except dbus.DBusException:
                    if attempt == 11:
                        raise
                    await asyncio.sleep(0.25)
        await server.start()
        print(json.dumps({"event": "ready", "synthetic": True, "duration": args.duration}), flush=True)
        try:
            await asyncio.wait_for(stop.wait(), args.duration)
        except TimeoutError:
            pass
    finally:
        await server.stop()
        if args.enable_radio:
            try:
                props.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(original_power))
            finally:
                if blocked:
                    await asyncio.to_thread(subprocess.run, ["/usr/sbin/rfkill", "block", "bluetooth"], check=True, capture_output=True, timeout=5)
        print(json.dumps({"event": "stopped", "restored_power": original_power, "restored_softblock": blocked}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--enable-radio", action="store_true")
    parser.add_argument("--duration", type=int, default=240, choices=range(10, 601))
    asyncio.run(run(parser.parse_args()))
