from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass

from app_support.threading_utils import wait_until

from origenerator.site_chrome import ChromeRefused

logger = logging.getLogger(__name__)

SIGNED_OUT = "signed out"
NEVER_ANSWERED = "never answered"
WINDOW_CLOSED = "window closed"
CHROME_FAILED = "chrome failed"

LOADS_WITHIN_S = 60.0
ANSWERS_WITHIN_S = 240.0
LOOKS_FOR_A_SIGN_IN_EVERY_S = 1.0

_NOWHERE = "about:blank"
_IS_NOWHERE = f"location.href === '{_NOWHERE}' && document.readyState === 'complete'"
_HAS_LOADED = "document.readyState === 'complete'"
_WHAT_IT_MADE = "JSON.stringify(window.funTimeMade || null)"
_IS_SIGNED_OUT = "window.funTimeSite ? window.funTimeSite.signedOut() : null"


@dataclass(frozen=True)
class Made:
    image: str
    seed: str = ""


class SiteRefused(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def made_on(page, address: str, script: str, *, until: Callable = wait_until) -> Made:
    try:
        page.go_to(_NOWHERE)
        until(lambda: page.read(_IS_NOWHERE), timeout=LOADS_WITHIN_S)
        page.go_to(address)
        until(lambda: page.read(_HAS_LOADED), timeout=LOADS_WITHIN_S)
        page.run(script)
        said: list[dict] = []
        until(lambda: _has_answered(page, said), timeout=ANSWERS_WITHIN_S)
    except TimeoutError as late:
        raise SiteRefused(NEVER_ANSWERED) from late
    except (ChromeRefused, OSError) as failed:
        logger.warning("The Chrome for sites failed while a site made an image: %r", failed)
        raise SiteRefused(CHROME_FAILED) from failed
    answer = said[0]
    if not answer.get("image"):
        raise SiteRefused(str(answer.get("refused") or NEVER_ANSWERED))
    return Made(image=str(answer["image"]), seed=str(answer.get("seed") or ""))


def _has_answered(page, said: list[dict]) -> bool:
    answer = json.loads(page.read(_WHAT_IT_MADE) or "null")
    if answer is not None:
        said.append(answer)
    return answer is not None


class Site:
    def __init__(self, chrome, script: Callable[[], str], *, until: Callable = wait_until):
        self._chrome, self._script, self._until = chrome, script, until
        self._page = None

    def make(self, address: str) -> Made:
        try:
            return self._made_unseen(address)
        except SiteRefused as refused:
            if refused.reason != SIGNED_OUT:
                raise
        self._wait_for_a_sign_in(address.split("#", 1)[0])
        return self._made_unseen(address)

    def close(self) -> None:
        self._page = None
        self._chrome.close()

    def _made_unseen(self, address: str) -> Made:
        try:
            if self._page is None:
                self._page = self._chrome.open()
            return made_on(self._page, address, self._script(), until=self._until)
        except (ChromeRefused, OSError, TimeoutError) as failed:
            logger.warning("The Chrome for sites did not start: %r", failed)
            self.close()
            raise SiteRefused(CHROME_FAILED) from failed
        except SiteRefused as refused:
            if refused.reason == CHROME_FAILED:
                self.close()
            raise

    def _wait_for_a_sign_in(self, address: str) -> None:
        self.close()
        try:
            page = self._chrome.open(address, seen=True)
            self._until(lambda: self._has_signed_in(page), interval=LOOKS_FOR_A_SIGN_IN_EVERY_S)
        except (ChromeRefused, OSError, TimeoutError) as failed:
            raise SiteRefused(CHROME_FAILED) from failed
        finally:
            self.close()

    def _has_signed_in(self, page) -> bool:
        try:
            signed_out = page.read(_IS_SIGNED_OUT)
            if signed_out is None:
                page.run(self._script())
            return signed_out is False
        except Exception:
            if not self._chrome.is_open():
                raise SiteRefused(WINDOW_CLOSED) from None
            return False
