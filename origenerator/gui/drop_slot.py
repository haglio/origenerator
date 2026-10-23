"""Drop targets for a dragged gallery generation: slots holding what it lends them.

The gallery's combine panel pairs two slots — an image slot and a video slot — with
a zone between them that drops into both. A slot holds whatever its ``lent_by``
says a dropped generation lends it and turns away one that lends it nothing; it
previews what it holds — a video loops its clip, an image shows its still — and
wears a corner badge of its own kind so it's clear which item belongs where. It
knows only prompt_ids; the view supplies ``lent_by`` and the preview.

A slot whose item is held only for its settings is built ``grayscale``, and draws
whatever lands in it drained of color (:mod:`origenerator.gui.grayscale`) — the
video slot's whole purpose being the recipe rather than the clip.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMovie, QPixmap
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget
from shared_ui.colors import TEXT_PRIMARY
from shared_ui.icons import glyph_pixmap

from origenerator.gui.drags import under_way
from origenerator.gui.drop_style import AIMED, LIT, light
from origenerator.gui.generation_drag import dragged_generation
from origenerator.gui.grayscale import grayscale_pixmap, play_grayscale
from origenerator.gui.looping_preview import looping_movie
from origenerator.gui.media_badge import MediaBadge
from origenerator.gui.thumbnail_box import THUMBNAIL_BOX, fitted_in_the_box


class DropZone(QWidget):
    """Where a dragged generation can be let go: into every slot this zone reaches
    that is showing and is lent something by it, each lit while the drag is here."""

    def __init__(self, slots=(), parent=None):
        super().__init__(parent)
        self._slots = tuple(slots)
        self.setAcceptDrops(True)

    def reaches(self) -> tuple[DropSlot, ...]:
        return tuple(slot for slot in self._slots if not slot.isHidden())

    def _landing(self, mime) -> dict[DropSlot, str]:
        dropped = dragged_generation(mime)
        if dropped is None:
            return {}
        lent = {slot: slot.lent_by(dropped) for slot in self.reaches()}
        return {slot: held for slot, held in lent.items() if held is not None}

    def _aim(self, event):
        landing = self._landing(event.mimeData())
        for slot in self.reaches():
            slot.set_targeted(slot in landing)
        if landing:
            event.acceptProposedAction()
        else:
            event.ignore()

    def _put_out(self):
        for slot in self.reaches():
            slot.set_targeted(False)

    def dragEnterEvent(self, event):
        self._aim(event)

    def dragMoveEvent(self, event):
        self._aim(event)

    def dragLeaveEvent(self, event):
        self._put_out()

    def dropEvent(self, event):
        self._put_out()
        landing = self._landing(event.mimeData())
        for slot, held in landing.items():
            slot.set_item(held)
        if landing:
            event.acceptProposedAction()
        else:
            event.ignore()


class DropSlot(DropZone):
    """A labeled drop zone that holds one accepted generation's prompt_id."""

    changed = pyqtSignal()  # the held item changed (dropped or cleared)
    activated = pyqtSignal(str)  # the held item was clicked: go to it

    def __init__(
        self,
        kind: str,
        lent_by: Callable[[str], str | None],
        preview: Callable[[str], tuple[str | None, str | None]],
        placeholder: str,
        parent=None,
        grayscale: bool = False,
    ):
        super().__init__(parent=parent)
        self._lent_by = lent_by
        self._preview = preview    # (prompt_id) -> (thumb_path, movie_path)
        self._placeholder = placeholder
        self._go_to_tip = f"Click to go to this {kind}"
        # Whether what lands here is held for its settings rather than shown as a
        # result — drawn gray if so, however it previews.
        self._grayscale = grayscale
        self._current_id: str | None = None
        self._movie: QMovie | None = None
        self.setMinimumWidth(0)  # shrink with the TOC pane rather than widen it

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # Style the child label, not the bare QWidget: a plain QWidget subclass
        # paints no stylesheet border without WA_StyledBackground.
        self._label = QLabel(placeholder)
        self._label.setObjectName("dropSlot")
        self._label.setProperty(LIT, False)
        self._label.setProperty(AIMED, False)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)
        self._label.setMinimumHeight(THUMBNAIL_BOX.height())
        layout.addWidget(self._label)
        # A corner chip naming this slot's kind, shown only once something's dropped.
        self._badge = MediaBadge(kind, self)
        self._render()
        under_way.started.connect(self._light_for)
        under_way.ended.connect(self._put_out_for_the_drag)

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
            self.unsetCursor()
            return
        thumb_path, movie_path = self._preview(self._current_id)
        if movie_path and Path(movie_path).exists():
            self._label.setText("")
            self._movie = looping_movie(movie_path, THUMBNAIL_BOX, self._label)
            if self._grayscale:
                play_grayscale(self._movie, self._label)  # still loops, just drained
            else:
                self._label.setMovie(self._movie)
        elif thumb_path and Path(thumb_path).exists() and not QPixmap(str(thumb_path)).isNull():
            self._label.setText("")
            picture = fitted_in_the_box(QPixmap(str(thumb_path)))
            self._label.setPixmap(grayscale_pixmap(picture) if self._grayscale else picture)
        else:
            self._label.setText("")  # held, but no thumbnail to show
            self._label.setPixmap(glyph_pixmap("check", 2 * self._label.fontMetrics().height(),
                                               TEXT_PRIMARY))
        self._badge.setVisible(True)
        self._badge.raise_()  # keep the kind chip above the preview
        self.setToolTip(self._go_to_tip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # --- drag & drop ------------------------------------------------------

    def reaches(self) -> tuple[DropSlot, ...]:
        return (self,)

    def lent_by(self, prompt_id: str) -> str | None:
        return self._lent_by(prompt_id)

    def accepts(self, prompt_id: str) -> bool:
        return self.lent_by(prompt_id) is not None

    def _light_for(self, mime, _source):
        light(self._label, LIT, bool(self._landing(mime)))

    def _put_out_for_the_drag(self):
        light(self._label, LIT, False)

    def set_targeted(self, targeted: bool):
        light(self._label, AIMED, targeted)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._current_id is not None:
            self.activated.emit(self._current_id)
