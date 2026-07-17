"""A live fullscreen montage of an auto-generate loop.

Opened by double-clicking the preview while a folder is auto-generating, this
view stays on the item currently being generated — its streamed frames, then its
finished result — in a large centre panel, while the items finished so far
accumulate as thumbnails fanning out to either side (newest nearest the centre).

It is a dumb display driven by the gallery, which feeds it the loop's live frames
and finished items and reacts to its two curation keys:

* Up    — cancel the generation on screen (``cancel_requested``); the loop skips
          to the next one.
* Down  — star the item on screen (``star_requested``); a gold star confirms it.

Escape closes the montage (the loop keeps running); :attr:`closed` fires so the
gallery can forget it.
"""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel
from PyQt6.QtGui import QPalette, QColor, QPixmap
from PyQt6.QtCore import Qt, QSize, pyqtSignal

from origenerator.gui import icons
from origenerator.gui.preview_widget import PreviewWidget

_THUMB = QSize(132, 132)  # a side thumbnail's box
_MAX_PER_SIDE = 8  # visible history per side; older ones fall off the outer edge
_STAR = QSize(72, 72)  # the "starred" confirmation overlaid on the centre


class AutoGenerateView(QWidget):
    closed = pyqtSignal()           # dismissed (Esc / close) — loop keeps running
    cancel_requested = pyqtSignal()  # Up: cancel the generation on screen
    star_requested = pyqtSignal()    # Down: star the item on screen

    def __init__(self, *, player=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Auto-generate")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("black"))
        self.setPalette(palette)

        # left history | centre (the item being generated) | right history
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        left_container, self._left_row = self._side_row()
        right_container, self._right_row = self._side_row()
        # The centre is muted and looping like the inline preview — a rapid montage
        # shouldn't blast the audio of every finished clip — and never opens a
        # nested fullscreen of its own.
        self._preview = PreviewWidget(player=player, allow_fullscreen=False,
                                      mute_audio=True)
        layout.addWidget(left_container, 0)
        layout.addWidget(self._preview, 1)
        layout.addWidget(right_container, 0)

        # Newest finished items alternate sides so the history fans out both ways.
        self._left_thumbs: list[QLabel] = []
        self._right_thumbs: list[QLabel] = []
        self._next_side_right = True

        # A gold star flashed over the centre when the shown item is starred; reset
        # whenever a new item takes the centre.
        self._star = QLabel(self)
        self._star.setPixmap(icons.star_icon(filled=True).pixmap(_STAR))
        self._star.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._star.hide()

    @staticmethod
    def _side_row():
        """A container widget and its horizontal layout for one side's thumbnails.

        Both are returned so the caller keeps the container referenced — a layout
        alone doesn't keep its widget alive, and a dropped container takes the
        layout down with it."""
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(6, 6, 6, 6)
        row.setSpacing(6)
        row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return container, row

    # --- the gallery feeds these as the loop runs --------------------------

    def show_live_frame(self, data: bytes) -> None:
        """Mirror the current generation's streamed frame into the centre."""
        self._preview.show_frame(data)
        self.set_center_starred(False)  # a fresh item on screen isn't starred yet

    def show_center_media(self, path, media_type: str) -> None:
        """Show a finished item's file in the centre (before the next one starts)."""
        self._preview.show_media(path, media_type)
        self.set_center_starred(False)

    def add_thumbnail(self, thumb_path: str) -> None:
        """Add a finished item's thumbnail to the history, newest nearest the centre,
        alternating sides so the strip fans out both ways. Older ones fall off the
        outer edge once a side is full."""
        label = QLabel()
        label.setFixedSize(_THUMB)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(str(thumb_path)) if thumb_path else QPixmap()
        if not pixmap.isNull():
            label.setPixmap(pixmap.scaled(
                _THUMB, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        if self._next_side_right:
            self._push(self._right_row, self._right_thumbs, label, near_center_index=0)
        else:
            self._push(self._left_row, self._left_thumbs, label,
                       near_center_index=self._left_row.count())
        self._next_side_right = not self._next_side_right

    def set_center_starred(self, starred: bool) -> None:
        """Show or hide the gold star confirming the centre item is bookmarked."""
        if starred:
            self._reposition_star()
        self._star.setVisible(starred)

    # --- internals ---------------------------------------------------------

    def _push(self, row: QHBoxLayout, thumbs: list, label: QLabel, *, near_center_index: int):
        """Insert ``label`` nearest the centre on its side, trimming the far end when
        the side is full so the visible history stays bounded."""
        row.insertWidget(near_center_index, label)
        thumbs.append(label)
        if len(thumbs) > _MAX_PER_SIDE:
            oldest = thumbs.pop(0)  # the far (outer) end
            row.removeWidget(oldest)
            oldest.deleteLater()

    def _reposition_star(self) -> None:
        self._star.adjustSize()
        self._star.move((self.width() - self._star.width()) // 2, 24)
        self._star.raise_()

    # --- keys & lifecycle --------------------------------------------------

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close()
        elif key == Qt.Key.Key_Up:
            self.cancel_requested.emit()
        elif key == Qt.Key.Key_Down:
            self.star_requested.emit()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._star.isVisible():
            self._reposition_star()

    def closeEvent(self, event):
        self._preview.clear()  # release any held video file so it can be deleted
        self.closed.emit()
        super().closeEvent(event)
