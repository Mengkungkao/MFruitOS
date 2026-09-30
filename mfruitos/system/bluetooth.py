"""Bluetooth through BlueZ: power, search, pairing, connecting, forgetting.

BlueZ is driven over D-Bus (``python3-dbus`` and ``python3-gi``, which
whisplay-daemon already needs). Pairing a keyboard needs an *agent* that
shows the passkey to type, so ``Bluetooth`` registers one (capability
``DisplayYesNo``) on its own GLib thread and reports what BlueZ asks for
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
    return (not device.connected, not device.paired,
            -(device.rssi if device.rssi is not None else -200), device.name.lower())


class Bluetooth:
    def __init__(self, on_prompt: Callable[[Prompt], None] | None = None,
                 run: Callable | None = None):
        self.on_prompt = on_prompt or (lambda prompt: None)
        self._run = run or _run
        self._dbus = _load_dbus()
        self._agent = None
        self._agent_lock = threading.Lock()
        self._query_bus = None
        self._agent_bus = None
        self._glib = self._mainloop = None
        self._confirmation = None
        self._confirmation_timer = None
        self._pairing_address = ""
        self._closed = False

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
            output = self._ctl("power", "on" if on else "off")
            if "succeeded" not in output.lower():
                raise RuntimeError(_reason(output) or "Could not change Bluetooth power")

    def search(self, seconds: float = 8.0) -> None:
        """Listen for devices for ``seconds`` (they then appear in ``devices``)."""
        if self._dbus is not None:
            import time
            adapter = self._interface(self._adapter_path(), "org.bluez.Adapter1")
            started = False
            try:
                adapter.StartDiscovery()
                started = True
            except self._dbus.exceptions.DBusException as exc:
                if "InProgress" not in str(exc):
                    raise
            try:
                time.sleep(seconds)
            finally:
                if started:
                    try:
                        adapter.StopDiscovery()
                    except self._dbus.exceptions.DBusException as exc:
                        log.info("Stop discovery: %s", exc)
            return
        self._ctl("--timeout", str(int(seconds)), "scan", "on", timeout=seconds + 5)

    def pair(self, address: str) -> tuple[bool, str]:
        """Pair, trust (so it reconnects by itself) and connect. (ok, message)."""
        if self._dbus is None:
            output = self._ctl("pair", address, timeout=PAIR_TIMEOUT_SEC)
            if "Pairing successful" not in output and "AlreadyExists" not in output:
                return False, _reason(output) or "Pairing failed"
            trust = self._ctl("trust", address)
            if "succeeded" not in trust.lower():
                return False, "Paired, but could not trust device"
            ok, message = self.connect(address)
            return True, "Connected" if ok else "Paired; " + message
        if not self.start_agent():
            return False, "Pairing agent unavailable"
        path = self._device_path(address)
        if path is None:
            return False, "Device not found; search again"
        completed = threading.Event()
        errors = []
        self._pairing_address = address

        def failed(exc):
            errors.append(exc)
            completed.set()

        def begin():
            try:
                device = self._dbus.Interface(self._agent_bus.get_object("org.bluez", path),
                                              "org.bluez.Device1")
                # Pair on the agent's connection: BlueZ then chooses our agent
                # without replacing whisplay-daemon's global default agent.
                device.Pair(reply_handler=completed.set, error_handler=failed,
                            timeout=PAIR_TIMEOUT_SEC)
            except Exception as exc:
                failed(exc)
            return False
        try:
            self._glib.idle_add(begin)
            if not completed.wait(PAIR_TIMEOUT_SEC + 2):
                self.cancel_pairing()
                return False, "Pairing timed out"
            if errors and "AlreadyExists" not in str(errors[0]):
                return False, _dbus_reason(errors[0])
        finally:
            self._pairing_address = ""
            self.answer(False)
            self.on_prompt(Prompt("done", device=address))
        self._set_device(address, "Trusted", self._dbus.Boolean(True))
        ok, message = self.connect(address)
        return True, "Connected" if ok else "Paired; " + message

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
        if self._glib is not None:
            self._glib.idle_add(self._resolve_confirmation, accept)

    def _resolve_confirmation(self, accept: bool) -> bool:
        callbacks, self._confirmation = self._confirmation, None
        if self._confirmation_timer is not None:
            self._glib.source_remove(self._confirmation_timer)
            self._confirmation_timer = None
        if callbacks:
            reply, error = callbacks
            if accept:
                reply()
            else:
                error(self._dbus.exceptions.DBusException(
                    "Pairing rejected", name="org.bluez.Error.Rejected"))
        return False

    def cancel_pairing(self) -> None:
        self.answer(False)
        address = self._pairing_address
        if address and self._glib is not None:
            def cancel():
                try:
                    path = self._device_path(address)
                    if path:
                        device = self._dbus.Interface(self._agent_bus.get_object("org.bluez", path),
                                                      "org.bluez.Device1")
                        device.CancelPairing(reply_handler=lambda: None,
                                             error_handler=lambda exc: log.info("Cancel pairing: %s", exc))
                except Exception as exc:
                    log.info("Cancel pairing: %s", exc)
                return False
            self._glib.idle_add(cancel)

    def close(self) -> None:
        """Release the bounded query connection and pairing agent on shutdown."""
        self._closed = True
        self.cancel_pairing()
        if self._mainloop is not None:
            self._glib.idle_add(self._mainloop.quit)
        if self._query_bus is not None:
            self._query_bus.close()
            self._query_bus = None

    def start_agent(self) -> bool:
        """Register our connection's agent without taking over the global agent."""
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
        self._glib = GLib
        bus = dbus.SystemBus(private=True, mainloop=DBusGMainLoop())
        self._agent_bus = bus

        class Agent(dbus.service.Object):
            @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
            def Release(self):
                outer._agent = None
                outer.answer(False)

            @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="s")
            def RequestPinCode(self, device):
                raise dbus.exceptions.DBusException("PIN entry is not supported",
                                                    name="org.bluez.Error.Rejected")

            @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
            def DisplayPinCode(self, device, pincode):
                outer.on_prompt(Prompt("pin", str(pincode), _address_of(device)))

            @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="u")
            def RequestPasskey(self, device):
                raise dbus.exceptions.DBusException("Passkey entry is not supported",
                                                    name="org.bluez.Error.Rejected")

            @dbus.service.method("org.bluez.Agent1", in_signature="ouq", out_signature="")
            def DisplayPasskey(self, device, passkey, entered):
                outer.on_prompt(Prompt("passkey", f"{int(passkey):06d}", _address_of(device)))

            @dbus.service.method("org.bluez.Agent1", in_signature="ou", out_signature="",
                                 async_callbacks=("reply", "error"))
            def RequestConfirmation(self, device, passkey, reply, error):
                outer._resolve_confirmation(False)
                outer._confirmation = (reply, error)
                outer._confirmation_timer = GLib.timeout_add_seconds(
                    CONFIRM_TIMEOUT_SEC, outer._resolve_confirmation, False)
                outer.on_prompt(Prompt("confirm", f"{int(passkey):06d}", _address_of(device)))

            @dbus.service.method("org.bluez.Agent1", in_signature="o", out_signature="")
            def RequestAuthorization(self, device):
                if _address_of(device) != outer._pairing_address:
                    raise dbus.exceptions.DBusException("No pairing requested",
                                                        name="org.bluez.Error.Rejected")

            @dbus.service.method("org.bluez.Agent1", in_signature="os", out_signature="")
            def AuthorizeService(self, device, uuid):
                pass

            @dbus.service.method("org.bluez.Agent1", in_signature="", out_signature="")
            def Cancel(self):
                outer._resolve_confirmation(False)
                outer.on_prompt(Prompt("done"))

        try:
            agent = Agent(bus, AGENT_PATH)
            manager = dbus.Interface(bus.get_object("org.bluez", "/org/bluez"),
                                     "org.bluez.AgentManager1")
            manager.RegisterAgent(AGENT_PATH, "DisplayYesNo")
            self._agent = agent
            log.info("Bluetooth pairing agent registered")
        except Exception as exc:
            log.warning("Cannot register the pairing agent: %s", exc)
            bus.close()
            self._agent_bus = None
            ready.set()
            return
        self._mainloop = GLib.MainLoop()
        ready.set()
        try:
            if not self._closed:
                self._mainloop.run()
        finally:
            self._resolve_confirmation(False)
            self._agent = None
            bus.close()  # BlueZ unregisters this connection's agent.
            self._agent_bus = None

    # ------------------------------------------------------ D-Bus helpers
    def _bus(self):
        if self._closed:
            raise RuntimeError("Bluetooth service is closed")
        if self._query_bus is None:
            self._query_bus = self._dbus.SystemBus(private=True)
        return self._query_bus

    def _objects(self) -> dict:
        bus = self._bus()
        manager = self._dbus.Interface(bus.get_object("org.bluez", "/"),
                                       "org.freedesktop.DBus.ObjectManager")
        return manager.GetManagedObjects()

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
        if path is None:
            raise RuntimeError("Bluetooth controller unavailable")
        return self._dbus.Interface(self._bus().get_object("org.bluez", path), name)

    def _device(self, address: str):
        path = self._device_path(address)
        if path is None:
            raise self._dbus.exceptions.DBusException("Device not found",
                                                      name="org.bluez.Error.DoesNotExist")
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
