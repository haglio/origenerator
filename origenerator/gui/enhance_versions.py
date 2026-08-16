"""Every version of one image, as a strip of thumbnails that swap the preview.

An enhancement is a layer, not a replacement: the enhanced file leads the row's
``output_files`` and each earlier one stays listed, so an image can carry several
levels at once — usually one, more when the same image is enhanced again at
different settings to compare them. The preview opens on the most-enhanced
version; this is where the rest are, sitting at the bottom of the info pane
beside the other cross-links (a video's source image, an image's animations),
each tile captioned with the settings that made it.

A tile can also be dragged onto the Enhance subpanel, which absorbs the settings
it carries — the way to say "do that again" about a version you liked without
reading its numbers off and typing them back in.

An enhancement still cooking takes the ``+ Enhance`` card's own slot at the head
of the strip, mirroring the run's streamed frames the way the in-flight cards do
everywhere else — the card becomes the thing it asked for, and the level being
made appears where the level will be.

The strip is up for every image, even one with nothing but its original: it is
where an image's versions live, and a place that appears only once you already
have versions is a place you never find. It also closes with a ``+ Enhance``
card that makes another at the current settings — dimmed when the image already
holds one made at exactly those, and hovering the dimmed card lights the level
it would have duplicated.
"""

import json

from PyQt6.QtWidgets import (
    QApplication, QGraphicsOpacityEffect, QLabel, QVBoxLayout, QWidget,
)
from PyQt6.QtGui import QDrag, QPixmap
from PyQt6.QtCore import QByteArray, QMimeData, Qt, pyqtSignal

from origenerator.gui.flow_layout import FlowLayout

# A dragged enhancement level carries the params that produced it under this
# type; the Enhance subpanel reads it to absorb those settings.
ENHANCE_LEVEL_MIME = "application/x-origenerator-enhance-level"

_TILE = 108  # the thumbnail box; a caption of settings sits under it
# The in-flight edge the Recents shelf's cards wear, so work in progress reads
# the same wherever it shows.
_PENDING_BORDER = "2px solid #3080e0"
# The dashed box of an empty slot waiting to be filled, and the lit edge a level
# wears while the card that would duplicate it is hovered.
_ADD_BORDER = "1px dashed #808080"
_MATCH_BORDER = "2px solid #30a030"


def enhance_level_mime(params: dict) -> QMimeData:
    """The drag payload carrying one level's enhancement settings."""
    mime = QMimeData()
    mime.setData(ENHANCE_LEVEL_MIME,
                 QByteArray(json.dumps(params).encode("utf-8")))
    return mime


def params_from_mime(mime) -> dict | None:
    """The settings a dragged level carries, or ``None`` for any other drag."""
    if not mime.hasFormat(ENHANCE_LEVEL_MIME):
        return None
    try:
        params = json.loads(bytes(mime.data(ENHANCE_LEVEL_MIME)).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return params if isinstance(params, dict) else None


class _LevelTile(QWidget):
    """One version: its picture, its label, and the settings that made it.

    Clicking puts it in the preview; dragging it carries those settings for the
    Enhance subpanel to absorb.
    """

    clicked = pyqtSignal(int)

    def __init__(self, level, position: int, image_path, parent=None):
        super().__init__(parent)
        self._position = position
        self._params = dict(level.params)
        self._press_pos = None
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        picture = QLabel()
        self._picture = picture  # the image the drag carries under the cursor
        picture.setFixedSize(_TILE, _TILE)
        picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(str(image_path)) if image_path else QPixmap()
        if not pixmap.isNull():
            picture.setPixmap(pixmap.scaled(
                _TILE, _TILE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        else:
            # The file is gone (trashed, or moved out from under us). The level
            # still lists — its caption says which one it was — so the box shows
            # the em dash the rest of the app uses for "nothing to show here".
            picture.setText("—")
            picture.setToolTip("This version's file is no longer on disk")
        box.addWidget(picture)
        caption = QLabel(level.label)
        caption.setStyleSheet("font-weight: 600;")
        box.addWidget(caption)
        if level.settings:
            detail = QLabel(level.settings.replace(" · ", "\n"))
            detail.setObjectName("estimateLabel")
            box.addWidget(detail)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(
            f"{level.settings}\nDrag onto Enhance to reuse these settings"
            if level.params else level.label
        )

    def set_highlighted(self, on: bool) -> None:
        """Light this level's picture — what the ``+ Enhance`` card points at
        when it is dimmed because this is the version it would duplicate."""
        self._picture.setStyleSheet(
            f"border: {_MATCH_BORDER}; border-radius: 3px;" if on else ""
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()

    def mouseMoveEvent(self, event):
        # Only a level that knows its settings is worth dragging: the original
        # was made by no enhancement, so there is nothing for the panel to take.
        if self._press_pos is None or not self._params:
            return
        moved = (event.position().toPoint() - self._press_pos).manhattanLength()
        if moved < QApplication.startDragDistance():
            return  # still a click, not yet a drag — a thumbnail's own threshold
        self._press_pos = None
        drag = QDrag(self)
        drag.setMimeData(enhance_level_mime(self._params))
        pixmap = self._picture.pixmap()
        if pixmap is not None and not pixmap.isNull():
            drag.setPixmap(pixmap)  # the version's image trails the cursor
        drag.exec(Qt.DropAction.CopyAction)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._press_pos is not None:
            self._press_pos = None
            self.clicked.emit(self._position)


class _PendingTile(QWidget):
    """The enhancement being made right now: its live frame, or the stage it's at.

    Wears the same blue "in progress" edge as the Recents shelf's in-flight
    cards, so a level under construction reads the same here as work in flight
    reads anywhere else in the app.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        self._picture = QLabel()
        self._picture.setFixedSize(_TILE, _TILE)
        self._picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._picture.setWordWrap(True)
        self._picture.setStyleSheet(
            f"background-color: transparent; border: {_PENDING_BORDER};"
            " border-radius: 3px;"
        )
        box.addWidget(self._picture)
        self._caption = QLabel("Enhancing")
        self._caption.setStyleSheet("font-weight: 600;")
        box.addWidget(self._caption)
        # The settings under the caption, exactly where a finished level carries
        # its own: what is being made is as much a question of "at what" as the
        # levels already there, and it is the only place to read it back before
        # the run lands.
        self._detail = QLabel()
        self._detail.setObjectName("estimateLabel")
        box.addWidget(self._detail)
        self.setToolTip("An enhancement of this image is being generated")

    def update_pending(self, status: str, frame: bytes | None, settings: str = ""):
        pixmap = QPixmap()
        if frame and pixmap.loadFromData(frame) and not pixmap.isNull():
            self._picture.setPixmap(pixmap.scaled(
                _TILE, _TILE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        else:
            self._picture.setText(
                "Generating…" if status == "running" else "Queued…"
            )
        self._detail.setText(settings.replace(" · ", "\n"))
        self._detail.setVisible(bool(settings))
        self.setToolTip(
            f"An enhancement of this image is being generated at {settings}"
            if settings else "An enhancement of this image is being generated"
        )


class _AddTile(QWidget):
    """The ``+ Enhance`` slot that closes the strip.

    Live, it makes another version at whatever the Enhance panel currently says.
    Dimmed, the image already holds one made at exactly those settings, and
    hovering it lights that level rather than leaving you to compare numbers —
    the answer to "why can't I press this" is the tile it points at.
    """

    clicked = pyqtSignal()
    hovered = pyqtSignal(bool)

    def __init__(self, settings: str, duplicate_of: int | None, parent=None):
        super().__init__(parent)
        self._enabled = duplicate_of is None
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        self._picture = QLabel("+")
        self._picture.setFixedSize(_TILE, _TILE)
        self._picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._picture.setStyleSheet(
            f"border: {_ADD_BORDER}; border-radius: 3px; font-size: 28px;"
        )
        box.addWidget(self._picture)
        caption = QLabel("Enhance")
        caption.setStyleSheet("font-weight: 600;")
        box.addWidget(caption)
        if settings:
            detail = QLabel(settings.replace(" · ", "\n"))
            detail.setObjectName("estimateLabel")
            box.addWidget(detail)
        # Dimmed by opacity rather than by setEnabled: Qt delivers no mouse
        # events to a disabled widget, and the hover is exactly what the dimmed
        # state is for — it is how the card explains why it cannot be pressed.
        if not self._enabled:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(0.4)
            self.setGraphicsEffect(effect)
        self.setCursor(Qt.CursorShape.PointingHandCursor if self._enabled
                       else Qt.CursorShape.ForbiddenCursor)
        self.setToolTip(
            f"Enhance this image at {settings}" if self._enabled
            else "This image already has a version at exactly these settings"
        )

    def enterEvent(self, event):
        self.hovered.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered.emit(False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._enabled and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class EnhanceVersions(QWidget):
    """The levels of one image, newest first, as a strip of thumbnails.

    ``show_levels`` takes :class:`~origenerator.gallery.enhance.EnhanceLevel`
    objects (as :func:`~origenerator.gallery.enhance.enhance_levels` produces
    them) paired with the on-disk file to draw, plus the ``(status, frame)`` of
    an enhancement still running on this image. Clicking a level's tile emits
    ``level_selected`` with its position in that list, for the panel to put in
    the preview.
    """

    level_selected = pyqtSignal(int)
    enhance_requested = pyqtSignal()   # the "+ Enhance" card was pressed

    def __init__(self, parent=None):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        self._heading = QLabel("Enhancement levels")
        self._heading.setStyleSheet("font-weight: 600;")
        box.addWidget(self._heading)
        self._host = QWidget()
        FlowLayout(self._host, spacing=6)
        box.addWidget(self._host)
        self._box = box
        self._pending: _PendingTile | None = None
        self._tiles: list[_LevelTile] = []
        self.hide()

    def show_levels(self, items: list[tuple], pending: tuple | None = None,
                    add: tuple | None = None):
        """Rebuild the strip from ``(level, image_path)`` pairs.

        ``add`` is ``(settings, duplicate_of)`` for the ``+ Enhance`` card, which
        leads the strip: that is where a new version arrives, since the strip
        runs newest first. ``duplicate_of`` names the level those settings would
        duplicate, or ``None`` when they would make something new.

        ``pending`` is the ``(status, frame, settings)`` of an enhancement still
        running, and it takes that same leading slot — the card *becomes* the
        thing it asked for rather than sitting beside it, which is what the press
        looks like from the other side.

        Hidden only when there is nothing at all to show — no versions, nothing
        running, and no card to press, which is what a video looks like.
        """
        # Replace the host wholesale — the same delete-and-rebuild idiom the
        # related-media strips use, so no tile outlives the row it described.
        self._box.removeWidget(self._host)
        self._host.deleteLater()
        self._host = QWidget()
        flow = FlowLayout(self._host, spacing=6)
        self._pending = None
        self._tiles = []
        # One leading slot, held by whichever of the two applies: the run in
        # flight if there is one, else the card that would start it.
        if pending is not None:
            self._pending = _PendingTile()
            self._pending.update_pending(*pending)
            flow.addWidget(self._pending)
        elif add is not None:
            settings, duplicate_of = add
            card = _AddTile(settings, duplicate_of)
            card.clicked.connect(self.enhance_requested)
            card.hovered.connect(
                lambda on, at=duplicate_of: self._highlight_level(at, on))
            flow.addWidget(card)
        for position, (level, image_path) in enumerate(items):
            tile = _LevelTile(level, position, image_path)
            tile.clicked.connect(self.level_selected)
            self._tiles.append(tile)
            flow.addWidget(tile)
        self._box.addWidget(self._host)
        self.setVisible(bool(items) or pending is not None or add is not None)

    def _highlight_level(self, position: int | None, on: bool) -> None:
        """Light the level the dimmed ``+ Enhance`` card would have duplicated."""
        if position is None or not 0 <= position < len(self._tiles):
            return
        self._tiles[position].set_highlighted(on)

    def update_pending(self, pending: tuple | None) -> bool:
        """Feed a new frame to the tile already standing, without rebuilding.

        A run streams frames several times a second, and rebuilding the strip on
        each would thrash the layout under the cursor mid-drag. Returns whether
        the update landed; ``False`` means the strip's shape has to change (a run
        started or ended) and the caller should rebuild.
        """
        if (self._pending is None) != (pending is None):
            return False
        if pending is not None:
            self._pending.update_pending(*pending)
        return True
