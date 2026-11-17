from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from origenerator.gui.param_form import ParamForm
from origenerator.one_look import looking_once

WORKFLOWS_KEPT_AHEAD = 3


class FormsAhead(QWidget):
    def __init__(self, parent: QWidget, fresh_form_of: Callable[[str], ParamForm],
                 definitions_of: Callable[[str], list]):
        super().__init__(parent)
        self.hide()
        self._fresh_form_of = fresh_form_of
        self._definitions_of = definitions_of
        self._made: dict[str, tuple[list, ParamForm]] = {}
        self._shown_lately: list[str] = []
        self._when_idle = QTimer(self)
        self._when_idle.setSingleShot(True)
        self._when_idle.setInterval(0)
        self._when_idle.timeout.connect(self._make_one)

    def take(self, key: str) -> ParamForm | None:
        self._note_shown(key)
        self._when_idle.start()
        made_from, made = self._made.pop(key, (None, None))
        if made is not None and made_from != self._definitions_of(key):
            made.deleteLater()
            return None
        return made

    def _note_shown(self, key: str) -> None:
        self._shown_lately = [*(shown for shown in self._shown_lately if shown != key), key]
        for forgotten in self._shown_lately[:-WORKFLOWS_KEPT_AHEAD]:
            if forgotten in self._made:
                self._made.pop(forgotten)[1].deleteLater()
        self._shown_lately = self._shown_lately[-WORKFLOWS_KEPT_AHEAD:]

    @looking_once
    def _make_one(self) -> None:
        owed = [key for key in self._shown_lately[:-1] if key not in self._made]
        if not owed:
            return
        made = self._fresh_form_of(owed[-1])
        made.setParent(self)
        self._made[owed[-1]] = (self._definitions_of(owed[-1]), made)
        if len(owed) > 1:
            self._when_idle.start()
