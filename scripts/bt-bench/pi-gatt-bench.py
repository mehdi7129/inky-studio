#!/usr/bin/env python3
"""Temporary BlueZ echo bench. No credentials, pairing, Wi-Fi or Inky API access."""

import argparse
import json
from pathlib import Path
import signal
import subprocess
import sys
import time

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

from protocol import Assembly, RX_UUID, SERVICE_UUID, TX_UUID, VERSION_UUID, VERSION_VALUE, fragments

PROPS = "org.freedesktop.DBus.Properties"
GATT_SERVICE = "org.bluez.GattService1"
GATT_CHAR = "org.bluez.GattCharacteristic1"
ADV = "org.bluez.LEAdvertisement1"
ROOT = "/org/inky/bench"


def log(event, **values):
    print(json.dumps({"event": event, **values}, sort_keys=True), flush=True)


class InvalidValue(dbus.DBusException):
    _dbus_error_name = "org.bluez.Error.InvalidValueLength"


class Object(dbus.service.Object):
    def __init__(self, bus, path, interface, properties):
        self.path, self.interface, self.properties = path, interface, properties
        super().__init__(bus, path)

    @dbus.service.method(PROPS, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        return self.properties if interface == self.interface else {}

    @dbus.service.method(PROPS, in_signature="ss", out_signature="v")
    def Get(self, interface, name):
        return self.GetAll(interface)[name]

    @dbus.service.signal(PROPS, signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed, invalidated):
        pass


class Characteristic(Object):
    def __init__(self, bus, name, uuid, flags, service):
        super().__init__(bus, ROOT + "/service/" + name, GATT_CHAR, {
            "UUID": uuid, "Service": dbus.ObjectPath(service.path),
            "Flags": dbus.Array(flags, signature="s"),
        })
        self.value = b""
        self.notifying = False
        self.assemblies = {}
        self.output = None
        self.pending = []
        self.timer = None

    @dbus.service.method(GATT_CHAR, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options):
        offset = int(options.get("offset", 0))
        if offset > len(self.value):
            raise InvalidValue("Invalid offset")
        log("read", characteristic=self.path.rsplit("/", 1)[-1], bytes=len(self.value) - offset)
        return dbus.ByteArray(self.value[offset:])

    @dbus.service.method(GATT_CHAR, in_signature="aya{sv}", out_signature="")
    def WriteValue(self, value, options):
        if "write" not in self.properties["Flags"] or int(options.get("offset", 0)) != 0:
            raise InvalidValue("Unsupported write")
        # Device path is used only in memory, never printed or persisted.
        peer = str(options.get("device", "local"))
        if peer not in self.assemblies and len(self.assemblies) >= 4:
            raise InvalidValue("Bench client limit")
        parser = self.assemblies.setdefault(peer, Assembly())
        try:
            result = parser.accept(bytes(value))
        except ValueError as exc:
            raise InvalidValue(str(exc)) from exc
        if result:
            transaction, payload = result
            log("echo", transaction=transaction, payload_bytes=len(payload))
            if len(self.output.pending) > 128:
                raise InvalidValue("Bench notification limit")
            self.output.pending.extend(fragments(payload, transaction, frame_size=20))
            if self.output.timer is None:
                self.output.timer = GLib.timeout_add(15, self.output.send_next)

    def send_next(self):
        if not self.pending or not self.notifying:
            self.pending.clear()
            self.timer = None
            return False
        self.value = self.pending.pop(0)
        self.PropertiesChanged(GATT_CHAR, {"Value": dbus.ByteArray(self.value)}, [])
        return True

    @dbus.service.method(GATT_CHAR, in_signature="", out_signature="")
    def StartNotify(self):
        self.notifying = True
        self.properties["Notifying"] = dbus.Boolean(True)
        self.PropertiesChanged(GATT_CHAR, {"Notifying": dbus.Boolean(True)}, [])
        log("notify-enabled")

    @dbus.service.method(GATT_CHAR, in_signature="", out_signature="")
    def StopNotify(self):
        self.notifying = False
        self.pending.clear()
        self.properties["Notifying"] = dbus.Boolean(False)
        self.PropertiesChanged(GATT_CHAR, {"Notifying": dbus.Boolean(False)}, [])
        log("notify-disabled")


class Application(dbus.service.Object):
    def __init__(self, bus):
        super().__init__(bus, ROOT)
        service = Object(bus, ROOT + "/service", GATT_SERVICE, {"UUID": SERVICE_UUID, "Primary": dbus.Boolean(True), "Includes": dbus.Array([], signature="o")})
        version = Characteristic(bus, "version", VERSION_UUID, ["read"], service)
        version.value = VERSION_VALUE
        rx = Characteristic(bus, "rx", RX_UUID, ["write"], service)
        tx = Characteristic(bus, "tx", TX_UUID, ["read", "notify"], service)
        tx.properties["Notifying"] = dbus.Boolean(False)
        rx.output = tx
        self.objects = [service, version, rx, tx]

    @dbus.service.method("org.freedesktop.DBus.ObjectManager", out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        return {item.path: {item.interface: item.properties} for item in self.objects}


class Advertisement(Object):
    def __init__(self, bus):
        super().__init__(bus, ROOT + "/advertisement", ADV, {
            "Type": "peripheral", "ServiceUUIDs": dbus.Array([SERVICE_UUID], signature="s"),
            "LocalName": "Inky Bench", "Discoverable": dbus.Boolean(True),
        })

    @dbus.service.method(ADV, in_signature="", out_signature="")
    def Release(self):
        log("advertisement-released")


def bluetooth_blocked():
    for entry in Path("/sys/class/rfkill").glob("rfkill*"):
        if (entry / "type").read_text().strip() == "bluetooth":
            return (entry / "soft").read_text().strip() == "1"
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable-radio", action="store_true", help="Temporarily unblock/power Bluetooth; restore its prior state on exit")
    parser.add_argument("--duration", type=int, default=240, choices=range(10, 601), metavar="10..600")
    args = parser.parse_args()
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    adapter = bus.get_object("org.bluez", "/org/bluez/hci0")
    props = dbus.Interface(adapter, PROPS)
    original_power = bool(props.Get("org.bluez.Adapter1", "Powered"))
    original_block = bluetooth_blocked()
    gatt = dbus.Interface(adapter, "org.bluez.GattManager1")
    advertisements = dbus.Interface(adapter, "org.bluez.LEAdvertisingManager1")
    app = Application(bus)
    advert = Advertisement(bus)
    loop = GLib.MainLoop()
    registered_app = False
    registered_advert = False
    exit_code = 0

    def stop(*_):
        loop.quit()
        return False

    def failed(error):
        nonlocal exit_code
        exit_code = 1
        log("registration-error", error=error.get_dbus_name())
        loop.quit()

    def advert_ready():
        nonlocal registered_advert
        registered_advert = True
        log("ready", protocol=1, duration=args.duration, private_data=False, authenticated=False)

    def app_ready():
        nonlocal registered_app
        registered_app = True
        advertisements.RegisterAdvertisement(advert.path, {}, reply_handler=advert_ready, error_handler=failed)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        if args.enable_radio:
            if original_block:
                subprocess.run(["/usr/sbin/rfkill", "unblock", "bluetooth"], check=True, capture_output=True, timeout=5)
            for attempt in range(12):
                try:
                    props.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(True))
                    break
                except dbus.DBusException:
                    if attempt == 11:
                        raise
                    time.sleep(0.25)
        if not bool(props.Get("org.bluez.Adapter1", "Powered")):
            raise RuntimeError("Bluetooth is off; use --enable-radio for this temporary bench")
        GLib.timeout_add_seconds(args.duration, stop)
        gatt.RegisterApplication(ROOT, {}, reply_handler=app_ready, error_handler=failed)
        loop.run()
    finally:
        for manager, method, path, registered in (
            (advertisements, "UnregisterAdvertisement", advert.path, registered_advert),
            (gatt, "UnregisterApplication", ROOT, registered_app),
        ):
            if registered:
                try:
                    getattr(manager, method)(path)
                except dbus.DBusException:
                    pass
        if args.enable_radio:
            try:
                props.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(original_power))
            finally:
                if original_block:
                    subprocess.run(["/usr/sbin/rfkill", "block", "bluetooth"], check=True, capture_output=True, timeout=5)
        log("stopped", restored_power=original_power, restored_softblock=original_block)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
