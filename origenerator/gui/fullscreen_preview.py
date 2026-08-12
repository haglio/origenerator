"""A fullscreen view of a single image or video, opened by double-clicking a
preview. Escape or another double-click closes it.

Reuses :class:`PreviewWidget` (looping, like the inline preview) for the actual
rendering, over a solid black surround. The media is scaled as large as it fits
the screen without cropping, so a shape that doesn't match the screen letterboxes
on two sides at most — never stranded small with black on all four. Opened by
:meth:`PreviewWidget.open_fullscreen`; the opening preview keeps the reference
alive, mirroring how the gallery holds its slideshow window.

Being the deliberate foreground view, it plays sound (the inline preview stays
muted) and exposes its :meth:`osr2_drive_target`, so the gallery can drive the OSR2
off the video on screen for as long as it's up — regardless of the global toggle.
It signals :attr:`closed` on dismissal so the device is handed back.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtCore import Qt, pyqtSignal

from origenerator.gui.osr2_driver import drive_target_for
from origenerator.gui.preview_widget import PreviewWidget
from origenerator.gui.stroke_hud import StrokeCaption, apply_stroke_key


class FullscreenPreview(QWidget):
    closed = pyqtSignal()  # the view was dismissed (Esc, a double-click, or close)
    media_changed = pyqtSignal()  # paged to a different item (re-aim the OSR2 drive)

    def __init__(self, media: tuple, *, player=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preview")
        # The navigable folder: a lone item until set_playlist arms Left/Right to
        # page across the folder the view was opened from.
        self._items: list[tuple] = [media]
        self._index = 0
        # The gallery hands its app-global stroke driver in via set_stroke once
        # this view announces itself; until then the stroke keys are inert.
        self._stroke = None
        self._stroke_caption: StrokeCaption | None = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAutoFillBackground(True)  # a solid black surround behind the media
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("black"))
        self.setPalette(palette)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # This preview *is* the fullscreen view, so it opts out of opening another —
        # and a double-click on it (the media fills the window) dismisses the view. It
        # plays sound (mute_audio=False), unlike the muted inline preview.
        self._preview = PreviewWidget(player=player, allow_fullscreen=False,
                                      show_funscript_strip=True, mute_audio=False,
                                      on_double_click=self.close)
        layout.addWidget(self._preview, 1)
        self._preview.show_media(media[0], media[1])

    def set_playlist(self, items: list[tuple], index: int) -> None:
        """Arm Left/Right to page across the folder the view was opened from.

        ``items`` is the folder's media in shown order as ``(path, media_type)``;
        ``index`` is the one already on screen. Until this is called the view holds
        a lone item and paging is inert.
        """
        self._items = list(items)
        self._index = index

    def set_stroke(self, stroke) -> None:
        """Wire the shared OSR2 stroke keys and their standing caption in — so
        the device can run over a fullscreen image, which has no script."""
        self._stroke = stroke
        if self._stroke_caption is None and stroke is not None:
            self._stroke_caption = StrokeCaption(stroke, self)

    def osr2_drive_target(self):
        """``(video_path, player, actions)`` for the video on screen, or ``None`` for
        an image or a video with no funscript — mirrors the config panel's target so
        the view can point its one driver at whichever surface is foreground."""
        return drive_target_for(self._preview.current_video_path(), self._preview.player())

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close()
        elif key == Qt.Key.Key_Left:
            self._step(-1)
        elif key == Qt.Key.Key_Right:
            self._step(1)
        elif apply_stroke_key(self._stroke, key):
            self._stroke_caption.refresh()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._stroke_caption is not None:
            self._stroke_caption.reposition()

    def _step(self, delta: int) -> None:
        """Page ``delta`` items through the folder, wrapping at either end."""
        if len(self._items) <= 1:
            return
        self._index = (self._index + delta) % len(self._items)
        self._preview.show_media(*self._items[self._index])
        self.media_changed.emit()  # a different clip may need the OSR2 re-aimed

    def mouseDoubleClickEvent(self, event):
        self.close()  # a second double-click dismisses the fullscreen view

    def closeEvent(self, event):
        self._preview.clear()  # release any held video file so it can be deleted
        self.closed.emit()     # the view hands the OSR2 back to the toggle (or stops)
        super().closeEvent(event)
