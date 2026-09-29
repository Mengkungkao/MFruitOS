"""Single-threaded event loop with timers.

All UI state is owned by the loop thread. Other threads (daemon events,
workers, control socket) hand work over with :meth:`EventLoop.post`. The loop
sleeps until the next timer or posted item — there is no polling.
"""

from __future__ import annotations

import heapq
import itertools
import logging
import queue
import threading
import time
from typing import Any, Callable

log = logging.getLogger("mfruitos.loop")


class Timer:
    __slots__ = ("due", "seq", "callback", "args", "cancelled")

    def __init__(self, due: float, seq: int, callback: Callable, args: tuple):
        self.due = due
        self.seq = seq
        self.callback = callback
        self.args = args
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def __lt__(self, other: "Timer") -> bool:
        return (self.due, self.seq) < (other.due, other.seq)


class EventLoop:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self._queue: queue.Queue = queue.Queue()
        self._timers: list[Timer] = []
        self._seq = itertools.count()
        self._running = False
        self._thread_id: int | None = None
        self.wakeups = 0

    # ------------------------------------------------------------ scheduling
    def post(self, callback: Callable, *args: Any) -> None:
        """Run ``callback(*args)`` on the loop thread (thread-safe)."""
        self._queue.put((callback, args))

    def call_later(self, delay: float, callback: Callable, *args: Any) -> Timer:
        """Schedule on the loop thread. Must be called from the loop thread."""
        timer = Timer(self.clock() + max(0.0, delay), next(self._seq), callback, args)
        heapq.heappush(self._timers, timer)
        return timer

    def in_loop_thread(self) -> bool:
        return self._thread_id == threading.get_ident()

    # ----------------------------------------------------------------- run
    def stop(self) -> None:
        self.post(self._halt)

    def _halt(self) -> None:
        self._running = False

    def run(self) -> None:
        self._running = True
        self._thread_id = threading.get_ident()
        while self._running:
            self.run_once(block=True)

    def run_once(self, block: bool = False, max_wait: float | None = None) -> None:
        """Process due timers and queued work once (used by tests too)."""
        self.wakeups += 1
        self._run_due_timers()
        timeout = self._next_timeout()
        if max_wait is not None:
            timeout = max_wait if timeout is None else min(timeout, max_wait)
        try:
            if block:
                item = self._queue.get(timeout=timeout)
            else:
                item = self._queue.get_nowait()
        except queue.Empty:
            item = None
        while item is not None:
            self._invoke(*item)
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                item = None
        self._run_due_timers()

    def _next_timeout(self) -> float | None:
        while self._timers and self._timers[0].cancelled:
            heapq.heappop(self._timers)
        if not self._timers:
            return None
        return max(0.0, self._timers[0].due - self.clock())

    def _run_due_timers(self) -> None:
        now = self.clock()
        while self._timers and self._timers[0].due <= now:
            timer = heapq.heappop(self._timers)
            if not timer.cancelled:
                self._invoke(timer.callback, timer.args)

    def _invoke(self, callback: Callable, args: tuple) -> None:
        try:
            callback(*args)
        except Exception:  # one faulty handler must not take down the launcher
            log.exception("Unhandled error in %s", getattr(callback, "__qualname__", callback))
