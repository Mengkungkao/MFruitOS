"""``python3 -m mfruitos.power`` — the power service and its command line.

    serve [--fake MODEL] [--home DIR]   run the service (mfruit-power.service)
    status [--details]                  battery state and settings (JSON)
    set KEY VALUE                       change a setting (VALUE is JSON, or text)
    probe                               look for the battery board again
    level                               one line, e.g. "82% charging" (phone setup info)
    shutdown | reboot                   safe power off / restart
    clock save | load                   board clock <- system / system <- board

``--fake pisugar3`` (or pisugar2-4led, pisugar2-2led, pisugar2-pro) runs the
service against a simulated board: nothing is powered off and the clock is
not changed; the PiSugar socket is then created in the state directory.
"""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import signal
import subprocess
import sys

from mfruitos import __version__, power
from mfruitos.paths import package_root, resolve_paths

log = logging.getLogger("mfruitos.power")
RESTART_EXIT = 75          # code updated: systemd starts the new version


def _setup_logging(logs_dir: str, debug: bool) -> None:
    root = logging.getLogger("mfruitos")
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    root.propagate = False
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(logging.Formatter("%(levelname)-8s %(name)s: %(message)s"))
    root.addHandler(stream)
    os.makedirs(logs_dir, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(os.path.join(logs_dir, "power.log"),
                                                   maxBytes=256 * 1024, backupCount=2,
                                                   encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
    root.addHandler(handler)


def active_code(paths) -> str:
    """The installed version the ``system/current`` link points at (else this
    package). Under systemd the working directory is the resolved version, so
    the imported modules' own path never changes; the link does on an update."""
    link = os.path.join(paths.system_dir, "current")
    return os.path.realpath(link if os.path.lexists(link) else package_root())


def pisugar_server_active() -> bool:
    """PiSugar's own server drives the same board; never run both."""
    try:
        result = subprocess.run(["systemctl", "is-active", "--quiet", "pisugar-server.service"],
                                timeout=5, stdin=subprocess.DEVNULL)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def serve(args) -> int:
    from mfruitos.hosts.pisugar import detect, fake
    from mfruitos.power.config import PowerConfig, first_load
    from mfruitos.power.server import PowerServer
    from mfruitos.power.service import DryRunner, PowerService
    from mfruitos.system import sdnotify

    paths = resolve_paths(args.home)
    paths.ensure()
    _setup_logging(paths.logs_dir, args.debug)
    log.info("mFruit power %s starting%s", __version__,
             f" with a simulated {args.fake}" if args.fake else "")
    config = PowerConfig(power.config_file(paths))
    imported = first_load(config) if not args.fake else (config.load() or [])
    for problem in config.load_errors:
        log.warning(problem)

    kwargs = {}
    compat_path = power.COMPAT_SOCKET
    if args.fake:
        bus, board = fake.simulated_bus(args.fake)

        def open_board(bus_number, model, addr):
            return bus, detect.build(bus, bus_number, model if model != "auto" else args.fake,
                                     addr)
        kwargs = {"open_board": open_board, "runner": DryRunner(),
                  "set_clock": lambda when: log.warning("dry run: would set the clock to %s",
                                                        when.isoformat())}
        compat_path = os.path.join(paths.state_dir, "pisugar-server.sock")
    service = PowerService(config, **kwargs)
    blocked = not args.fake and pisugar_server_active()
    server = PowerServer(service, power.api_socket(paths),
                         compat_path if config.get("compat_socket") and not blocked else None)
    try:
        server.bind()
    except OSError as exc:
        log.error("Cannot open the power socket: %s", exc)
        return 1
    if imported:
        log.info("Settings imported from PiSugar's power manager: %s", ", ".join(imported))
    if blocked:
        service.error = ("PiSugar's pisugar-server is running and owns the battery board; "
                         "stop it to use mFruit power: sudo systemctl disable --now "
                         "pisugar-server")
        log.warning(service.error)
    else:
        service.start()

    started_code = active_code(paths)

    def check_code() -> None:
        if active_code(paths) != started_code and not service.shutting_down:
            log.info("mFruit OS was updated; restarting the power service")
            server.stop()
            check_code.restart = True
    check_code.restart = False
    server.every(60.0, check_code)

    interval = sdnotify.watchdog_interval()
    if interval:
        server.every(interval, lambda: sdnotify.notify("WATCHDOG=1"))
    sdnotify.notify("READY=1")

    def on_signal(signum, _frame):
        log.info("Received signal %d; stopping", signum)
        server.stop()
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    try:
        server.run()
    finally:
        sdnotify.notify("STOPPING=1")
        server.close()
        service.close_board()
    return RESTART_EXIT if check_code.restart else 0


def _value(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return text


def client_command(args) -> int:
    from mfruitos.power.client import PowerClient, PowerError
    client = PowerClient(power.api_socket(resolve_paths(args.home)))
    try:
        if args.command == "status":
            result = client.status(details=args.details)
        elif args.command == "set":
            result = client.set(args.key, _value(args.value))
        elif args.command == "probe":
            result = client.probe()
        elif args.command == "level":
            status = client.status()
            if not status.get("present") or status.get("level") is None:
                print("no battery")
                return 0
            state = "charging" if status.get("charging") else (
                "plugged in" if status.get("plugged") else "on battery")
            print(f"{status['level']}% {state}")
            return 0
        elif args.command in ("shutdown", "reboot"):
            client.shutdown(reboot=args.command == "reboot", reason="mfruitctl")
            result = {"ok": True}
        elif args.command == "clock":
            result = {"time": client.clock(args.action)}
        else:
            return 2
    except PowerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"the power service is not running ({exc}); "
              "start it with: sudo systemctl start mfruit-power", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m mfruitos.power",
                                     description="mFruit OS power management")
    parser.add_argument("--home", help="data directory (default ~/.whisplay-os)")
    sub = parser.add_subparsers(dest="command", required=True)
    serve_p = sub.add_parser("serve", help="run the power service")
    serve_p.add_argument("--fake", choices=("pisugar3", "pisugar2-4led", "pisugar2-2led",
                                            "pisugar2-pro"),
                         help="simulate this board (development; nothing is powered off)")
    serve_p.add_argument("--debug", action="store_true")
    status_p = sub.add_parser("status", help="battery state and settings")
    status_p.add_argument("--details", action="store_true", help="also read the board settings")
    set_p = sub.add_parser("set", help="change a setting")
    set_p.add_argument("key")
    set_p.add_argument("value")
    sub.add_parser("probe", help="look for the battery board again")
    sub.add_parser("level", help="battery level in one line")
    sub.add_parser("shutdown", help="power off safely")
    sub.add_parser("reboot", help="restart safely")
    clock_p = sub.add_parser("clock", help="copy the time between system and board")
    clock_p.add_argument("action", choices=("save", "load"))
    args = parser.parse_args(argv)
    if args.command == "serve":
        return serve(args)
    return client_command(args)


if __name__ == "__main__":
    sys.exit(main())
