"""BlueZ adapter for the bounded per-device TLS transport (Linux only)."""
import asyncio
import json

from dbus_fast import DBusError, Message, MessageType
from dbus_fast.aio import MessageBus
from dbus_fast.constants import BusType, PropertyAccess
from dbus_fast.service import ServiceInterface, dbus_method, dbus_property

from .transport import CERTIFICATE_UUIDS, IDENTITY_UUID, SERVICE_UUID, STREAM_UUID, TransportError

ROOT = "/org/inky/provisioning"
SERVICE = ROOT + "/service"
ADAPTER = "/org/bluez/hci0"


class Service(ServiceInterface):
    def __init__(self):
        super().__init__("org.bluez.GattService1")

    @dbus_property(access=PropertyAccess.READ)
    def UUID(self) -> "s":  # noqa: F821
        return SERVICE_UUID

    @dbus_property(access=PropertyAccess.READ)
    def Primary(self) -> "b":  # noqa: F821
        return True


class Characteristic(ServiceInterface):
    def __init__(self, uuid, transport, identity):
        super().__init__("org.bluez.GattCharacteristic1")
        self.uuid, self.transport = uuid, transport
        if not 1 <= len(identity.cert_der) <= 960:
            raise ValueError("Certificate exceeds GATT identity representation")
        self.identity_value = json.dumps({
            "v": 1, "id": identity.frame_id,
            "cert_length": len(identity.cert_der),
        }, separators=(",", ":")).encode()
        if uuid in CERTIFICATE_UUIDS:
            index = CERTIFICATE_UUIDS.index(uuid)
            self.identity_value = identity.cert_der[index * 480:(index + 1) * 480]

    @dbus_property(access=PropertyAccess.READ)
    def UUID(self) -> "s":  # noqa: F821
        return self.uuid

    @dbus_property(access=PropertyAccess.READ)
    def Service(self) -> "o":  # noqa: F821
        return SERVICE

    @dbus_property(access=PropertyAccess.READ)
    def Flags(self) -> "as":  # noqa: F722
        return ["read", "write"] if self.uuid == STREAM_UUID else ["read"]

    @dbus_method()
    def ReadValue(self, options: "a{sv}") -> "ay":  # noqa: F722,F821
        values = {key: item.value for key, item in options.items()}
        offset = values.get("offset", 0)
        if self.uuid != STREAM_UUID:
            if not 0 <= offset <= len(self.identity_value):
                raise DBusError("org.bluez.Error.InvalidOffset", "Offset invalide")
            return self.identity_value[offset:]
        try:
            return self.transport.read(values.get("device", ""), offset)
        except TransportError:
            raise DBusError("org.bluez.Error.Failed", "Session indisponible") from None

    @dbus_method()
    def WriteValue(self, value: "ay", options: "a{sv}"):  # noqa: F722,F821
        values = {key: item.value for key, item in options.items()}
        if (self.uuid != STREAM_UUID or values.get("offset", 0) != 0
                or values.get("type", "request") != "request"
                or values.get("prepare-authorize", False)):
            raise DBusError("org.bluez.Error.NotPermitted", "Écriture non autorisée")
        try:
            self.transport.write(values.get("device", ""), bytes(value), values.get("mtu", 23))
        except TransportError:
            raise DBusError("org.bluez.Error.Failed", "Session indisponible") from None


class Advertisement(ServiceInterface):
    def __init__(self):
        super().__init__("org.bluez.LEAdvertisement1")

    @dbus_property(access=PropertyAccess.READ)
    def Type(self) -> "s":  # noqa: F821
        return "peripheral"

    @dbus_property(access=PropertyAccess.READ)
    def ServiceUUIDs(self) -> "as":  # noqa: F722
        return [SERVICE_UUID]

    @dbus_property(access=PropertyAccess.READ)
    def LocalName(self) -> "s":  # noqa: F821
        return "Inky Studio"

    @dbus_property(access=PropertyAccess.READ)
    def Discoverable(self) -> "b":  # noqa: F821
        return True

    @dbus_method()
    def Release(self):
        pass


class BlueZServer:
    def __init__(self, transport, identity):
        self.transport, self.identity = transport, identity
        self.bus = None
        self.registered = False
        self.advertising = False
        self._task = None

    async def _call(self, interface, member, signature="", body=None, path=ADAPTER):
        result = await self.bus.call(Message(
            destination="org.bluez", path=path, interface=interface,
            member=member, signature=signature, body=body or [],
        ))
        if result.message_type == MessageType.ERROR:
            # D-Bus can echo method arguments: expose only its error name.
            raise RuntimeError(result.error_name)
        return result.body

    async def start(self):
        self.bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        try:
            # MessageBus exports ObjectManager automatically for descendants.
            self.bus.export(SERVICE, Service())
            self.bus.export(SERVICE + "/identity", Characteristic(IDENTITY_UUID, self.transport, self.identity))
            self.bus.export(SERVICE + "/stream", Characteristic(STREAM_UUID, self.transport, self.identity))
            for index, uuid in enumerate(CERTIFICATE_UUIDS):
                self.bus.export(SERVICE + f"/certificate{index}", Characteristic(uuid, self.transport, self.identity))
            self.bus.export(ROOT + "/advertisement", Advertisement())
            self.bus.add_message_handler(self._signal)
            match = "type='signal',sender='org.bluez',interface='org.freedesktop.DBus.Properties',member='PropertiesChanged'"
            result = await self.bus.call(Message(
                destination="org.freedesktop.DBus", path="/org/freedesktop/DBus",
                interface="org.freedesktop.DBus", member="AddMatch",
                signature="s", body=[match],
            ))
            if result.message_type == MessageType.ERROR:
                raise RuntimeError(result.error_name)
            # Radio enablement belongs to explicit installation, never a silent
            # networking side effect while importing or testing this module.
            await self._call("org.bluez.GattManager1", "RegisterApplication", "oa{sv}", [ROOT, {}])
            self.registered = True
            await self._call("org.bluez.LEAdvertisingManager1", "RegisterAdvertisement", "oa{sv}", [ROOT + "/advertisement", {}])
            self.advertising = True
            self._task = asyncio.create_task(self._expire())
        except BaseException:
            await self.stop()
            raise

    def _signal(self, message):
        if (message.message_type == MessageType.SIGNAL
                and message.interface == "org.freedesktop.DBus.Properties"
                and message.member == "PropertiesChanged" and len(message.body) == 3
                and message.body[0] == "org.bluez.Device1"):
            connected = message.body[1].get("Connected")
            if connected is not None and not connected.value:
                self.transport.disconnect(message.path)

    async def _expire(self):
        while True:
            await asyncio.sleep(10)
            self.transport.expire()

    async def stop(self):
        self.transport.close()
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        if self.bus:
            try:
                if self.advertising:
                    await self._call("org.bluez.LEAdvertisingManager1", "UnregisterAdvertisement", "o", [ROOT + "/advertisement"])
                if self.registered:
                    await self._call("org.bluez.GattManager1", "UnregisterApplication", "o", [ROOT])
            finally:
                self.bus.disconnect()
                self.bus = None
                self.advertising = self.registered = False
