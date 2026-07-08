"""A fullscreen view of a single image or video, opened by double-clicking a
preview. Escape or another double-click closes it.

Reuses :class:`PreviewWidget` (looping, like the inline preview) for the actual
rendering, over a solid black surround. The media is scaled as large as it fits
the screen without cropping, so a shape that doesn't match the screen letterboxes
on two sides at most — never stranded small with black on all four. Opened by
:meth:`PreviewWidget.open_fullscreen`; the opening preview keeps the reference
alive, mirroring how the gallery holds its slideshow window.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtCore import Qt

from origenerator.gui.preview_widget import PreviewWidget


class FullscreenPreview(QWidget):
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
        # and a double-click on it (the media fills the window) dismisses the view.
        self._preview = PreviewWidget(player=player, allow_fullscreen=False,
                                      show_funscript_strip=True,
                                      on_double_click=self.close)
        layout.addWidget(self._preview, 1)
        self._preview.show_media(media[0], media[1])

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.close()  # a second double-click dismisses the fullscreen view

    def closeEvent(self, event):
        self._preview.clear()  # release any held video file so it can be deleted
        super().closeEvent(event)
