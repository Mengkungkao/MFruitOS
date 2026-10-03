"""Radio setup steps that run as a command (called by scripts/setup-radio.sh).

    python3 -m mfruitos.hosts.lora status [--home DIR]
    sudo python3 -m mfruitos.hosts.lora check
    sudo python3 -m mfruitos.hosts.lora provision --band au915 [--frequency MHZ]
         [--air-speed BPS] [--power DBM] [--home DIR] [--owner USER]

``check`` and ``provision`` need root: M0/M1 are also the Whisplay LCD's
lines, so whisplay-daemon is stopped for a few seconds (which closes any
running app, freeing the serial port) and started again afterwards.
``provision`` then records the settings in the shared radio directory,
owned by ``--owner``, where every radio app reads them.
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import subprocess
import sys
import time

from mfruitos.hosts.lora import modelines, sx126x
from mfruitos.hosts.lora.readiness import radio_status
from mfruitos.sdk.radio import settings as radio_settings

DAEMON = "whisplay-daemon.service"


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


def check(args) -> int:
    def action(configurator):
        reg = configurator.read()
        if reg is None:
            print("! no reply from the module -- wrong port, or wiring?", file=sys.stderr)
            return 1
        print("module settings:")
        _print_registers(reg)
        return 0
    return _session(args.port, action)


def provision(args) -> int:
    low, high, default = radio_settings.BANDS[args.band]
    frequency = args.frequency or default
    if not low <= frequency <= high:
        print(f"! {frequency} MHz is outside {args.band} ({low}-{high} MHz)", file=sys.stderr)
        return 2
    register = sx126x.encode(0, frequency, args.air_speed, args.power)

    def action(configurator):
        print(f"writing: {frequency} MHz ({args.band}), {args.air_speed} bps, "
              f"{args.power} dBm (kept through power-off)")
        if not configurator.write(register):
            print("! the module did not acknowledge the write", file=sys.stderr)
            return 1
        reg = configurator.read()
        if reg is None or sx126x.describe(reg)["frequency_mhz"] != frequency:
            print("! the module did not read back the new settings", file=sys.stderr)
            return 1
        print("read back:")
        _print_registers(reg)
        return 0

    result = _session(args.port, action)
    if result != 0:
        return result
    directory = radio_settings.radio_dir(args.home)
    radio_settings.save_radio(radio_settings.RadioSettings(
        frequency_mhz=frequency, air_speed=args.air_speed, power_dbm=args.power,
        port=args.port, band=args.band, provisioned_at=time.strftime("%Y-%m-%dT%H:%M:%S%z")),
        directory)
    if args.owner:
        user = pwd.getpwnam(args.owner)
        for folder, _, names in os.walk(os.path.dirname(directory)):
            for path in [folder] + [os.path.join(folder, n) for n in names]:
                os.chown(path, user.pw_uid, user.pw_gid)
    print(f"recorded in {directory}/radio.json")
    print("Do the same on every other radio: until they match, they cannot hear each other.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m mfruitos.hosts.lora",
                                     description="MFruit OS LoRa radio setup steps")
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status", help="readiness as JSON (no root needed)")
    status.add_argument("--home")
    chk = sub.add_parser("check", help="read the module's settings (root)")
    chk.add_argument("--port", default="/dev/ttyS0")
    prov = sub.add_parser("provision", help="write the module's settings (root)")
    prov.add_argument("--band", choices=sorted(radio_settings.BANDS), default="au915")
    prov.add_argument("--frequency", type=int, help="MHz inside the band (default: its middle)")
    prov.add_argument("--air-speed", type=int, default=2400, choices=sorted(sx126x.AIR_SPEED))
    prov.add_argument("--power", type=int, default=22, choices=sorted(sx126x.POWER_DBM))
    prov.add_argument("--port", default="/dev/ttyS0")
    prov.add_argument("--home", help="MFruit OS home of the user the radio belongs to")
    prov.add_argument("--owner", help="user who owns the shared radio files")
    args = parser.parse_args(argv)
    if args.command == "status":
        report = radio_status(args.home)
        print(json.dumps(report, indent=2))
        return 0 if report["ready"] else 1
    return check(args) if args.command == "check" else provision(args)


if __name__ == "__main__":
    raise SystemExit(main())
