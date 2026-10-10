from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QLineEdit, QStackedLayout, QWidget

_STILL_IN_THE_FIELD = (Qt.FocusReason.PopupFocusReason,
                       Qt.FocusReason.ActiveWindowFocusReason)


class _PathField(QLineEdit):
    dismissed = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.dismissed.emit()
        else:
            super().keyPressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        if event.reason() not in _STILL_IN_THE_FIELD:
            self.dismissed.emit()


class FolderPathHeader(QWidget):
    edit_requested = pyqtSignal()
    entered = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)

        self._label = QLabel("")
        self._label.setWordWrap(True)
        self._label.setStyleSheet("font-size: 15px; font-weight: 600; padding: 2px;")
        self._stack.addWidget(self._label)

        self._edit = _PathField()
        self._edit.setPlaceholderText("Paste a folder's path")
        self._edit.returnPressed.connect(self._on_entered)
        self._edit.dismissed.connect(self._close_field)
        self._stack.addWidget(self._edit)

    def set_display(self, text: str):
        self._label.setText(text)

    def display_text(self) -> str:
        return self._label.text()

    def begin_edit(self, path: str):
        self._edit.setText(path)
        self._stack.setCurrentWidget(self._edit)
        self._edit.setFocus()
        self._edit.selectAll()

    def heightForWidth(self, width: int) -> int:
        if self._editing():
            return self._edit.sizeHint().height()
        return self._label.heightForWidth(width)

    def sizeHint(self):
        return self._edit.sizeHint() if self._editing() else self._label.sizeHint()

    def minimumSizeHint(self):
        return (self._edit.minimumSizeHint() if self._editing()
                else self._label.minimumSizeHint())

    def _editing(self) -> bool:
        return self._stack.currentWidget() is self._edit

    def _on_entered(self):
        path = self._edit.text()
        self._close_field()
        self.entered.emit(path)

    def _close_field(self):
        self._stack.setCurrentWidget(self._label)

    def mouseDoubleClickEvent(self, event):
        if not self._editing():
            self.edit_requested.emit()
        super().mouseDoubleClickEvent(event)
