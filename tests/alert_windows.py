from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import NamedTuple

from PySide6.QtWidgets import QLabel
from shared_ui.alert import AlertDialog, Level
from shared_ui.testing import alert_shown


class Alert(NamedTuple):
    title: str
    message: str
    level: Level


@contextmanager
def alerts_kept() -> Iterator[list[Alert]]:
    kept: list[Alert] = []
    with alert_shown(side_effect=lambda title, message, **how: kept.append(
            Alert(title, message, how["level"]))):
        yield kept


def messages(alerts: list[Alert]) -> list[str]:
    return [alert.message for alert in alerts]


def open_alerts(parent) -> list[AlertDialog]:
    return [dialog for dialog in parent.findChildren(AlertDialog) if dialog.isVisible()]


def message_of(dialog: AlertDialog) -> str:
    (said,) = [label.text() for label in dialog.findChildren(QLabel) if label.wordWrap()]
    return said
