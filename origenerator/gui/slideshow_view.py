"""A fullscreen slideshow of a set of generations — a folder's, or a shelf's
(Recents, Starred).

Reuses :class:`PreviewWidget` (in play-once mode) for the actual image/video
rendering and a :class:`~origenerator.slideshow.SlideshowPlaylist` for the order
and pacing. Images advance on a dwell timer; videos play once and advance when
they end (``PreviewWidget.video_ended``). The arrows step, Up culls, Down holds,
Enter leaves for the shown item's own folder (``open_requested``), and Escape
closes. The items either side of the one on screen ride along as small stills
(see :mod:`origenerator.gui.neighbor_previews`). The shared OSR2 stroke keys ride
along too (Space and friends — see :mod:`origenerator.gui.stroke_hud`) with
genau's drive panel floated up top, so the device can run over a slideshow of
stills.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

from origenerator.gui.neighbor_previews import NeighborPreviews, still_for
from origenerator.gui.slideshow_pace import SlideshowPace
from origenerator.gui.preview_widget import PreviewWidget
from origenerator.gui.stroke_hud import apply_stroke_key
from origenerator.gui.stroke_panel import StrokePanel
from origenerator.slideshow import SlideshowPlaylist


class SlideshowView(QWidget):
    # Enter on an item: leave the slideshow for that generation's own folder.
    open_requested = pyqtSignal(str)

    def __init__(self, items, *, image_dwell_ms=None, shuffle=None, on_delete=None,
                 player=None, stroke=None, pace=None, parent=None):
        super().__init__(parent)
        self._on_delete = on_delete
        self._stroke = stroke  # the gallery's app-global stroke driver, or None
        # How long a slide holds the screen is app-wide, because the console
        # that sets it is: turned up here or in the main window, it is the
        # same number. An explicit dwell (a test's) still wins.
        self._pace = pace if pace is not None else SlideshowPace(parent=self)
        if image_dwell_ms is None:
            image_dwell_ms = self._pace.dwell_ms
        self._pace.changed.connect(self._on_pace_changed)
        playlist_kwargs = {"image_dwell_ms": image_dwell_ms}
        if shuffle is not None:  # else the playlist uses its own random shuffle
            playlist_kwargs["shuffle"] = shuffle
        self._playlist = SlideshowPlaylist(items, **playlist_kwargs)
        self.setWindowTitle("Slideshow")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAutoFillBackground(True)  # a solid black surround behind the media
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("black"))
        self.setPalette(palette)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # Already a fullscreen view with its own keys, so a double-click here must
        # not spawn a nested fullscreen preview.
        self._preview = PreviewWidget(player=player, loop_videos=False,
                                      allow_fullscreen=False)
        self._preview.video_ended.connect(self._on_video_ended)
        # The media is refitted a beat after the window resizes (and again when a
        # video's resolution arrives), so re-place the neighbors when it lands.
        self._preview.media_resized.connect(self._reposition_neighbors)
        layout.addWidget(self._preview, 1)

        # The items either side of this one, floated over the black surround.
        self._neighbors = NeighborPreviews(self)

        # A translucent position/pause caption floating over the bottom of the media.
        self._counter = QLabel(self)
        self._counter.setStyleSheet(
            "color: white; background: rgba(0, 0, 0, 140);"
            " padding: 4px 10px; border-radius: 4px;"
        )
        self._counter.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._stroke_panel = StrokePanel(stroke, self, host=self) if stroke is not None else None

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._advance)

        self._show_current()

    # --- playback ----------------------------------------------------------

    def _show_current(self):
        """Render the current item and arm the dwell timer if it's an image."""
        self._timer.stop()
        item = self._playlist.current()
        if item is None:
            return
        path, media_type = item[0], item[1]
        self._preview.show_media(path, media_type)
        self._update_counter()
        self._update_neighbors()
        dwell = self._playlist.dwell_ms()
        if dwell is not None:
            self._timer.start(dwell)

    def _advance(self):
        self._playlist.advance()
        self._show_current()

    def release_media(self, paths):
        """Let go of any of ``paths`` on screen — a file about to be deleted (its
        own Up key condemns the item it's playing)."""
        self._preview.release_media(paths)

    def _delete_current(self):
        """Delete the current item (if a deleter is wired) and advance to the next."""
        item = self._playlist.current()
        if item is None:
            return
        if self._on_delete is not None and len(item) > 2:
            self._on_delete(item[2])
        self._playlist.remove_current()
        if self._playlist.is_empty():
            self.close()
        else:
            self._show_current()

    def _back(self):
        self._playlist.back()
        self._show_current()

    # --- what Genau's console acts on here ---------------------------------
    # Its transport steps Genau's clips and its clip-seconds pace how long an
    # unheld one stays up. Here the clips are the slides, so the same four
    # buttons step, hold and cull them, and the same pair sets the dwell.

    @property
    def dwell_s(self) -> int:
        return self._pace.seconds

    @property
    def locked(self) -> bool:
        """Whether what is on screen is being held — the console's padlock."""
        return self._playlist.paused

    def stroke_step(self, delta: int) -> None:
        self._advance() if delta > 0 else self._back()

    def stroke_toggle_hold(self) -> None:
        self._toggle_pause()

    def stroke_cull(self) -> None:
        self._delete_current()

    def set_dwell_s(self, seconds: int) -> None:
        self._pace.set_seconds(seconds)

    def _on_pace_changed(self, seconds: int) -> None:
        """The pace moved — here or in another window — so the slide on screen
        takes the new one rather than waiting out the old."""
        self._playlist.image_dwell_ms = seconds * 1000
        if not self._playlist.paused:
            self._show_current()

    def _on_video_ended(self):
        """A clip finished: move on, unless the user paused while it played."""
        if not self._playlist.paused:
            self._advance()

    def _toggle_pause(self):
        if self._playlist.toggle_pause():
            self._timer.stop()  # hold on the current item
            self._update_counter()
        else:
            self._show_current()  # resume, re-arming the dwell timer

    def _open_current(self):
        """Enter: leave the slideshow and hand its item to the gallery, which
        opens the folder it lives in — the way out of a shelf's slideshow, where
        what you're watching came from folders all over the tree."""
        item = self._playlist.current()
        prompt_id = item[2] if item is not None and len(item) > 2 else None
        self.close()
        if prompt_id is not None:
            self.open_requested.emit(prompt_id)

    # --- the neighboring items ---------------------------------------------

    def _update_neighbors(self):
        """Draw the items either side of this one — nothing on a playlist too
        short for a neighbor to be anything but the item already on screen."""
        if len(self._playlist) < 2:
            self._neighbors.set_neighbors(None, None)
            return
        self._neighbors.set_neighbors(
            still_for(self._playlist.peek(-1)), still_for(self._playlist.peek(1)),
            media_rect=self._media_rect(),
        )

    def _reposition_neighbors(self):
        self._neighbors.reposition(self._media_rect())

    def _media_rect(self):
        """Where the media is drawn, in this view's coordinates."""
        rect = self._preview.media_rect()
        rect.moveTopLeft(self._preview.mapTo(self, rect.topLeft()))
        return rect

    # --- caption -----------------------------------------------------------

    def _update_counter(self):
        # Show the item's number within the set (its shuffled position), not the
        # step count — so a random slideshow visibly jumps around, e.g. 7, 23, 16.
        text = f"{self._playlist.order[self._playlist.index] + 1} / {len(self._playlist)}"
        if self._playlist.paused:
            text += "  ·  paused"
        self._counter.setText(text)
        self._reposition_counter()

    def _reposition_counter(self):
        self._counter.adjustSize()
        x = (self.width() - self._counter.width()) // 2
        y = self.height() - self._counter.height() - 24
        self._counter.move(max(0, x), max(0, y))

    # --- Qt events ---------------------------------------------------------

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close()
        elif key == Qt.Key.Key_Left:
            self._back()
        elif key == Qt.Key.Key_Right:
            self._advance()
        elif key == Qt.Key.Key_Up:
            self._delete_current()  # cull this one and move on
        elif key == Qt.Key.Key_Down:
            self._toggle_pause()    # hold on the current item
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._open_current()    # out of the slideshow, into its folder
        elif apply_stroke_key(self._stroke, key):
            # Space belongs to the stroke cluster now, everywhere — holding the
            # slideshow is Down, matching the auto-generate view's lock.
            self._stroke_panel.refresh()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_counter()
        self._reposition_neighbors()
        if self._stroke_panel is not None:
            self._stroke_panel.reposition()

    def closeEvent(self, event):
        self._timer.stop()
        self._preview.clear()  # release any held video file so it can be deleted
        super().closeEvent(event)
