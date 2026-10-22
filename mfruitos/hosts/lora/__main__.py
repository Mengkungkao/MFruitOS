"""Radio setup steps that run as a command (called by scripts/setup-radio.sh).

    python3 -m mfruitos.hosts.lora status [--home DIR]
    sudo python3 -m mfruitos.hosts.lora check [--home DIR]
    sudo python3 -m mfruitos.hosts.lora provision --band au915 [--frequency MHZ]
         [--air-speed BPS] [--power DBM] [--home DIR] [--owner USER]
    python3 -m mfruitos.hosts.lora record --band au915 [--frequency MHZ] ... --home DIR
    python3 -m mfruitos.hosts.lora ensure --home DIR
    python3 -m mfruitos.hosts.lora boot-unit --code DIR --home DIR --owner USER [--port PORT]

The module keeps its settings in its own memory, so what ``radio.json``
records is only what it was given once. A module that is new, swapped for
another or reset to its factory settings (868 MHz, sending transparently)
cannot hear radios set up by mFruit OS, while every screen still shows the
recorded frequency. So the settings are compared with the module itself:

``check``, ``provision`` and ``ensure`` need M0/M1, which are also the
Whisplay LCD's lines: while whisplay-daemon runs they need root to stop it
for a few seconds (which closes any running app, freeing the serial port).
``check`` only reads. ``provision`` writes the given settings where the
module differs and records them in the shared radio directory, owned by
``--owner``, where every radio app reads them. ``record`` writes that record
without touching the module (the boot check below writes the module).

``ensure`` is the boot check: ``boot-unit`` prints the systemd unit
setup-radio.sh and install.sh install. It runs at every boot as the user,
before whisplay-daemon starts (so nothing has to be stopped), reads the
module and writes the recorded settings back where they differ. Every
command that reads the module leaves its result in ``module.json`` beside
``radio.json``, which the readiness check reports.
"""

from __future__ import annotations

import argparse
import grp
import json
import os
import pwd
import re
import stat
import subprocess
import sys
import time

from mfruitos.hosts.lora import modelines, sx126x
from mfruitos.hosts.lora.readiness import MODULE_FILE, radio_status
from mfruitos.sdk.radio import settings as radio_settings

DAEMON = "whisplay-daemon.service"
BOOT_UNIT = "mfruit-radio-setup.service"
DEFAULT_PORT = "/dev/ttyS0"
_PORT_PATTERN = re.compile(r"/dev/tty[A-Za-z0-9]+")

# What reading the module found (module.json "result").
MATCHED = "ok"             # it already had the recorded settings
RESTORED = "restored"      # they differed and were written back
NO_REPLY = "no_reply"      # it did not answer: HAT, wiring or port
FAILED = "failed"          # the write was refused or did not read back
UNUSABLE = "invalid"       # radio.json holds values the module cannot take


def _systemctl(action: str) -> bool:
    try:
        return subprocess.run(["systemctl", action, DAEMON], timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _daemon_active() -> bool:
    try:
        return subprocess.run(["systemctl", "is-active", "--quiet", DAEMON],
                              timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _session(port: str, action):
    """Stop the daemon, hold M0/M1 and the port, run ``action``, undo it all."""
    lines = modelines.board_lines()
    if lines is None:
        print("! this board's M0/M1 lines are not known", file=sys.stderr)
        return 2
    restart = _daemon_active()
    if restart:
        if os.geteuid() != 0:
            print("! run with sudo: whisplay-daemon holds M0/M1 (the LCD's lines)",
                  file=sys.stderr)
            return 2
        print("stopping whisplay-daemon for a few seconds (this closes any open app)")
        if not _systemctl("stop"):
            print("! could not stop whisplay-daemon", file=sys.stderr)
            return 1
        time.sleep(1.0)
    configurator = None
    try:
        try:
            configurator = sx126x.Configurator(port, modelines.ModeLines(lines))
        except Exception as exc:  # gpiod/serial failures vary by board and state
            print(f"! cannot take M0/M1 or open {port}: {exc}", file=sys.stderr)
            return 1
        return action(configurator)
    finally:
        if configurator is not None:
            configurator.close()
        if restart:
            print("starting whisplay-daemon")
            _systemctl("start")


def _print_registers(reg: bytes) -> None:
    for key, value in sx126x.describe(reg).items():
        print(f"  {key:<20} {value}")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _wanted(settings) -> bytes:
    """The register write for recorded settings (ValueError if unusable)."""
    return sx126x.encode(0, settings.frequency_mhz, settings.air_speed, settings.power_dbm,
                         net_id=settings.net_id)


def _bring(configurator, wanted: bytes, found: list) -> str:
    """Read the module; write ``wanted`` only where it differs, then check
    every readable register. ``found`` receives the differences seen first."""
    reg = configurator.read()
    if reg is None:
        print("! no reply from the module -- is the LoRa HAT seated, its M0/M1 jumpers "
              "removed and the serial console off the port?", file=sys.stderr)
        return NO_REPLY
    found.extend(sx126x.differences(reg, wanted))
    if not found:
        print("the module already has these settings:")
        _print_registers(reg)
        return MATCHED
    print("the module has other settings:")
    for difference in found:
        print(f"  {difference}")
    print("writing the recorded settings (kept through power-off)")
    if not configurator.write(wanted):
        print("! the module did not acknowledge the write", file=sys.stderr)
        return FAILED
    reg = configurator.read()
    left = sx126x.differences(reg, wanted) if reg is not None else ["no reply after writing"]
    if left:
        print(f"! the module did not read back the new settings: {'; '.join(left)}",
              file=sys.stderr)
        return FAILED
    print("read back:")
    _print_registers(reg)
    return RESTORED


def _save_status(directory: str, result: str, found: list, settings, by: str) -> None:
    status = {"result": result, "checked_at": _now(), "by": by, "differences": found}
    if settings is not None:
        status.update(frequency_mhz=settings.frequency_mhz, air_speed=settings.air_speed)
    try:
        radio_settings.write_json(os.path.join(directory, MODULE_FILE), status)
    except OSError as exc:
        print(f"! could not record the result in {directory}: {exc}", file=sys.stderr)


def _hand_over(directory: str, owner: str | None) -> None:
    """Give the shared radio folder to ``owner`` (run as root). Links are
    changed, never followed: a link in the user's folder must not make root
    hand over a file outside it."""
    if not owner:
        return
    user = pwd.getpwnam(owner)
    for folder, _, names in os.walk(os.path.dirname(directory)):
        for path in [folder] + [os.path.join(folder, n) for n in names]:
            os.chown(path, user.pw_uid, user.pw_gid, follow_symlinks=False)


def _give_back(directory: str) -> None:
    """Run as root (``sudo ... ensure``): the files just written go back to
    whoever owns the shared radio folder, so the apps can still read them."""
    if os.geteuid() != 0:
        return
    try:
        folder = os.lstat(directory)
    except OSError:
        return
    if not stat.S_ISDIR(folder.st_mode) or folder.st_uid == 0:
        return
    for name in (radio_settings.RADIO_FILE, MODULE_FILE):
        try:
            os.chown(os.path.join(directory, name), folder.st_uid, folder.st_gid,
                     follow_symlinks=False)
        except OSError:
            pass


def check(args) -> int:
    recorded = radio_settings.load_radio(radio_settings.radio_dir(args.home)) if args.home else None

    def action(configurator):
        reg = configurator.read()
        if reg is None:
            print("! no reply from the module -- wrong port, or wiring?", file=sys.stderr)
            return 1
        print("module settings:")
        _print_registers(reg)
        if recorded is None:
            return 0
        try:
            found = sx126x.differences(reg, _wanted(recorded))
        except ValueError as exc:
            print(f"! radio.json holds settings the module cannot take: {exc}", file=sys.stderr)
            return 1
        if not found:
            print(f"matches the recorded settings ({recorded.frequency_mhz} MHz, "
                  f"{recorded.air_speed} bps)")
            return 0
        print("! differs from the recorded settings (provision, or reboot: the boot check "
              "writes them back):")
        for difference in found:
            print(f"  {difference}")
        return 1
    return _session(args.port, action)


def _settings_from_args(args):
    low, high, default = radio_settings.BANDS[args.band]
    frequency = args.frequency or default
    if not low <= frequency <= high:
        print(f"! {frequency} MHz is outside {args.band} ({low}-{high} MHz)", file=sys.stderr)
        return None
    return radio_settings.RadioSettings(
        frequency_mhz=frequency, air_speed=args.air_speed, power_dbm=args.power,
        port=args.port, band=args.band)


def _same_settings(a, b) -> bool:
    keys = ("frequency_mhz", "air_speed", "power_dbm", "net_id", "port", "band", "module")
    return a is not None and b is not None and all(getattr(a, k) == getattr(b, k) for k in keys)


def provision(args) -> int:
    settings = _settings_from_args(args)
    if settings is None:
        return 2
    wanted = _wanted(settings)
    directory = radio_settings.radio_dir(args.home)
    found: list = []
    outcome = {}

    def action(configurator):
        print(f"wanted: {settings.frequency_mhz} MHz ({args.band}), {args.air_speed} bps, "
              f"{args.power} dBm")
        outcome["result"] = _bring(configurator, wanted, found)
        return 0 if outcome["result"] in (MATCHED, RESTORED) else 1

    result = _session(args.port, action)
    if "result" in outcome:
        _save_status(directory, outcome["result"], found, settings, "provision")
    if result != 0:
        _hand_over(directory, args.owner)
        return result
    recorded = radio_settings.load_radio(directory)
    if outcome["result"] == MATCHED and _same_settings(recorded, settings) \
            and recorded.provisioned_at:
        settings.provisioned_at = recorded.provisioned_at   # nothing changed
    else:
        settings.provisioned_at = _now()
    radio_settings.save_radio(settings, directory)
    _hand_over(directory, args.owner)
    print(f"recorded in {directory}/radio.json")
    print("Do the same on every other radio: until they match, they cannot hear each other.")
    return 0


def record(args) -> int:
    """Record the wanted settings for the boot check, without the module."""
    settings = _settings_from_args(args)
    if settings is None:
        return 2
    directory = radio_settings.radio_dir(args.home)
    if _same_settings(radio_settings.load_radio(directory), settings):
        print(f"already recorded in {directory}/radio.json")
        return 0
    radio_settings.save_radio(settings, directory)   # provisioned_at stays empty until written
    print(f"recorded in {directory}/radio.json; the module gets them at the next boot")
    return 0


def ensure(args) -> int:
    """The boot check: give the module the recorded settings if it lacks them."""
    directory = radio_settings.radio_dir(args.home)
    settings = radio_settings.load_radio(directory)
    if settings is None:
        print(f"the radio is not set up ({directory}/radio.json): nothing to check")
        return 0
    try:
        wanted = _wanted(settings)
    except ValueError as exc:
        print(f"! {directory}/radio.json holds settings the module cannot take: {exc}",
              file=sys.stderr)
        _save_status(directory, UNUSABLE, [str(exc)], settings, "boot check")
        _give_back(directory)
        return 1
    found: list = []
    outcome = {}

    def action(configurator):
        outcome["result"] = _bring(configurator, wanted, found)
        return 0 if outcome["result"] in (MATCHED, RESTORED) else 1

    code = _session(settings.port, action)
    if "result" not in outcome:
        return code                    # M0/M1 or the port could not be taken
    if outcome["result"] == RESTORED or (outcome["result"] == MATCHED
                                         and not settings.provisioned_at):
        # A new date tells the apps the module was (re)written, so they learn
        # its abilities again (RadioConnect asks for the channel level once per date).
        settings.provisioned_at = _now()
        radio_settings.save_radio(settings, directory)
    _save_status(directory, outcome["result"], found, settings, "boot check")
    _give_back(directory)
    return code


def _device_groups(paths) -> list:
    """Groups (not root's) owning the devices the boot check opens."""
    names = set()
    for path in paths:
        try:
            gid = os.stat(path).st_gid
            if gid:
                names.add(grp.getgrgid(gid).gr_name)
        except (OSError, KeyError):
            continue
    return sorted(names)


def boot_unit(args) -> str:
    """The unit that checks the module's settings at every boot, as the user."""
    for value in (args.code, args.home, args.owner, args.port):
        if not value or any(c.isspace() or c in "\\\"'%$;" for c in value):
            raise ValueError(f"unsafe value for a unit file: {value!r}")
    if not _PORT_PATTERN.fullmatch(args.port):
        raise ValueError(f"not a serial port: {args.port!r}")
    lines = modelines.board_lines()
    groups = " ".join(_device_groups([args.port] + ([lines.chip] if lines else [])))
    supplementary = f"SupplementaryGroups={groups}\n" if groups else ""
    return f"""# Installed by mFruit OS (scripts/setup-radio.sh, scripts/install.sh). At every
# boot, before whisplay-daemon takes the LoRa module's M0/M1 lines, it reads the
# module's settings and writes the recorded ones back where they differ, so a
# new, swapped or reset module still matches the other radios. As the user.
# Result: {args.home}/shared/radio/module.json
# Undo: systemctl disable {BOOT_UNIT}; rm /etc/systemd/system/{BOOT_UNIT}
[Unit]
Description=mFruit OS: check the LoRa radio module's settings
After=local-fs.target
Before={DAEMON} whisplay-os.service
ConditionPathExists={args.port}

[Service]
Type=oneshot
User={args.owner}
{supplementary}Environment=PYTHONPATH={args.code}
ExecStart=/usr/bin/python3 -m mfruitos.hosts.lora ensure --home {args.home}
TimeoutStartSec=60

[Install]
WantedBy=multi-user.target
"""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m mfruitos.hosts.lora",
                                     description="mFruit OS LoRa radio setup steps")
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status", help="readiness as JSON (no root needed)")
    status.add_argument("--home")
    chk = sub.add_parser("check", help="read the module's settings (root while the daemon runs)")
    chk.add_argument("--port", default=DEFAULT_PORT)
    chk.add_argument("--home", help="also compare with this mFruit OS home's radio.json")
    for name, text in (("provision", "write the module's settings where they differ (root)"),
                       ("record", "record the settings for the boot check (no module)")):
        cmd = sub.add_parser(name, help=text)
        cmd.add_argument("--band", choices=sorted(radio_settings.BANDS), default="au915")
        cmd.add_argument("--frequency", type=int, help="MHz inside the band (default: its middle)")
        cmd.add_argument("--air-speed", type=int, default=2400, choices=sorted(sx126x.AIR_SPEED))
        cmd.add_argument("--power", type=int, default=22, choices=sorted(sx126x.POWER_DBM))
        cmd.add_argument("--port", default=DEFAULT_PORT)
        cmd.add_argument("--home", help="mFruit OS home of the user the radio belongs to")
        if name == "provision":
            cmd.add_argument("--owner", help="user who owns the shared radio files")
    keep = sub.add_parser("ensure", help="boot check: give the module the recorded settings")
    keep.add_argument("--home", required=True)
    unit = sub.add_parser("boot-unit", help="print the unit that checks the module at boot")
    unit.add_argument("--port", default=DEFAULT_PORT)
    unit.add_argument("--code", required=True, help="mFruit OS code directory (PYTHONPATH)")
    unit.add_argument("--home", required=True)
    unit.add_argument("--owner", required=True)
    args = parser.parse_args(argv)
    if args.command == "boot-unit":
        try:
            sys.stdout.write(boot_unit(args))
        except ValueError as exc:
            print(f"! {exc}", file=sys.stderr)
            return 2
        return 0
    if args.command == "status":
        report = radio_status(args.home)
        print(json.dumps(report, indent=2))
        return 0 if report["ready"] else 1
    return {"check": check, "provision": provision, "record": record,
            "ensure": ensure}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
