"""Entry point: ``python3 -m mfruitos``."""

from __future__ import annotations

import argparse
import logging
import signal

from mfruitos import __version__
from mfruitos.logs import setup_logging
from mfruitos.paths import package_root, resolve_paths

log = logging.getLogger("mfruitos.main")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(prog="mfruitos", description="MFruit OS for Whisplay")
    parser.add_argument("--home", help="data directory (default ~/.whisplay-os)")
    parser.add_argument("--socket", help="whisplay-daemon socket path")
    parser.add_argument("--debug", action="store_true", help="debug logging")
    parser.add_argument("--self-test", action="store_true",
                        help="import every module and render every screen offscreen, then exit")
    parser.add_argument("--preview", metavar="DIR",
                        help="render all screens to PNG files in DIR (no daemon needed)")
    parser.add_argument("--version", action="version", version=f"MFruit OS {__version__}")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.self_test or args.preview:
        from mfruitos.launcher.preview import run_preview
        setup_logging(None, debug=args.debug, stderr=not args.self_test)
        return run_preview(args.preview)

    paths = resolve_paths(args.home)
    paths.ensure()
    setup_logging(paths.logs_dir, debug=args.debug)
    from mfruitos.launcher.runtime import Runtime
    runtime = Runtime(paths, package_root(), socket_path=args.socket)

    def on_signal(signum, _frame):
        log.info("Received signal %d; shutting down", signum)
        runtime.loop.post(runtime.shutdown, 0)
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    try:
        return runtime.run()
    except Exception:
        log.critical("MFruit OS crashed", exc_info=True)
        return 1
