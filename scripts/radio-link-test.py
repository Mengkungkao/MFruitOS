#!/usr/bin/env python3
"""Over-the-air link test between two boards' SX126X (E22) radios (device validation).

  python3 scripts/radio-link-test.py listen --seconds 120 --echo   on board B
  python3 scripts/radio-link-test.py ping --count 40 --size 32     on board A

Uses the shared radio settings (~/.whisplay-os/shared/radio/radio.json:
port, frequency) as provisioned by scripts/setup-radio.sh (fixed
transmission, RSSI byte appended). Packets go to the broadcast address.
Each output line is JSON; RSSI dBm = -(256 - appended byte).

Before running: close radio apps (they hold the serial port), and hold the
backlight at 100% on both boards. With the HAT's stock jumpers the
backlight pin is the radio's M0, and any dimming (PWM) or screen-off leaves
the radio deaf (docs/quality/KNOWN_ISSUES.md KI-11).
"""
import argparse
import json
import os
import struct
import sys
import time

import serial

STORE = os.path.expanduser("~/.whisplay-os/shared/radio/radio.json")
PING, ECHO = b"OTP", b"OTE"


def settings():
    with open(STORE) as fp:
        cfg = json.load(fp)
    return cfg["port"], cfg["frequency_mhz"] - 850


def open_port(port):
    return serial.Serial(port, 9600, timeout=0.05)


def read_packet(ser, wait, expected=0):
    """One packet: bytes until a 50 ms gap (and at least ``expected`` bytes, as
    the module may hand over a long packet in two bursts). None if nothing
    arrives within ``wait``."""
    deadline = time.monotonic() + wait
    data = b""
    while time.monotonic() < deadline:
        chunk = ser.read(256)
        if chunk:
            data += chunk
            while True:
                more = ser.read(256)
                if not more and len(data) >= expected:
                    return data
                if not more and time.monotonic() > deadline:
                    return data
                data += more or b""
    return data or None


def rssi(byte):
    return -(256 - byte)


def send(ser, channel, payload):
    ser.write(b"\xff\xff" + bytes([channel]) + payload)
    ser.flush()


def listen(args):
    port, channel = settings()
    ser = open_port(port)
    end = time.monotonic() + args.seconds
    while time.monotonic() < end:
        packet = read_packet(ser, end - time.monotonic())
        if not packet:
            continue
        body, level = packet[:-1], rssi(packet[-1])
        line = {"t": round(time.time(), 3), "len": len(body), "rssi": level, "head": body[:3].decode("latin-1")}
        if body[:3] == PING and len(body) >= 5:
            seq = struct.unpack(">H", body[3:5])[0]
            line["seq"] = seq
            if args.echo:
                reply = ECHO + struct.pack(">Hb", seq, level)
                send(ser, channel, reply + b"." * max(0, len(body) - len(reply)))
        print(json.dumps(line), flush=True)


def ping(args):
    port, channel = settings()
    ser = open_port(port)
    results = []
    for seq in range(args.count):
        payload = PING + struct.pack(">H", seq)
        payload += b"x" * max(0, args.size - len(payload))
        ser.reset_input_buffer()
        start = time.monotonic()
        send(ser, channel, payload)
        got = None
        while time.monotonic() - start < args.timeout:
            packet = read_packet(ser, args.timeout - (time.monotonic() - start), expected=args.size + 1)
            if packet and packet[:3] == ECHO and len(packet) >= 7:
                echo_seq, there = struct.unpack(">Hb", packet[3:6])
                if echo_seq == seq:
                    got = {"seq": seq, "rtt_ms": round((time.monotonic() - start) * 1000),
                           "rssi_there": there, "rssi_here": rssi(packet[-1])}
                    break
        results.append(got or {"seq": seq, "lost": True})
        print(json.dumps(results[-1]), flush=True)
        time.sleep(args.interval)
    ok = [r for r in results if "rtt_ms" in r]
    summary = {"sent": len(results), "echoed": len(ok), "size": args.size}
    if ok:
        rtts = sorted(r["rtt_ms"] for r in ok)
        summary.update(rtt_ms_median=rtts[len(rtts) // 2], rtt_ms_max=rtts[-1],
                       rssi_there=[min(r["rssi_there"] for r in ok), max(r["rssi_there"] for r in ok)],
                       rssi_here=[min(r["rssi_here"] for r in ok), max(r["rssi_here"] for r in ok)])
    print(json.dumps({"summary": summary}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("listen")
    p.add_argument("--seconds", type=float, default=120)
    p.add_argument("--echo", action="store_true")
    p = sub.add_parser("ping")
    p.add_argument("--count", type=int, default=40)
    p.add_argument("--size", type=int, default=32)
    p.add_argument("--interval", type=float, default=0.3)
    p.add_argument("--timeout", type=float, default=4.0)
    args = parser.parse_args()
    {"listen": listen, "ping": ping}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
