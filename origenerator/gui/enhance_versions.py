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

Hidden entirely for an image with nothing but its original, which is most of
them — the strip appears when there is actually a choice to make.
"""

import json

from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget
from PyQt6.QtGui import QDrag, QPixmap
from PyQt6.QtCore import QByteArray, QMimeData, Qt, pyqtSignal

from origenerator.gui.flow_layout import FlowLayout

# A dragged enhancement level carries the params that produced it under this
# type; the Enhance subpanel reads it to absorb those settings.
ENHANCE_LEVEL_MIME = "application/x-origenerator-enhance-level"

_TILE = 108  # the thumbnail box; a caption of settings sits under it


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

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()

    def mouseMoveEvent(self, event):
        # Only a level that knows its settings is worth dragging: the original
        # was made by no enhancement, so there is nothing for the panel to take.
        if self._press_pos is None or not self._params:
            return
        if (event.position().toPoint() - self._press_pos).manhattanLength() < 10:
            return
        self._press_pos = None
        drag = QDrag(self)
        drag.setMimeData(enhance_level_mime(self._params))
        drag.exec(Qt.DropAction.CopyAction)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._press_pos is not None:
            self._press_pos = None
            self.clicked.emit(self._position)


class EnhanceVersions(QWidget):
    """The levels of one image, newest first, as a strip of thumbnails.

    ``show_levels`` takes :class:`~origenerator.gallery.enhance.EnhanceLevel`
    objects (as :func:`~origenerator.gallery.enhance.enhance_levels` produces
    them) paired with the on-disk file to draw. Clicking a tile emits
    ``level_selected`` with its position in that list, for the panel to put in
    the preview.
    """

    level_selected = pyqtSignal(int)

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
        self.hide()

    def show_levels(self, items: list[tuple]):
        """Rebuild the strip from ``(level, image_path)`` pairs, or hide when the
        image has only its original (nothing to choose between)."""
        # Replace the host wholesale — the same delete-and-rebuild idiom the
        # related-media strips use, so no tile outlives the row it described.
        self._box.removeWidget(self._host)
        self._host.deleteLater()
        self._host = QWidget()
        flow = FlowLayout(self._host, spacing=6)
        for position, (level, image_path) in enumerate(items):
            tile = _LevelTile(level, position, image_path)
            tile.clicked.connect(self.level_selected)
            flow.addWidget(tile)
        self._box.addWidget(self._host)
        self.setVisible(len(items) > 1)
