"""Bluetooth through BlueZ: power, search, pairing, connecting, forgetting.

BlueZ is driven over D-Bus (``python3-dbus`` and ``python3-gi``, which
whisplay-daemon already needs). Pairing a keyboard needs an *agent* that
shows the passkey to type, so ``Bluetooth`` registers one (capability
``KeyboardDisplay``) on its own GLib thread and reports what BlueZ asks for
through ``on_prompt``. Where the D-Bus bindings are missing, ``bluetoothctl``
does the same jobs, without passkey display.

Every call blocks (up to tens of seconds for pairing): run them on a worker
(``os.run_task`` / ``os.start_job``), never on the UI thread.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import Callable, Optional

log = logging.getLogger("mfruitos.bluetooth")

AGENT_PATH = "/org/mfruitos/BluetoothAgent"
PAIR_TIMEOUT_SEC = 60
CONFIRM_TIMEOUT_SEC = 30
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x01|\x02")
ADDRESS = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$", re.IGNORECASE)

# BlueZ's "Icon" property -> the kind shown on screen.
KINDS = {"input-keyboard": "Keyboard", "input-mouse": "Mouse", "input-gaming": "Controller",
         "audio-headset": "Headset", "audio-headphones": "Headphones", "audio-card": "Speaker",
         "phone": "Phone", "computer": "Computer", "input-tablet": "Tablet"}


@dataclass
class BtDevice:
    address: str
    name: str
    paired: bool = False
    connected: bool = False
    trusted: bool = False
    icon: str = ""                  # BlueZ's icon name, e.g. "input-keyboard"
    rssi: Optional[int] = None      # dBm, while it is being heard

    @property
    def kind(self) -> str:
        return KINDS.get(self.icon, "")


@dataclass
class Prompt:
    """What the pairing agent needs the user to see or decide."""
    kind: str                       # passkey | pin | confirm | done
    code: str = ""                  # the digits to type or compare
    device: str = ""


def named(device: BtDevice) -> bool:
    """Worth listing: it has a real name (not just its address)."""
    name = device.name.strip()
    return bool(name) and not ADDRESS.match(name.replace("-", ":"))


def sort_key(device: BtDevice):
    return (not device.connected, not device.paired, -(device.rssi or -200), device.name.lower())


class Bluetooth:
    def __init__(self, on_prompt: Callable[[Prompt], None] | None = None,
                 run: Callable | None = None):
        self.on_prompt = on_prompt or (lambda prompt: None)
        self._run = run or _run
        self._dbus = _load_dbus()
        self._agent = None
        self._agent_lock = threading.Lock()
        self._decision = threading.Event()
        self._accepted = False

    # ------------------------------------------------------------ queries
    @property
    def via_dbus(self) -> bool:
        return self._dbus is not None

    def available(self) -> bool:
        """Is there a Bluetooth controller we can drive?"""
        if self._dbus is not None:
            try:
                return self._adapter_path() is not None
            except Exception as exc:
                log.info("BlueZ unavailable over D-Bus: %s", exc)
                return False
        if not shutil.which("bluetoothctl"):
            return False
        return "Controller " in self._ctl("list")

    def powered(self) -> bool:
        if self._dbus is not None:
            return bool(self._adapter_props().get("Powered", False))
        return "Powered: yes" in self._ctl("show")

    def devices(self) -> list[BtDevice]:
        """Every device BlueZ knows: paired ones, and those heard while searching."""
        if self._dbus is not None:
            found = []
            for path, interfaces in self._objects().items():
                props = interfaces.get("org.bluez.Device1")
                if props is None:
                    continue
                found.append(BtDevice(
                    address=str(props.get("Address", "")),
                    name=str(props.get("Alias") or props.get("Name") or ""),
                    paired=bool(props.get("Paired", False)),
                    connected=bool(props.get("Connected", False)),
                    trusted=bool(props.get("Trusted", False)),
                    icon=str(props.get("Icon", "")),
                    rssi=int(props["RSSI"]) if "RSSI" in props else None))
            return sorted(found, key=sort_key)
        return sorted(self._ctl_devices(), key=sort_key)

    # ----------------------------------------------------------- actions
    def set_powered(self, on: bool) -> None:
        if self._dbus is not None:
            self._set_adapter("Powered", self._dbus.Boolean(on))
        else:
            self._ctl("power", "on" if on else "off")

    def search(self, seconds: float = 8.0) -> None:
        """Listen for devices for ``seconds`` (they then appear in ``devices``)."""
        if self._dbus is not None:
            import time
            adapter = self._interface(self._adapter_path(), "org.bluez.Adapter1")
            try:
                adapter.StartDiscovery()
            except self._dbus.exceptions.DBusException as exc:
                if "InProgress" not in str(exc):
                    raise
            try:
                time.sleep(seconds)
            finally:
                try:
                    adapter.StopDiscovery()
                except self._dbus.exceptions.DBusException:
                    pass
            return
        self._ctl("--timeout", str(int(seconds)), "scan", "on", timeout=seconds + 5)

    def pair(self, address: str) -> tuple[bool, str]:
        """Pair, trust (so it reconnects by itself) and connect. (ok, message)."""
        if self._dbus is None:
            output = self._ctl("pair", address, timeout=PAIR_TIMEOUT_SEC)
            if "successful" not in output.lower() and "already" not in output.lower():
                return False, _reason(output) or "Pairing failed"
            self._ctl("trust", address)
            self._ctl("connect", address, timeout=30)
            return True, "Paired"
        self.start_agent()
        device = self._device(address)
        try:
            device.Pair(timeout=PAIR_TIMEOUT_SEC)
        except self._dbus.exceptions.DBusException as exc:
            if "AlreadyExists" not in str(exc):
                return False, _dbus_reason(exc)
        finally:
            self.on_prompt(Prompt("done", device=address))
        self._set_device(address, "Trusted", self._dbus.Boolean(True))
        ok, message = self.connect(address)
        return True, "Connected" if ok else "Paired"

    def connect(self, address: str) -> tuple[bool, str]:
        if self._dbus is None:
            output = self._ctl("connect", address, timeout=30)
            ok = "successful" in output.lower()
            return ok, "Connected" if ok else (_reason(output) or "Could not connect")
        try:
            self._device(address).Connect(timeout=30)
            return True, "Connected"
        except self._dbus.exceptions.DBusException as exc:
            return False, _dbus_reason(exc)

    def disconnect(self, address: str) -> tuple[bool, str]:
        if self._dbus is None:
            output = self._ctl("disconnect", address, timeout=15)
            ok = "successful" in output.lower()
            return ok, "Disconnected" if ok else (_reason(output) or "Could not disconnect")
        try:
            self._device(address).Disconnect(timeout=15)
            return True, "Disconnected"
        except self._dbus.exceptions.DBusException as exc:
            return False, _dbus_reason(exc)

    def forget(self, address: str) -> tuple[bool, str]:
        """Unpair and remove the device; it must be paired again to reconnect."""
        if self._dbus is None:
            output = self._ctl("remove", address, timeout=15)
            ok = "removed" in output.lower()
            return ok, "Forgotten" if ok else (_reason(output) or "Could not forget it")
        path = self._device_path(address)
        if path is None:
            return True, "Forgotten"
        try:
            self._interface(self._adapter_path(), "org.bluez.Adapter1").RemoveDevice(path)
            return True, "Forgotten"
        except self._dbus.exceptions.DBusException as exc:
            return False, _dbus_reason(exc)

    # ------------------------------------------------------ pairing agent
    def answer(self, accept: bool) -> None:
        """The user's answer to a "confirm" prompt."""
        self._accepted = accept
        self._decision.set()

    def start_agent(self) -> bool:
        """Register the pairing agent (once), and make it BlueZ's default."""
        if self._dbus is None:
            return False
        with self._agent_lock:
            if self._agent is not None:
                return True
            ready = threading.Event()
            thread = threading.Thread(target=self._agent_loop, args=(ready,),
                                      name="bt-agent", daemon=True)
            thread.start()
            ready.wait(5.0)
            return self._agent is not None

    def _agent_loop(self, ready: threading.Event) -> None:
        try:
            import dbus
            import dbus.service
            from dbus.mainloop.glib import DBusGMainLoop
            from gi.repository import GLib
        except ImportError as exc:
            log.warning("No pairing agent: %s", exc)
            ready.set()
            return
        outer = self
        DBusGMainLoop(set_as_default=True)
        bus = dbus.SystemBus()

        class Agent(dbus.service.Object):
            @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
            def Release(self):
                pass

            @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="s")
            def RequestPinCode(self, device):
                raise dbus.exceptions.DBusException("org.bluez.Error.Rejected",
                                                    "PIN entry is not supported")

            @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="")
            def DisplayPinCode(self, device, pincode):
                outer.on_prompt(Prompt("pin", str(pincode), _address_of(device)))

            @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="u")
            def RequestPasskey(self, device):
                raise dbus.exceptions.DBusException("org.bluez.Error.Rejected",
                                                    "Passkey entry is not supported")

            @dbus.service.method("org.bluez.Agent1", in_signature="ouq", out_signature="")
            def DisplayPasskey(self, device, passkey, entered):
                outer.on_prompt(Prompt("passkey", f"{int(passkey):06d}", _address_of(device)))

            @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="")
            def RequestConfirmation(self, device, passkey):
                outer._decision.clear()
                outer._accepted = False
                outer.on_prompt(Prompt("confirm", f"{int(passkey):06d}", _address_of(device)))
                outer._decision.wait(CONFIRM_TIMEOUT_SEC)
                if not outer._accepted:
                    raise dbus.exceptions.DBusException("org.bluez.Error.Rejected",
                                                        "Pairing rejected")

            @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="")
            def RequestAuthorization(self, device):
                pass

            @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
            def AuthorizeService(self, device, uuid):
                pass

            @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
            def Cancel(self):
                outer.on_prompt(Prompt("done"))

        try:
            agent = Agent(bus, AGENT_PATH)
            manager = dbus.Interface(bus.get_object("org.bluez", "/org/bluez"),
                                     "org.bluez.AgentManager1")
            manager.RegisterAgent(AGENT_PATH, "KeyboardDisplay")
            manager.RequestDefaultAgent(AGENT_PATH)
            self._agent = agent
            log.info("Bluetooth pairing agent registered")
        except Exception as exc:
            log.warning("Cannot register the pairing agent: %s", exc)
            ready.set()
            return
        ready.set()
        GLib.MainLoop().run()

    # ------------------------------------------------------ D-Bus helpers
    def _bus(self):
        return self._dbus.SystemBus(private=True)

    def _objects(self) -> dict:
        bus = self._bus()
        try:
            manager = self._dbus.Interface(bus.get_object("org.bluez", "/"),
                                           "org.freedesktop.DBus.ObjectManager")
            return manager.GetManagedObjects()
        finally:
            bus.close()

    def _adapter_path(self) -> Optional[str]:
        for path, interfaces in self._objects().items():
            if "org.bluez.Adapter1" in interfaces:
                return str(path)
        return None

    def _adapter_props(self) -> dict:
        for path, interfaces in self._objects().items():
            if "org.bluez.Adapter1" in interfaces:
                return dict(interfaces["org.bluez.Adapter1"])
        return {}

    def _device_path(self, address: str) -> Optional[str]:
        for path, interfaces in self._objects().items():
            props = interfaces.get("org.bluez.Device1")
            if props is not None and str(props.get("Address", "")).upper() == address.upper():
                return str(path)
        return None

    def _interface(self, path: str, name: str):
        return self._dbus.Interface(self._bus().get_object("org.bluez", path), name)

    def _device(self, address: str):
        path = self._device_path(address)
        if path is None:
            raise self._dbus.exceptions.DBusException("org.bluez.Error.DoesNotExist",
                                                      "Device not found")
        return self._interface(path, "org.bluez.Device1")

    def _set_adapter(self, name: str, value) -> None:
        props = self._interface(self._adapter_path(), "org.freedesktop.DBus.Properties")
        props.Set("org.bluez.Adapter1", name, value)

    def _set_device(self, address: str, name: str, value) -> None:
        path = self._device_path(address)
        if path is not None:
            props = self._interface(path, "org.freedesktop.DBus.Properties")
            props.Set("org.bluez.Device1", name, value)

    # ---------------------------------------------------- bluetoothctl
    def _ctl(self, *args: str, timeout: float = 10.0) -> str:
        return ANSI.sub("", self._run(["bluetoothctl", *args], timeout))

    def _ctl_devices(self) -> list[BtDevice]:
        devices = []
        for line in self._ctl("devices").splitlines():
            parts = line.strip().split(maxsplit=2)
            if len(parts) < 2 or parts[0] != "Device":
                continue
            devices.append(parse_info(parts[1], self._ctl("info", parts[1]),
                                      parts[2] if len(parts) > 2 else ""))
        return devices


def parse_info(address: str, text: str, listed_name: str = "") -> BtDevice:
    """A device from ``bluetoothctl info`` output."""
    fields = {}
    for raw in ANSI.sub("", text).splitlines():
        key, _, value = raw.strip().partition(":")
        if value and key not in fields:
            fields[key] = value.strip()
    rssi = None
    match = re.search(r"-?\d+", fields.get("RSSI", "").split("(")[-1]) if "RSSI" in fields else None
    if match:
        rssi = int(match.group(0))
    return BtDevice(address=address,
                    name=fields.get("Alias") or fields.get("Name") or listed_name,
                    paired=fields.get("Paired") == "yes",
                    connected=fields.get("Connected") == "yes",
                    trusted=fields.get("Trusted") == "yes",
                    icon=fields.get("Icon", ""), rssi=rssi)


def _run(args: list[str], timeout: float) -> str:
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.info("%s: %s", " ".join(args[:2]), exc)
        return ""
    return (done.stdout or "") + (done.stderr or "")


def _reason(output: str) -> str:
    for line in reversed(output.splitlines()):
        line = line.strip()
        if "Failed" in line or "Error" in line or "not available" in line:
            return line[:60]
    return ""


def _dbus_reason(exc) -> str:
    name = getattr(exc, "get_dbus_name", lambda: "")() or ""
    return {
        "org.bluez.Error.AuthenticationFailed": "The code did not match",
        "org.bluez.Error.AuthenticationCanceled": "Pairing was cancelled",
        "org.bluez.Error.AuthenticationRejected": "Pairing was rejected",
        "org.bluez.Error.AuthenticationTimeout": "Pairing timed out",
        "org.bluez.Error.ConnectionAttemptFailed": "It did not answer",
        "org.bluez.Error.InProgress": "Busy, try again",
        "org.bluez.Error.NotReady": "Bluetooth is off",
        "org.freedesktop.DBus.Error.NoReply": "It did not answer",
    }.get(name, (str(exc).split(":")[-1].strip() or "Failed")[:60])


def _address_of(device_path) -> str:
    tail = str(device_path).rsplit("/", 1)[-1]
    return tail[4:].replace("_", ":") if tail.startswith("dev_") else ""


def _load_dbus():
    try:
        import dbus
        import dbus.exceptions  # noqa: F401
        return dbus
    except ImportError:
        return None
