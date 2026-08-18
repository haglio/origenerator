from PyQt6.QtWidgets import QWidget, QStackedLayout, QLabel, QLineEdit
from PyQt6.QtCore import Qt, pyqtSignal


class _RenameEdit(QLineEdit):
    cancelled = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
        else:
            super().keyPressEvent(event)


# The editor is sized to the name it holds, not to the header it sits in: what
# is being edited is one folder's name, and a box the size of a wrapped
# six-level path reads as though the whole path were up for editing.
_EDIT_SLACK = 40   # room past the current name, so there is somewhere to type
_EDIT_MIN_WIDTH = 120


class EditableHeader(QWidget):
    """A bold title that swaps to an inline editor on double-click.

    Shows arbitrary display text (e.g. a breadcrumb) but edits a separate value
    supplied by the caller, so the visible path and the editable folder name can
    differ — the display can run to several wrapped lines while the editor is one
    short line at the head of them. Emits ``edit_requested`` on double-click and
    ``edited`` on commit; Escape cancels without emitting.
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
        """Open the editor on ``value`` — a box the width of that name, one line
        tall, wherever the display text starts."""
        self._edit.setText(value)
        wanted = self._edit.fontMetrics().horizontalAdvance(value) + _EDIT_SLACK
        ceiling = self.width() or wanted
        self._edit.setFixedSize(
            min(max(wanted, _EDIT_MIN_WIDTH), ceiling),
            self._edit.sizeHint().height(),
        )
        self._stack.setCurrentWidget(self._edit)
        self._edit.setFocus()
        self._edit.selectAll()

    def heightForWidth(self, width: int) -> int:
        """One line while editing, the wrapped display text otherwise.

        Without this the header keeps the height of the whole wrapped path while
        the editor is open, leaving the small box adrift in a block of blank
        space the path used to fill.
        """
        if self._editing():
            return self._edit.height()
        return self._label.heightForWidth(width)

    def sizeHint(self):
        return self._edit.sizeHint() if self._editing() else self._label.sizeHint()

    def minimumSizeHint(self):
        return (self._edit.minimumSizeHint() if self._editing()
                else self._label.minimumSizeHint())

    def _editing(self) -> bool:
        return self._stack.currentWidget() is self._edit

    def _on_editing_finished(self):
        if not self._editing():
            return  # already returned to the label (e.g. via cancel)
        value = self._edit.text()
        self._stack.setCurrentWidget(self._label)
        self.updateGeometry()  # back to the height the wrapped path needs
        self.edited.emit(value)

    def _cancel(self):
        self._stack.setCurrentWidget(self._label)
        self.updateGeometry()

    def mouseDoubleClickEvent(self, event):
        if not self._editing():
            self.edit_requested.emit()
        super().mouseDoubleClickEvent(event)
