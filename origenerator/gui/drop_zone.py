"""Drop targets for a dragged gallery generation: drop zones holding what it lends them.

The gallery's Combine pairs two drop zones — one for an image and one for a
video — with a span between them that drops into both. A drop zone holds whatever its ``lent_by``
says a dropped generation lends it and turns away one that lends it nothing; it
previews what it holds — a video loops, an image shows its still — names
it underneath, and wears an item type icon of its own kind. What it holds means
nothing to it; its owner supplies ``lent_by``, the preview and the name.

A drop zone whose item is held only for its settings is built ``grayscale``, and draws
whatever lands in it drained of color (:mod:`origenerator.gui.grayscale`) — the
video drop zone's whole purpose being the video's settings rather than the video.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMovie, QPixmap
from PyQt6.QtWidgets import QApplication, QLabel, QMenu, QVBoxLayout, QWidget
from shared_ui.colors import TEXT_PRIMARY
from shared_ui.icons import icon_pixmap
from shared_ui.spacing import GAP_SMALL

from origenerator.gui import tile_shape
from origenerator.gui.drags import under_way
from origenerator.gui.drop_style import AIMED, LIT, light
from origenerator.gui.generation_drag import dragged_generation
from origenerator.gui.grayscale import grayscale_pixmap, play_grayscale
from origenerator.gui.item_type_icon import ItemTypeIcon
from origenerator.gui.looping_preview import looping_movie
from origenerator.gui.thumbnail_box import THUMBNAIL_BOX, fitted_in_the_box

DROP_AN_IMAGE = "Drop an image"
DROP_A_VIDEO = "Drop a video"
PASTE_NAME = "Paste Origenerator name"
BROWSE = "Browse..."


def placeholder_for(kind: str) -> str:
    return DROP_A_VIDEO if kind == "video" else DROP_AN_IMAGE


class DropZones(QWidget):
    """Where a dragged generation can be let go: into every drop zone this span
    reaches that is showing and is lent something by it, each lit while the drag is here."""

    def __init__(self, zones=(), parent=None):
        super().__init__(parent)
        self._zones = tuple(zones)
        self.setAcceptDrops(True)

    def reaches(self) -> tuple[DropZone, ...]:
        return tuple(zone for zone in self._zones if not zone.isHidden())

    def _landing(self, mime) -> dict[DropZone, str]:
        dropped = dragged_generation(mime)
        if dropped is None:
            return {}
        lent = {zone: zone.lent_by(dropped) for zone in self.reaches()}
        return {zone: held for zone, held in lent.items() if held is not None}

    def _aim(self, event):
        landing = self._landing(event.mimeData())
        for zone in self.reaches():
            zone.set_targeted(zone in landing)
        if landing:
            event.acceptProposedAction()
        else:
            event.ignore()

    def _put_out(self):
        for zone in self.reaches():
            zone.set_targeted(False)

    def dragEnterEvent(self, event):
        self._aim(event)

    def dragMoveEvent(self, event):
        self._aim(event)

    def dragLeaveEvent(self, event):
        self._put_out()

    def dropEvent(self, event):
        self._put_out()
        landing = self._landing(event.mimeData())
        for zone, held in landing.items():
            zone.set_item(held)
        if landing:
            event.acceptProposedAction()
        else:
            event.ignore()


class DropZone(DropZones):
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
        named: Callable[[str], str | None] = lambda name: None,
        name_of: Callable[[str], str] = lambda held: "",
        browse: Callable[[], None] | None = None,
        leads_to: Callable[[str], str | None] = lambda held: held,
    ):
        super().__init__(parent=parent)
        self._lent_by = lent_by
        self._preview = preview    # (prompt_id) -> (thumb_path, movie_path)
        self._placeholder = placeholder
        self._named = named        # an Origenerator name -> the prompt_id wearing it
        self._name_of = name_of    # what is held -> the name its tooltip says
        self._browse = browse      # picks a file into the drop zone; None where only items go
        self._leads_to = leads_to
        self._go_to_tip = f"Click to go to this {kind}"
        # Whether what lands here is held for its settings rather than shown as a
        # result — drawn gray if so, however it previews.
        self._grayscale = grayscale
        self._current_id: str | None = None
        self._movie: QMovie | None = None
        self.setMinimumWidth(0)  # shrink with the TOC pane rather than widen it

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(GAP_SMALL)
        # Style the child label, not the bare QWidget: a plain QWidget subclass
        # paints no stylesheet border without WA_StyledBackground.
        self._label = QLabel(placeholder)
        self._label.setObjectName("dropZone")
        self._label.setProperty(LIT, False)
        self._label.setProperty(AIMED, False)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)
        self._label.setMinimumHeight(THUMBNAIL_BOX.height())
        layout.addWidget(self._label)
        self._caption = QLabel()
        self._caption.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self._caption.setWordWrap(True)
        tile_shape.style_caption(self._caption)
        layout.addWidget(self._caption)
        # An item type icon naming this drop zone's kind, shown only once something's dropped.
        self._item_type_icon = ItemTypeIcon(kind, self)
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
        """Empty the drop zone back to its placeholder; a no-op when already empty."""
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

    def reread_name(self) -> None:
        held = self._current_id
        named = self._name_of(held) if held is not None else ""
        self._caption.setText(named)
        self._show_where_a_click_goes(held, named)

    def _render(self):
        self._stop_movie()
        self.reread_name()
        if self._current_id is None:
            self._label.setPixmap(QPixmap())  # drop any prior preview
            self._label.setText(self._placeholder)
            self._item_type_icon.setVisible(False)
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
            thumbnail = fitted_in_the_box(QPixmap(str(thumb_path)))
            self._label.setPixmap(grayscale_pixmap(thumbnail) if self._grayscale else thumbnail)
        else:
            self._label.setText("")  # held, but no thumbnail to show
            self._label.setPixmap(icon_pixmap("check", 2 * self._label.fontMetrics().height(),
                                              TEXT_PRIMARY))
        self._item_type_icon.setVisible(True)
        self._item_type_icon.raise_()  # keep the item type icon above the preview

    def _show_where_a_click_goes(self, held: str | None, named: str) -> None:
        leads = held is not None and self._leads_to(held) is not None
        self.setToolTip(named or (self._go_to_tip if leads else ""))
        if leads:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()

    # --- drag & drop ------------------------------------------------------

    def reaches(self) -> tuple[DropZone, ...]:
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
        if event.button() != Qt.MouseButton.LeftButton or self._current_id is None:
            return
        item = self._leads_to(self._current_id)
        if item is not None:
            self.activated.emit(item)

    # --- the right-click menu ---------------------------------------------

    def menu(self) -> QMenu:
        menu = QMenu(self)
        pasted = self._pasted()
        paste = menu.addAction(PASTE_NAME)
        paste.setEnabled(pasted is not None)
        paste.triggered.connect(lambda: self.set_item(pasted))
        if self._browse is not None:
            menu.addAction(BROWSE).triggered.connect(lambda: self._browse())
        return menu

    def _pasted(self) -> str | None:
        name = QApplication.clipboard().text().strip()
        prompt_id = self._named(name) if name else None
        return self.lent_by(prompt_id) if prompt_id else None

    def contextMenuEvent(self, event):
        self.menu().exec(event.globalPos())
