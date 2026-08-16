"""The find strip: a query box, a match count, and the two steps between hits.

Pops open at the foot of the info pane on Ctrl+F and puts itself away on Esc or
its own ✕. Controls only — it holds no matches and touches no prompt; what it
drives is a :class:`~origenerator.gui.prompt_find.PromptFind`, which the gallery
view wires to it.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QLineEdit, QToolButton, QWidget,
)


class FindBar(QWidget):
    """A browser-style find strip over the front config tab's prompts."""

    query_changed = pyqtSignal(str)
    step_requested = pyqtSignal(int)  # +1 for the next match, -1 for the previous
    dismissed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 4, 0, 0)
        row.setSpacing(6)
        row.addWidget(QLabel("Find in prompts:"))
        self._query = QLineEdit()
        self._query.setPlaceholderText("a word you wrote…")
        self._query.setClearButtonEnabled(True)
        self._query.textChanged.connect(self.query_changed)
        # Enter walks the matches without leaving the keyboard, Shift+Enter backs
        # up — the pairing every find box in every app makes.
        self._query.returnPressed.connect(self._on_return)
        row.addWidget(self._query, 1)
        self._count = QLabel("")
        self._count.setObjectName("estimateLabel")
        row.addWidget(self._count)
        self._prev_btn = self._step_button("▲", "Previous match (Shift+Enter)", -1)
        self._next_btn = self._step_button("▼", "Next match (Enter)", 1)
        row.addWidget(self._prev_btn)
        row.addWidget(self._next_btn)
        self._close_btn = QToolButton()
        self._close_btn.setObjectName("iconButton")
        self._close_btn.setText("✕")
        self._close_btn.setToolTip("Close the find (Esc)")
        self._close_btn.clicked.connect(self.dismissed)
        row.addWidget(self._close_btn)
        self.hide()  # it opens on Ctrl+F, and takes no room until then

    def _step_button(self, text: str, tooltip: str, delta: int) -> QToolButton:
        button = QToolButton()
        button.setObjectName("iconButton")
        button.setText(text)
        button.setToolTip(tooltip)
        button.clicked.connect(
            lambda _checked=False, d=delta: self.step_requested.emit(d)
        )
        button.setEnabled(False)  # nothing to step through until something matches
        return button

    def _on_return(self):
        shift = QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier
        self.step_requested.emit(-1 if shift else 1)

    def open_find(self):
        """Show the strip and take the keyboard, the standing query selected: the
        next keystroke starts a fresh search, and Ctrl+F on an already-open strip
        re-selects rather than doing nothing."""
        self.show()
        self._query.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._query.selectAll()

    def query(self) -> str:
        return self._query.text()

    def show_count(self, position: int, total: int):
        """Say where in the results we are — "3 of 12", or that there are none.

        Blank while nothing has been typed: a count of zero before you have
        searched anything reads as a search that failed.
        """
        if not self._query.text():
            self._count.setText("")
        elif total:
            self._count.setText(f"{position} of {total}")
        else:
            self._count.setText("No matches")
        # One match is already the one you're on, so stepping would land back on
        # it; gray the arrows rather than offer a move that goes nowhere.
        for button in (self._prev_btn, self._next_btn):
            button.setEnabled(total > 1)
