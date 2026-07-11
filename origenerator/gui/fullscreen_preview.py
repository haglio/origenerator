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


class FullscreenPreview(QWidget):
    closed = pyqtSignal()  # the view was dismissed (Esc, a double-click, or close)

    def __init__(self, media: tuple, *, player=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preview")
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

    def osr2_drive_target(self):
        """``(video_path, player, actions)`` for the video on screen, or ``None`` for
        an image or a video with no funscript — mirrors the config panel's target so
        the view can point its one driver at whichever surface is foreground."""
        return drive_target_for(self._preview.current_video_path(), self._preview.player())

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.close()  # a second double-click dismisses the fullscreen view

    def closeEvent(self, event):
        self._preview.clear()  # release any held video file so it can be deleted
        self.closed.emit()     # the view hands the OSR2 back to the toggle (or stops)
        super().closeEvent(event)
