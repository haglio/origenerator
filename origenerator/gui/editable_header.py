from PyQt6.QtWidgets import QWidget, QStackedLayout, QLabel, QLineEdit
from PyQt6.QtCore import Qt, pyqtSignal


class _RenameEdit(QLineEdit):
    cancelled = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
        else:
            super().keyPressEvent(event)


class EditableHeader(QWidget):
    """A bold title that swaps to an inline editor on double-click.

    Shows arbitrary display text (e.g. a breadcrumb) but edits a separate value
    supplied by the caller, so the visible path and the editable folder name can
    differ. Emits ``edit_requested`` on double-click and ``edited`` on commit;
    Escape cancels without emitting.
    """

    edit_requested = pyqtSignal()
    edited = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)

        self._label = QLabel("")
        self._label.setWordWrap(True)
        self._label.setStyleSheet("font-size: 15px; font-weight: 600; padding: 2px;")
        self._stack.addWidget(self._label)

        self._edit = _RenameEdit()
        self._edit.editingFinished.connect(self._on_editing_finished)
        self._edit.cancelled.connect(self._cancel)
        self._stack.addWidget(self._edit)

    def set_display(self, text: str):
        self._label.setText(text)

    def display_text(self) -> str:
        return self._label.text()

    def begin_edit(self, value: str):
        self._edit.setText(value)
        self._stack.setCurrentWidget(self._edit)
        self._edit.setFocus()
        self._edit.selectAll()

    def _editing(self) -> bool:
        return self._stack.currentWidget() is self._edit

    def _on_editing_finished(self):
        if not self._editing():
            return  # already returned to the label (e.g. via cancel)
        value = self._edit.text()
        self._stack.setCurrentWidget(self._label)
        self.edited.emit(value)

    def _cancel(self):
        self._stack.setCurrentWidget(self._label)

    def mouseDoubleClickEvent(self, event):
        if not self._editing():
            self.edit_requested.emit()
        super().mouseDoubleClickEvent(event)
