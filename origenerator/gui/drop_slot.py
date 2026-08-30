"""One drop target for a dragged gallery generation, gated by a predicate.

The gallery's combine panel pairs two of these — an image slot and a video slot.
Each accepts only a generation its ``accepts`` predicate allows (the image slot an
image, the video slot a rebuildable i2v video), previews the dropped item — a video
loops its clip, an image shows its still — and wears a corner badge of its own kind
so it's clear which item belongs where. It knows only prompt_ids; the view supplies
the predicate and the preview, so the slot stays free of database knowledge.

A slot whose item is held only for its settings is built ``grayscale``, and draws
whatever lands in it drained of color (:mod:`origenerator.gui.grayscale`) — the
video slot's whole purpose being the recipe rather than the clip.
"""

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtGui import QPixmap, QMovie
from PyQt6.QtCore import Qt, QSize, pyqtSignal

from origenerator.gui.grayscale import grayscale_pixmap, play_grayscale
from origenerator.gui.looping_preview import looping_movie
from origenerator.gui.media_badge import MediaBadge
from origenerator.gui.generation_drag import GENERATION_MIME

_PREVIEW_SIZE = 96  # the dropped thumbnail fits this box; small enough for a 120px pane


class DropSlot(QWidget):
    """A labeled drop zone that holds one accepted generation's prompt_id."""

    changed = pyqtSignal()  # the held item changed (dropped or cleared)

    def __init__(
        self,
        kind: str,
        accepts: Callable[[str], bool],
        preview: Callable[[str], tuple[str | None, str | None]],
        placeholder: str,
        parent=None,
        grayscale: bool = False,
    ):
        super().__init__(parent)
        self._accepts = accepts
        self._preview = preview    # (prompt_id) -> (thumb_path, movie_path)
        self._placeholder = placeholder
        # Whether what lands here is held for its settings rather than shown as a
        # result — drawn gray if so, however it previews.
        self._grayscale = grayscale
        self._current_id: str | None = None
        self._movie: QMovie | None = None
        self.setAcceptDrops(True)
        self.setMinimumWidth(0)  # shrink with the TOC pane rather than widen it

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # Style the child label, not the bare QWidget: a plain QWidget subclass
        # paints no stylesheet border without WA_StyledBackground.
        self._label = QLabel(placeholder)
        self._label.setObjectName("dropSlot")
        self._label.setProperty("dragActive", False)  # lit while a matching drag is underway
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)
        self._label.setMinimumHeight(_PREVIEW_SIZE)
        layout.addWidget(self._label)
        # A corner chip naming this slot's kind, shown only once something's dropped.
        self._badge = MediaBadge(kind, self)
        self._render()

    # --- state ------------------------------------------------------------

    def current_id(self) -> str | None:
        return self._current_id

    def set_item(self, prompt_id: str):
        """Hold ``prompt_id`` and show its preview."""
        self._current_id = prompt_id
        self._render()
        self.changed.emit()

    def set_placeholder(self, text: str):
        """Change the prompt shown while the slot is empty, re-rendering if nothing
        is held (a filled slot keeps its preview until cleared)."""
        self._placeholder = text
        if self._current_id is None:
            self._render()

    def clear(self):
        """Empty the slot back to its placeholder; a no-op when already empty."""
        if self._current_id is None:
            return
        self._current_id = None
        self._render()
        self.changed.emit()

    def _stop_movie(self):
        if self._movie is not None:
            self._movie.stop()
            self._movie.deleteLater()
            self._movie = None

    def _render(self):
        self._stop_movie()
        if self._current_id is None:
            self._label.setPixmap(QPixmap())  # drop any prior preview
            self._label.setText(self._placeholder)
            self._badge.setVisible(False)
            self.setToolTip("")
            return
        thumb_path, movie_path = self._preview(self._current_id)
        if movie_path and Path(movie_path).exists():
            self._label.setText("")
            # A video loops its clip; looping_movie runs it (held, under a
            # session's OmniPause).
            self._movie = looping_movie(movie_path, QSize(_PREVIEW_SIZE, _PREVIEW_SIZE), self._label)
            if self._grayscale:
                play_grayscale(self._movie, self._label)  # still loops, just drained
            else:
                self._label.setMovie(self._movie)
        elif thumb_path and Path(thumb_path).exists() and not QPixmap(str(thumb_path)).isNull():
            self._label.setText("")
            picture = QPixmap(str(thumb_path)).scaled(
                _PREVIEW_SIZE, _PREVIEW_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
            )
            self._label.setPixmap(grayscale_pixmap(picture) if self._grayscale else picture)
        else:
            self._label.setText("✓")  # held, but no thumbnail to show
        self._badge.setVisible(True)
        self._badge.raise_()  # keep the kind chip above the preview
        self.setToolTip("Click to remove")

    # --- drag & drop ------------------------------------------------------

    def _pid_from(self, mime) -> str | None:
        """The dropped generation's id if it carries our type and passes ``accepts``."""
        if not mime.hasFormat(GENERATION_MIME):
            return None
        pid = bytes(mime.data(GENERATION_MIME)).decode("utf-8")
        return pid if self._accepts(pid) else None

    def accepts(self, prompt_id: str) -> bool:
        """Whether this slot would take ``prompt_id`` (its kind gate)."""
        return self._accepts(prompt_id)

    def set_candidate(self, active: bool):
        """Light the slot as a valid target for the in-progress drag (or clear it).

        Driven by the drag's start/end, not by hover, so the drop zone stands out
        the moment a matching drag begins — you see where to aim before arriving.
        """
        if self._label.property("dragActive") == active:
            return
        self._label.setProperty("dragActive", active)
        self._label.style().unpolish(self._label)
        self._label.style().polish(self._label)

    def dragEnterEvent(self, event):
        # Accept so the drop lands (and the OS shows a "can drop" cursor); the
        # highlight is already on from drag-start, so nothing to toggle here.
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
