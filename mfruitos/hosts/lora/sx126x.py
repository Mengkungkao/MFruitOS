"""SX126X (E22-900T22S) configuration: register encoding and the
read/write handshake in configuration mode (M0=0, M1=1).

Ported from WalkieTalkie's app/radio/sx126x.py (its ``configure`` and
``read_settings``), without the transmit/receive path the apps keep. The
settings are written to register header 0xC0, so the module keeps them
through power-off and the apps never need the mode pins.

pyserial is imported only when a port is opened (the radio setup installs
python3-serial); register encoding and decoding need nothing.
"""

from __future__ import annotations

import time

UART_BAUD = {1200: 0x00, 2400: 0x20, 4800: 0x40, 9600: 0x60,
             19200: 0x80, 38400: 0xA0, 57600: 0xC0, 115200: 0xE0}
AIR_SPEED = {300: 0x00, 1200: 0x01, 2400: 0x02, 4800: 0x03, 9600: 0x04,
             19200: 0x05, 38400: 0x06, 62500: 0x07}
POWER_DBM = {22: 0x00, 17: 0x01, 13: 0x02, 10: 0x03}
BUFFER_SIZE = {240: 0x00, 128: 0x40, 64: 0x80, 32: 0xC0}
REG_PERSIST = 0xC0
REG_VOLATILE = 0xC2
BAND_START = 850          # E22-900T22S: channel = frequency - 850 MHz
MAX_CHANNEL = 80          # 850-930 MHz


def channel_for(frequency_mhz: int) -> int:
    channel = int(frequency_mhz) - BAND_START
    if not 0 <= channel <= MAX_CHANNEL:
        raise ValueError(f"{frequency_mhz} MHz is outside the module's "
                         f"{BAND_START}-{BAND_START + MAX_CHANNEL} MHz range")
    return channel


def encode(address: int, frequency_mhz: int, air_speed: int = 2400, power: int = 22,
           net_id: int = 0, buffer_size: int = 240, rssi: bool = True,
           persist: bool = True) -> bytes:
    """The 12-byte register write the module expects."""
    for name, table, value in (("air speed", AIR_SPEED, air_speed), ("power", POWER_DBM, power),
                               ("buffer size", BUFFER_SIZE, buffer_size)):
        if value not in table:
            raise ValueError(f"unsupported {name}: {value} (have {sorted(table)})")
    return bytes([
        REG_PERSIST if persist else REG_VOLATILE, 0x00, 0x09,
        (address >> 8) & 0xFF, address & 0xFF, net_id & 0xFF,
        UART_BAUD[9600] + AIR_SPEED[air_speed],
        # +0x20 enables ambient-noise RSSI readback.
        BUFFER_SIZE[buffer_size] + POWER_DBM[power] + 0x20,
        channel_for(frequency_mhz),
        # 0x40 = fixed-point (addressed) transmission; 0x80 appends a
        # per-packet RSSI byte, which the apps' deframers read.
        0x43 + (0x80 if rssi else 0x00),
        0x00, 0x00,
    ])


def describe(reg: bytes) -> dict:
    """Decode a 12-byte register dump."""
    def inv(table, value):
        return next((k for k, v in table.items() if v == value), None)
    return {
        "address": (reg[3] << 8) | reg[4],
        "net_id": reg[5],
        "uart_baud": inv(UART_BAUD, reg[6] & 0xE0),
        "air_speed": inv(AIR_SPEED, reg[6] & 0x07),
        "power_dbm": inv(POWER_DBM, reg[7] & 0x03),
        "buffer_size": inv(BUFFER_SIZE, reg[7] & 0xC0),
        "channel": reg[8],
        "frequency_mhz": BAND_START + reg[8],
        "fixed_transmission": bool(reg[9] & 0x40),
        "rssi_appended": bool(reg[9] & 0x80),
    }


class Configurator:
    """Holds the port and the mode lines for one provisioning session."""

    def __init__(self, port: str, mode_lines, serial_port=None, settle: float = 0.1):
        self.mode = mode_lines
        self.settle = settle
        if serial_port is None:
            import serial  # python3-serial, installed by the radio setup
            serial_port = serial.Serial(port, 9600, timeout=1.0, exclusive=True)
        self.ser = serial_port

    def _config_mode(self, on: bool) -> None:
        self.mode.set(0, 1 if on else 0)
        time.sleep(self.settle)

    def read(self) -> bytes | None:
        self._config_mode(True)
        try:
            self.ser.reset_input_buffer()
            self.ser.write(bytes([0xC1, 0x00, 0x09]))
            self.ser.flush()
            time.sleep(3 * self.settle)
            reply = self.ser.read(12)
        finally:
            self._config_mode(False)
        return reply if reply and len(reply) == 12 and reply[0] == 0xC1 else None

    def write(self, register: bytes, attempts: int = 3) -> bool:
        self._config_mode(True)
        try:
            for _ in range(attempts):
                self.ser.reset_input_buffer()
                self.ser.write(register)
                self.ser.flush()
                time.sleep(3 * self.settle)
                reply = self.ser.read(12)
                if reply and reply[0] == 0xC1:
                    return True
                time.sleep(3 * self.settle)
            return False
        finally:
            self._config_mode(False)

    def close(self) -> None:
        try:
            self.ser.close()
        finally:
            self.mode.close()
