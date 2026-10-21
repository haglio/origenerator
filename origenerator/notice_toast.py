"""A run's notice as the notification Windows raises for it, from the open app
and from the process that waits out a run the app was closed on alike."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from origenerator import app_link
from origenerator.run_notice import Notice
from origenerator.windows_toast import show, take_back, toast_xml

logger = logging.getLogger(__name__)

_FILED_WITH = "runs"


def raise_notice(identity: str, notice: Notice, *, mark: Path | None = None) -> None:
    try:
        link = app_link.link_to(notice.generation) if notice.generation else None
        show(identity, toast_xml(notice.title, notice.body, link=link, mark=mark),
             tag=_tag_of(notice.generation), group=_FILED_WITH)
    except OSError as e:
        logger.warning("Windows would not raise the notification: %s", e)


def take_back_notice(identity: str, generation: str) -> None:
    try:
        take_back(identity, tag=_tag_of(generation), group=_FILED_WITH)
    except OSError as e:
        logger.warning("Windows would not take the notification back: %s", e)


def _tag_of(generation: str) -> str:
    return hashlib.sha1(generation.encode("utf-8")).hexdigest()
