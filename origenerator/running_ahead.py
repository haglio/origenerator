from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager

from funestra.funestra_priority import ahead_on_the_processor


class AheadWhilePlaying:
    def __init__(self, block=ahead_on_the_processor):
        self._block = block
        self._lock = threading.Lock()
        self._playing = 0
        self._raised = ExitStack()

    @contextmanager
    def held(self) -> Iterator[None]:
        with self._lock:
            if self._playing == 0:
                self._raised.enter_context(self._block())
            self._playing += 1
        try:
            yield
        finally:
            with self._lock:
                self._playing -= 1
                if self._playing == 0:
                    self._raised.close()


_THIS_APP = AheadWhilePlaying()


def ahead_while_playing():
    return _THIS_APP.held()
