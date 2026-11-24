from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable

from app_support.threading_utils import wait_until

NOT_THERE_YET = 404
APPEARS_WITHIN_S = 90.0
LOOKS_EVERY_S = 2.0
ANSWERS_WITHIN_S = 60


def _fetched(address: str) -> bytes:
    asked = urllib.request.Request(address, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(asked, timeout=ANSWERS_WITHIN_S) as answered:
        return answered.read()


def downloaded(address: str, *, fetch: Callable[[str], bytes] = _fetched,
               until: Callable = wait_until) -> bytes:
    got: list[bytes] = []

    def is_there() -> bool:
        try:
            got.append(fetch(address))
        except urllib.error.HTTPError as refused:
            if refused.code != NOT_THERE_YET:
                raise
            return False
        return True

    until(is_there, timeout=APPEARS_WITHIN_S, interval=LOOKS_EVERY_S)
    return got[0]
