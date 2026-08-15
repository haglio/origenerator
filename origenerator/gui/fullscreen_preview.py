"""A fullscreen view of a single image or video, opened by double-clicking a
preview. Escape or another double-click closes it.

It also opens over a generation that's still running: built with no media, it
shows that generation's streamed low-res frames (:meth:`show_frame`) until the
pane that opened it hands over the finished file (:meth:`show_landed`), at which
point it's an ordinary fullscreen view of that file. So a generation can be
watched full-screen while it's made, not only once it lands.

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
from origenerator.gui.stroke_hud import apply_stroke_key
from origenerator.gui.stroke_panel import StrokePanel

_GENERATING = "Generating…"


class FullscreenPreview(QWidget):
    closed = pyqtSignal()  # the view was dismissed (Esc, a double-click, or close)
    media_changed = pyqtSignal()  # paged to a different item (re-aim the OSR2 drive)

    def __init__(self, media: tuple | None, *, frame: bytes | None = None,
                 player=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preview")
        # The navigable folder: a lone item until set_playlist arms Left/Right to
        # page across the folder the view was opened from. Empty while following a
        # running generation — it has no file to page from yet.
        self._items: list[tuple] = [media] if media is not None else []
        self._index = 0
        # The enhancement levels of each item that has any, keyed by the file
        # the folder lists it under, so Shift+Left/Right steps the versions of
        # whatever is on screen. The base path is remembered separately: once
        # you have stepped onto a level, the file showing is no longer the key.
        self._levels_by_path: dict[str, list[tuple]] = {}
        self._level_base: str | None = None
        self._level_index = 0
        # Following a generation still in flight: no media of its own, so the pane
        # that opened it feeds the frames and hands over the file that lands.
        self._live = media is None
        # The gallery hands its app-global stroke driver in via set_stroke once
        # this view announces itself; until then the stroke keys are inert.
        self._stroke = None
        self._stroke_panel: StrokePanel | None = None
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
        if media is not None:
            self._preview.show_media(media[0], media[1])
        elif frame is not None:
            self._preview.show_frame(frame)  # the frame the double-click landed on
        else:
            self._preview.show_message(_GENERATING)  # opened before the first one

    def is_live(self) -> bool:
        """Whether this view is still following a generation in flight — the pane
        that opened it checks before feeding it another frame or its result."""
        return self._live

    def show_frame(self, data: bytes) -> None:
        """One more streamed frame of the generation being followed. Ignored once
        it has landed (or the view has paged away), which is no longer this run."""
        if self._live:
            self._preview.show_frame(data)

    def show_landed(self, media: tuple) -> None:
        """The followed generation finished: show the saved file in place of its
        frames, and become an ordinary fullscreen view of it — a finished video is
        a fresh OSR2 target, hence ``media_changed``."""
        if not self._live:
            return
        self._live = False
        self._items = [media]
        self._index = 0
        self._preview.show_media(media[0], media[1])
        self.media_changed.emit()

    def set_playlist(self, items: list[tuple], index: int) -> None:
        """Arm Left/Right to page across the folder the view was opened from.

        ``items`` is the folder's media in shown order as ``(path, media_type)``;
        ``index`` is the one already on screen. Until this is called the view holds
        a lone item and paging is inert.
        """
        self._items = list(items)
        self._index = index

    def set_levels(self, levels_by_path: dict) -> None:
        """Arm Shift+Left/Right to step an image's enhancement levels.

        ``levels_by_path`` maps the file the folder shows an image under to that
        image's versions, newest first, as ``(path, media_type)``. Plain
        Left/Right still pages the folder; the shifted pair moves within the one
        image — its own axis, because a version is not a neighbor.
        """
        self._levels_by_path = {str(k): list(v) for k, v in levels_by_path.items()}

    def set_stroke(self, stroke) -> None:
        """Wire the shared OSR2 stroke keys and genau's drive panel in — so the
        device can run over a fullscreen image, which has no script."""
        self._stroke = stroke
        if self._stroke_panel is None and stroke is not None:
            self._stroke_panel = StrokePanel(stroke, self)
            self._stroke_panel.reposition()
            self._stroke_panel.show()

    def release_media(self, paths) -> None:
        """Dismiss the view when what it's showing is about to be deleted: its
        video holds the file open, which would block the delete, and a
        fullscreen view of a file that's going is nothing to keep up."""
        if self._preview.is_showing_any(paths):
            self.close()  # closeEvent clears the preview, releasing the file

    def osr2_drive_target(self):
        """``(video_path, player, actions)`` for the video on screen, or ``None`` for
        an image or a video with no funscript — mirrors the config panel's target so
        the view can point its one driver at whichever surface is foreground."""
        return drive_target_for(self._preview.current_video_path(), self._preview.player())

    def keyPressEvent(self, event):
        key = event.key()
        shifted = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if key == Qt.Key.Key_Escape:
            self.close()
        elif key == Qt.Key.Key_Left:
            self._step_level(-1) if shifted else self._step(-1)
        elif key == Qt.Key.Key_Right:
            self._step_level(1) if shifted else self._step(1)
        elif apply_stroke_key(self._stroke, key):
            self._stroke_panel.refresh()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._stroke_panel is not None:
            self._stroke_panel.reposition()

    def _step(self, delta: int) -> None:
        """Page ``delta`` items through the folder, wrapping at either end."""
        if len(self._items) <= 1:
            return
        self._live = False  # paged off a live generation: its frames stop landing here
        self._index = (self._index + delta) % len(self._items)
        self._level_base = None  # a new image, so its own versions from the top
        self._level_index = 0
        self._preview.show_media(*self._items[self._index])
        self.media_changed.emit()  # a different clip may need the OSR2 re-aimed

    def _step_level(self, delta: int) -> None:
        """Step ``delta`` enhancement levels within the image on screen.

        A no-op for an image with one version, and for a video — there is
        nothing to compare it against, and silently doing nothing is better
        than paging the folder when the shift was the whole point.
        """
        base = self._level_base
        if base is None:
            if not self._items:
                return
            base = str(self._items[self._index][0])
        levels = self._levels_by_path.get(base) or []
        if len(levels) <= 1:
            return
        self._live = False
        self._level_base = base
        self._level_index = (self._level_index + delta) % len(levels)
        self._preview.show_media(*levels[self._level_index])

    def mouseDoubleClickEvent(self, event):
        self.close()  # a second double-click dismisses the fullscreen view

    def closeEvent(self, event):
        self._preview.clear()  # release any held video file so it can be deleted
        self.closed.emit()     # the view hands the OSR2 back to the toggle (or stops)
        super().closeEvent(event)
