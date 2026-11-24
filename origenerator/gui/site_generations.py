from __future__ import annotations

import logging
from collections.abc import Callable

from app_support import haglio_settings
from app_support.site_pages import fill_script
from PySide6.QtCore import QObject, Signal

from origenerator import config, site_items, sites
from origenerator.display_names import shown_name
from origenerator.gui.off_thread import run_off_thread
from origenerator.output_places import OutputFolders
from origenerator.site_chrome import SiteChrome, chrome_here
from origenerator.site_download import downloaded
from origenerator.site_generation import (
    CHROME_FAILED,
    NEVER_ANSWERED,
    WINDOW_CLOSED,
    Made,
    Site,
    SiteRefused,
)

logger = logging.getLogger(__name__)

NOT_DOWNLOADED = "not downloaded"
NOT_SET_UP = "not set up"

_WHY = {
    NEVER_ANSWERED: "the site never answered",
    WINDOW_CLOSED: "its window was closed before anyone signed in",
    CHROME_FAILED: "Chrome did not start, or stopped answering",
    NOT_DOWNLOADED: "the image it made could not be downloaded",
    NOT_SET_UP: "Chrome or Fun Time's script for the site's page is missing on this computer",
}


def why_in_words(site: str, reason: str) -> str:
    name = shown_name(site)
    if reason in _WHY:
        return f"{name} did not make the image: {_WHY[reason]}."
    return f"{name} did not make the image. {name} said: {reason}"


class _NothingToMakeItWith:
    def make(self, _address: str) -> Made:
        raise SiteRefused(NOT_SET_UP)

    def close(self) -> None:
        pass


def the_site_here():
    chrome = chrome_here()
    script = fill_script([root / "fun_time" for root in haglio_settings.project_roots()])
    if chrome is None or script is None:
        return _NothingToMakeItWith()
    return Site(SiteChrome(config.LIBRARY_STATE_DIR / "site_chrome", chrome),
                lambda: script.read_text(encoding="utf-8"))


def _off_the_window_thread(work, done, *, owner) -> None:
    run_off_thread(work, done, owner=owner, waits_long=True)


class SiteGenerations(QObject):
    finished = Signal(str, str, str)
    failed = Signal(str, str)

    def __init__(self, db, folders: OutputFolders, parent=None, *,
                 site: Callable = the_site_here, download: Callable[[str], bytes] = downloaded,
                 run_off: Callable = _off_the_window_thread):
        super().__init__(parent)
        self._db, self._folders = db, folders
        self._site_here, self._download, self._run_off = site, download, run_off
        self._site = None
        self._waiting: list[tuple[str, str, str, dict]] = []
        self._making: str | None = None

    def start_batch(self, key: str, workflow, batch: list[dict]) -> list[str]:
        started = [site_items.begin(self._db, workflow.name, params) for params in batch]
        self._waiting.extend((key, prompt_id, workflow.source, params)
                             for prompt_id, params in zip(started, batch, strict=True))
        self._make_the_next()
        return started

    def making(self) -> set[str]:
        waiting = {prompt_id for _key, prompt_id, _site, _params in self._waiting}
        return waiting | ({self._making} if self._making else set())

    def close(self) -> None:
        self._waiting.clear()
        if self._site is not None:
            self._site.close()

    def _make_the_next(self) -> None:
        if self._making or not self._waiting:
            return
        key, prompt_id, site, params = self._waiting.pop(0)
        self._making = prompt_id
        if self._site is None:
            self._site = self._site_here()
        self._run_off(lambda: self._made_by(site, params),
                      lambda made: self._ended(key, prompt_id, site, made), owner=self)

    def _made_by(self, site: str, params: dict):
        try:
            made = self._site.make(sites.address_asking_for_an_image(site, params))
            image = self._download(made.image)
            site_items.kind_of(image)
            return made, image
        except SiteRefused as refused:
            return refused
        except OSError as failed:
            logger.warning("An image a site made could not be downloaded or read: %r", failed)
            return SiteRefused(NOT_DOWNLOADED)
        finally:
            if not self._waiting:
                self._site.close()

    def _ended(self, key: str, prompt_id: str, site: str, made) -> None:
        self._making = None
        if isinstance(made, SiteRefused):
            site_items.give_up(self._db, prompt_id, made.reason)
            self.failed.emit(key, why_in_words(site, made.reason))
        elif site_items.take_in(self._db, prompt_id, *made, self._folders):
            self.finished.emit(key, prompt_id, prompt_id)
        self._make_the_next()
