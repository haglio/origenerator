"""What a tab is asked to change about the image it shows, in a few words.

Typed, or the words a spoken request was heard saying. A pause in the typing
asks for the prompts to be rewritten to match, and "updating…" stands beside
the words until they have been.
"""
from __future__ import annotations

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QWidget

_ASK = "What to change, e.g. two women"
_NOTHING_TO_ASK_OF = "Pick an image to ask a change of"
_UPDATING = "updating…"
_FAILED = "couldn't work that into the prompts"


class RequestField(QWidget):
    asked = pyqtSignal(str)

    PAUSE_MS = 600

    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self._words = QLineEdit()
        self._words.setPlaceholderText(_ASK)
        self._status = QLabel()
        self._status.hide()
        row.addWidget(self._words, 1)
        row.addWidget(self._status)
        self._pause = QTimer(self)
        self._pause.setSingleShot(True)
        self._pause.setInterval(self.PAUSE_MS)
        self._pause.timeout.connect(lambda: self.asked.emit(self.words()))
        self._words.textEdited.connect(self._typed)

    def _typed(self, _words: str) -> None:
        self._status.setText(_UPDATING)
        self._status.show()
        self._pause.start()

    def words(self) -> str:
        return self._words.text().strip()

    def show_words(self, words: str) -> None:
        self._pause.stop()
        self._words.setText(words)
        self._status.hide()

    def done(self) -> None:
        if not self._pause.isActive():
            self._status.hide()

    def failed(self) -> None:
        self._status.setText(_FAILED)
        self._status.show()

    def set_available(self, available: bool) -> None:
        if not available:
            self.show_words("")
        self._words.setEnabled(available)
        self._words.setPlaceholderText(_ASK if available else _NOTHING_TO_ASK_OF)
