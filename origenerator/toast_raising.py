"""A run's toast as Windows raises it, from the open app
and from the process that waits out a run the app was closed on alike."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from origenerator import app_link
from origenerator.run_toast import Toast
from origenerator.windows_toast import show, take_back, toast_xml

logger = logging.getLogger(__name__)

_FILED_WITH = "runs"


def raise_toast(identity: str, toast: Toast, *, mark: Path | None = None) -> None:
    try:
        link = app_link.link_to(toast.generation) if toast.generation else None
        show(identity, toast_xml(toast.title, toast.body, link=link, mark=mark),
             tag=_tag_of(toast.generation), group=_FILED_WITH)
    except OSError as e:
        logger.warning("Windows would not raise the toast: %s", e)


def take_back_toast(identity: str, generation: str) -> None:
    try:
        take_back(identity, tag=_tag_of(generation), group=_FILED_WITH)
    except OSError as e:
        logger.warning("Windows would not take the toast back: %s", e)


def _tag_of(generation: str) -> str:
    return hashlib.sha1(generation.encode("utf-8")).hexdigest()
