"""One drop target for a dragged gallery generation, gated by a predicate.

The gallery's combine panel pairs two of these — an image slot and a video slot.
Each accepts only a generation its ``accepts`` predicate allows (the image slot an
image, the video slot a rebuildable i2v video), shows the dropped item's preview,
and reports every change so the panel can enable its Generate button. It knows only
prompt_ids; the view supplies the predicate and the preview, so the slot stays free
of database or workflow knowledge.
"""

from collections.abc import Callable

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, pyqtSignal

from origenerator.gui.thumbnail_widget import GENERATION_MIME

_PREVIEW_SIZE = 96  # the dropped thumbnail fits this box; small enough for a 120px pane


class DropSlot(QWidget):
    """A labeled drop zone that holds one accepted generation's prompt_id."""

    changed = pyqtSignal()  # the held item changed (dropped or cleared)

    def __init__(
        self,
        accepts: Callable[[str], bool],
        preview: Callable[[str], QPixmap | None],
        placeholder: str,
        parent=None,
    ):
        super().__init__(parent)
        self._accepts = accepts
        self._preview = preview
        self._placeholder = placeholder
        self._current_id: str | None = None
        self.setAcceptDrops(True)
        self.setMinimumWidth(0)  # shrink with the TOC pane rather than widen it

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # Style the child label, not the bare QWidget: a plain QWidget subclass
        # paints no stylesheet border without WA_StyledBackground.
        self._label = QLabel(placeholder)
        self._label.setObjectName("dropSlot")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)
        self._label.setMinimumHeight(_PREVIEW_SIZE)
        layout.addWidget(self._label)
        self._render()

    # --- state ------------------------------------------------------------

    def current_id(self) -> str | None:
        return self._current_id

    def set_item(self, prompt_id: str):
        """Hold ``prompt_id`` and show its preview."""
        self._current_id = prompt_id
        self._render()
        self.changed.emit()

    def clear(self):
        """Empty the slot back to its placeholder; a no-op when already empty."""
        if self._current_id is None:
            return
        self._current_id = None
        self._render()
        self.changed.emit()

    def _render(self):
        if self._current_id is None:
            self._label.setPixmap(QPixmap())  # drop any prior preview
            self._label.setText(self._placeholder)
            self.setToolTip("")
            return
        pixmap = self._preview(self._current_id)
        if pixmap is not None and not pixmap.isNull():
            self._label.setText("")
            self._label.setPixmap(pixmap.scaled(
                _PREVIEW_SIZE, _PREVIEW_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
            ))
        else:
            self._label.setText("✓")  # held, but no thumbnail to show
        self.setToolTip("Click to remove")

    # --- drag & drop ------------------------------------------------------

    def _pid_from(self, mime) -> str | None:
        """The dropped generation's id if it carries our type and passes ``accepts``."""
        if not mime.hasFormat(GENERATION_MIME):
            return None
        pid = bytes(mime.data(GENERATION_MIME)).decode("utf-8")
        return pid if self._accepts(pid) else None

    def dragEnterEvent(self, event):
        if self._pid_from(event.mimeData()) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._pid_from(event.mimeData()) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        pid = self._pid_from(event.mimeData())
        if pid is None:
            event.ignore()
            return
        self.set_item(pid)
        event.acceptProposedAction()

    def mousePressEvent(self, event):
        # Clicking a filled slot removes its item (the pair is small; a click is
        # the least fussy way to swap a choice out).
        if event.button() == Qt.MouseButton.LeftButton and self._current_id is not None:
            self.clear()
