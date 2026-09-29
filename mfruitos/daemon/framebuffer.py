"""Shared-framebuffer output (RGB565, big-endian) granted by whisplay-daemon."""

from __future__ import annotations

import logging
import mmap
import os

log = logging.getLogger("mfruitos.daemon.framebuffer")


class Framebuffer:
    """Maps the session-scoped ``buffer_handle`` returned by framebuffer.acquire.

    The buffer is only valid while this process holds foreground focus; after
    ``app_focus_revoked`` the daemon unlinks the file, so callers must
    ``detach()`` and stop drawing.
    """

    def __init__(self):
        self._file = None
        self._map: mmap.mmap | None = None
        self.path: str | None = None
        self.width = 0
        self.height = 0
        self.stride = 0

    @property
    def attached(self) -> bool:
        return self._map is not None

    @property
    def size(self) -> int:
        return self.stride * self.height

    def attach(self, info: dict) -> None:
        self.detach()
        path = str(info["buffer_handle"])
        width, height, stride = int(info["width"]), int(info["height"]), int(info["stride"])
        if info.get("pixel_format", "RGB565") != "RGB565":
            raise ValueError(f"unsupported pixel format {info.get('pixel_format')}")
        handle = open(path, "r+b")
        try:
            if os.fstat(handle.fileno()).st_size < stride * height:
                raise ValueError("framebuffer file is smaller than stride*height")
            mapped = mmap.mmap(handle.fileno(), stride * height)
        except Exception:
            handle.close()
            raise
        self._file, self._map = handle, mapped
        self.path, self.width, self.height, self.stride = path, width, height, stride
        log.debug("Attached framebuffer %s (%dx%d)", path, width, height)

    def write(self, frame: bytes) -> bool:
        if self._map is None:
            return False
        if len(frame) != self.size:
            log.error("Frame size %d does not match framebuffer size %d", len(frame), self.size)
            return False
        try:
            self._map[:] = frame
        except (ValueError, OSError) as exc:
            log.warning("Framebuffer write failed: %s", exc)
            self.detach()
            return False
        return True

    def detach(self) -> None:
        if self._map is not None:
            try:
                self._map.close()
            except (ValueError, OSError) as exc:
                log.debug("mmap close: %s", exc)
            self._map = None
        if self._file is not None:
            try:
                self._file.close()
            except OSError as exc:
                log.debug("framebuffer close: %s", exc)
            self._file = None
        self.path = None
