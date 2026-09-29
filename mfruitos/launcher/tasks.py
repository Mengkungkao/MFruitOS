"""Background work. Two lanes so a long install never blocks quick lookups:

``quick``  system info, diagnostics, release lists
``jobs``   update checks, installs, uninstalls (one at a time)

Results are posted back to the event loop; callbacks always run on the UI thread.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable

log = logging.getLogger("mfruitos.tasks")


class TaskRunner:
    def __init__(self, post: Callable[..., None]):
        self._post = post
        self._queues: dict[str, queue.Queue] = {}
        self._threads: list[threading.Thread] = []
        self.active: dict[str, str] = {}

    def start(self, lanes=("quick", "jobs")) -> None:
        for lane in lanes:
            q: queue.Queue = queue.Queue()
            self._queues[lane] = q
            thread = threading.Thread(target=self._worker, args=(lane, q), name=f"task-{lane}",
                                      daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        for q in self._queues.values():
            q.put(None)

    def busy(self, lane: str = "jobs") -> bool:
        return lane in self.active

    def submit(self, name: str, fn: Callable[[], Any], on_done: Callable[[Any], None] | None,
               on_error: Callable[[BaseException], None] | None, lane: str = "quick") -> None:
        q = self._queues.get(lane)
        if q is None:  # not started (tests / self-test): run inline
            self._run(lane, name, fn, on_done, on_error)
            return
        q.put((name, fn, on_done, on_error))

    def _worker(self, lane: str, q: queue.Queue) -> None:
        while True:
            item = q.get()
            if item is None:
                return
            self._run(lane, *item)

    def _run(self, lane, name, fn, on_done, on_error) -> None:
        self.active[lane] = name
        try:
            result = fn()
        except Exception as exc:  # reported to the UI via on_error, never crashes the worker
            log.warning("Task %s failed: %s", name, exc, exc_info=log.isEnabledFor(logging.DEBUG))
            if on_error is not None:
                self._post(on_error, exc)
            else:
                self._post(_log_unhandled, name, exc)
        else:
            if on_done is not None:
                self._post(on_done, result)
        finally:
            self.active.pop(lane, None)


def _log_unhandled(name: str, exc: BaseException) -> None:
    log.error("Task %s failed with no error handler: %s", name, exc)
