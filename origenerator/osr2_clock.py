from __future__ import annotations

import threading
import time


class TickThread:
    def __init__(self, tick, interval_s: float, *, name: str = "osr2-clock",
                 now=time.monotonic, sleep=time.sleep):
        self._tick = tick
        self._interval = interval_s
        self._now = now
        self._sleep = sleep
        self._stopping = threading.Event()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _run(self) -> None:
        due = self._now()
        while not self._stopping.is_set():
            due += self._interval
            now = self._now()
            if due < now - self._interval:
                due = now + self._interval
            delay = due - now
            if delay > 0:
                self._sleep(delay)
            if self._stopping.is_set():
                return
            self._tick()
