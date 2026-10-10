"""Linux I2C (SMBus) transfers with the Python standard library only.

The kernel's ``i2c-dev`` interface: open ``/dev/i2c-N``, select the target
with ``ioctl(I2C_SLAVE)`` and run each transfer with ``ioctl(I2C_SMBUS)``.
This replaces python3-smbus, which some board images do not ship.

Errors are ``OSError`` with the kernel's errno; :func:`explain` turns the
common ones into a sentence for the user.
"""

from __future__ import annotations

import ctypes
import errno
import fcntl
import os
import threading

I2C_SLAVE = 0x0703
I2C_SMBUS = 0x0720
I2C_SMBUS_READ = 1
I2C_SMBUS_WRITE = 0
I2C_SMBUS_BYTE_DATA = 2
I2C_SMBUS_I2C_BLOCK_DATA = 8
I2C_SMBUS_BLOCK_MAX = 32


class _Data(ctypes.Union):
    _fields_ = [("byte", ctypes.c_uint8), ("word", ctypes.c_uint16),
                ("block", ctypes.c_uint8 * (I2C_SMBUS_BLOCK_MAX + 2))]


class _Args(ctypes.Structure):
    _fields_ = [("read_write", ctypes.c_uint8), ("command", ctypes.c_uint8),
                ("size", ctypes.c_uint32), ("data", ctypes.POINTER(_Data))]


def bus_path(bus: int, dev_dir: str = "/dev") -> str:
    return os.path.join(dev_dir, f"i2c-{int(bus)}")


def explain(exc: OSError, bus: int, addr: int | None = None,
            sys_dir: str = "/sys/bus/i2c/devices") -> str:
    """A short, actionable reason for an I2C failure."""
    where = f"I2C bus {bus}" + (f" address 0x{addr:02x}" if addr is not None else "")
    code = getattr(exc, "errno", None)
    if code == errno.ENOENT:
        if os.path.isdir(os.path.join(sys_dir, f"i2c-{int(bus)}")):
            # The bus exists; only the i2c-dev interface that makes /dev/i2c-N is missing.
            return (f"I2C bus {bus} is on, but /dev/i2c-{bus} is missing: the i2c-dev "
                    "kernel module is not loaded (scripts/install.sh sets it up)")
        return f"I2C bus {bus} is not enabled (/dev/i2c-{bus} is missing)"
    if code in (errno.EACCES, errno.EPERM):
        return (f"no permission for /dev/i2c-{bus}: the power service needs the "
                "i2c group (install it with scripts/install.sh)")
    if code == errno.EBUSY:
        return (f"{where} is claimed by a kernel driver (for example the "
                "pisugar_battery module); unload it to use mFruit power")
    if code in (errno.ENXIO, errno.EREMOTEIO, errno.EIO, errno.ETIMEDOUT):
        return f"no answer from {where}"
    return f"{where}: {exc.strerror or exc}"


class SMBus:
    """One open ``/dev/i2c-N``. Thread-safe: each transfer holds a lock."""

    def __init__(self, bus: int, dev_dir: str = "/dev"):
        self.bus = int(bus)
        self.path = bus_path(self.bus, dev_dir)
        self._fd = os.open(self.path, os.O_RDWR | getattr(os, "O_CLOEXEC", 0))
        self._addr: int | None = None
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            if self._fd >= 0:
                os.close(self._fd)
                self._fd = -1

    def __enter__(self) -> "SMBus":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------ transfers
    def _target(self, addr: int) -> None:
        if not 0x03 <= addr <= 0x77:
            raise ValueError(f"invalid 7-bit I2C address 0x{addr:02x}")
        if self._fd < 0:
            raise OSError(errno.EBADF, "I2C bus is closed")
        if self._addr != addr:
            fcntl.ioctl(self._fd, I2C_SLAVE, addr)
            self._addr = addr

    def _transfer(self, addr: int, read_write: int, command: int, size: int,
                  data: _Data) -> None:
        args = _Args(read_write, command & 0xFF, size, ctypes.pointer(data))
        with self._lock:
            self._target(addr)
            fcntl.ioctl(self._fd, I2C_SMBUS, args)

    def read_byte_data(self, addr: int, register: int) -> int:
        data = _Data()
        self._transfer(addr, I2C_SMBUS_READ, register, I2C_SMBUS_BYTE_DATA, data)
        return data.byte & 0xFF

    def write_byte_data(self, addr: int, register: int, value: int) -> None:
        data = _Data()
        data.byte = int(value) & 0xFF
        self._transfer(addr, I2C_SMBUS_WRITE, register, I2C_SMBUS_BYTE_DATA, data)

    def read_i2c_block_data(self, addr: int, register: int, length: int) -> list[int]:
        if not 1 <= length <= I2C_SMBUS_BLOCK_MAX:
            raise ValueError("block length must be 1..32")
        data = _Data()
        data.block[0] = length
        self._transfer(addr, I2C_SMBUS_READ, register, I2C_SMBUS_I2C_BLOCK_DATA, data)
        return [data.block[i + 1] for i in range(length)]

    def write_i2c_block_data(self, addr: int, register: int, values: list[int]) -> None:
        values = [int(v) & 0xFF for v in values]
        if not 1 <= len(values) <= I2C_SMBUS_BLOCK_MAX:
            raise ValueError("block length must be 1..32")
        data = _Data()
        data.block[0] = len(values)
        for i, value in enumerate(values):
            data.block[i + 1] = value
        self._transfer(addr, I2C_SMBUS_WRITE, register, I2C_SMBUS_I2C_BLOCK_DATA, data)
