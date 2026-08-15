"""A fullscreen slideshow of a set of generations — a folder's, or a shelf's
(Recents, Starred).

Reuses :class:`PreviewWidget` (in play-once mode) for the actual image/video
rendering and a :class:`~origenerator.slideshow.SlideshowPlaylist` for the order
and pacing. Images advance on a dwell timer; videos play once and advance when
they end (``PreviewWidget.video_ended``). The arrows step, Up culls, Down locks
the slide on screen against the advance (a locked clip replays, and the hold both
stars the slide and asks for an enhancement — see
:meth:`SlideshowView._hold_current`), Enter leaves for the shown item's own folder
(``open_requested``), and Escape closes.

Anything that moves off a locked slide — a step either way, a cull — releases the
lock, the way Fun Time's next/prev cancel a satellite's: the lock holds the slide
it was set on, not wherever the user wanders to.

The items either side of the one on screen ride along as small stills
(see :mod:`origenerator.gui.neighbor_previews`). The shared OSR2 stroke keys ride
along too (Space and friends — see :mod:`origenerator.gui.stroke_hud`) with
genau's drive panel floated up top, so the device can run over a slideshow of
stills.
"""

from PyQt6.QtWidgets import QLabel, QWidget, QVBoxLayout
from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

from origenerator.gui.neighbor_previews import NeighborPreviews, still_for
from origenerator.gui.position_caption import PositionCaption
from origenerator.gui.slideshow_pace import SlideshowPace
from origenerator.gui.preview_widget import PreviewWidget
from origenerator.gui.stroke_hud import apply_stroke_key
from origenerator.gui.stroke_panel import StrokePanel
from origenerator.slideshow import SlideshowPlaylist

_BEING_MADE = "Generating…"  # an item with no file yet, before its first frame


class SlideshowView(QWidget):
    # Enter on an item: leave the slideshow for that generation's own folder.
    open_requested = pyqtSignal(str)

    def __init__(self, items, *, image_dwell_ms=None, shuffle=None, on_delete=None,
                 on_enhance=None, on_star=None, player=None, stroke=None, pace=None,
                 parent=None):
        super().__init__(parent)
        self._on_delete = on_delete
        # Holding a slide is also how you ask for it: Down enhances what is on
        # screen if it hasn't already been made at the current settings, so the
        # one you stopped on is the one that gets the better version. ``E``
        # turns that off for the session, for when it is in the way.
        self._on_enhance = on_enhance
        self._enhance_on_hold = on_enhance is not None
        self._enhancing: set[str] = set()  # prompt_ids with a run in flight
        self._on_star = on_star
        self._frames: dict[str, bytes] = {}  # latest streamed frame, by generation
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
        # Already a fullscreen view, so a double-click leaves it rather than
        # spawning a nested one — the way out of every other fullscreen view here.
        self._preview = PreviewWidget(player=player, loop_videos=False,
                                      allow_fullscreen=False,
                                      on_double_click=self.close)
        self._preview.video_ended.connect(self._on_video_ended)
        # The media is refitted a beat after the window resizes (and again when a
        # video's resolution arrives), so re-place the neighbors when it lands.
        self._preview.media_resized.connect(self._reposition_neighbors)
        layout.addWidget(self._preview, 1)

        # The items either side of this one, floated over the black surround.
        self._neighbors = NeighborPreviews(self)

        # Where in the set this one is, floated over the bottom of the media —
        # the same plate the plain fullscreen view wears.
        self._counter = PositionCaption(self)
        # A note while an enhancement of the slide on screen is being made, and
        # again for a beat when the switch is flipped — the only way to tell, in
        # a view with no panels, that a press did anything. It sits just above
        # the position counter at the bottom, with the rest of what this view
        # says about the item on screen; the top-left corner belongs to genau's
        # console, which would be underneath it.
        self._note = QLabel(self)
        self._note.setStyleSheet(
            "color: white; background: rgba(0, 0, 0, 160);"
            " padding: 6px 12px; border-radius: 4px;"
        )
        self._note.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._note.hide()
        self._note_timer = QTimer(self)
        self._note_timer.setSingleShot(True)
        self._note_timer.timeout.connect(self._refresh_note)
        self._stroke_panel = StrokePanel(stroke, self, host=self) if stroke is not None else None

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._advance)

        self._show_current()

    # --- playback ----------------------------------------------------------

    def _show_current(self):
        """Render the current item and arm the dwell timer if it's an image.

        An item with no file yet is one still being made: it shows the frames its
        generation has streamed so far, or says so until the first arrives, and
        dwells like an image. A folder whose only item is cooking is still a
        folder worth watching.
        """
        self._timer.stop()
        item = self._playlist.current()
        if item is None:
            return
        path, media_type = item[0], item[1]
        if path is None:
            frame = self._frames.get(item[2] if len(item) > 2 else None)
            if frame is not None:
                self._preview.show_frame(frame)
            else:
                self._preview.show_message(_BEING_MADE)
        else:
            self._preview.show_media(path, media_type)
        self._update_counter()
        self._update_neighbors()
        self._refresh_note()  # the corner belongs to whatever is on screen now
        dwell = self._playlist.dwell_ms()
        if dwell is not None:
            self._timer.start(dwell)

    def show_live_frame(self, prompt_id: str, frame: bytes) -> None:
        """One more streamed frame of a generation in the playlist. Redraws only
        when that generation is the one on screen."""
        self._frames[prompt_id] = frame
        item = self._playlist.current()
        if item is not None and item[0] is None and len(item) > 2 and item[2] == prompt_id:
            self._preview.show_frame(frame)

    def _advance(self):
        self._playlist.advance()
        self._show_current()

    def release_media(self, paths):
        """Let go of any of ``paths`` on screen — a file about to be deleted (its
        own Up key condemns the item it's playing)."""
        self._preview.release_media(paths)

    def _delete_current(self):
        """Delete the current item (if a deleter is wired) and advance to the next."""
        self._playlist.unlock()  # the held slide is the one being culled
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

    def _step(self, delta: int):
        """Manual stepping — an arrow, or the console's transport: moving off a
        slide releases its lock, so the way out of a hold is the same key that
        got you anywhere else, not a second press of the one that set it."""
        self._playlist.unlock()
        if delta > 0:
            self._playlist.advance()
        else:
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
        return self._playlist.locked

    def stroke_step(self, delta: int) -> None:
        self._step(delta)

    def stroke_toggle_hold(self) -> None:
        self._hold_current()

    def stroke_cull(self) -> None:
        self._delete_current()

    def set_dwell_s(self, seconds: int) -> None:
        self._pace.set_seconds(seconds)

    def _on_pace_changed(self, seconds: int) -> None:
        """The pace moved — here or in another window — so the slide on screen
        takes the new one rather than waiting out the old."""
        self._playlist.image_dwell_ms = seconds * 1000
        if not self._playlist.locked:
            self._show_current()

    def _on_video_ended(self):
        """A clip finished: replay it while locked, else move on. A lock is
        repeat-one here, as it is on a Fun Time satellite."""
        if self._playlist.locked:
            self._show_current()
        else:
            self._advance()

    def _hold_current(self):
        """Down: hold the slide, star it, and ask for it to be enhanced.

        Stopping on a picture is the gesture that says you want it, so it is
        also the one that stars it and the one that asks for the better version
        — nothing extra to press, and the run happens while you keep looking at
        it. Releasing the hold asks for nothing; only stopping does.
        """
        held = self._toggle_lock()
        if held:
            self._enhance_current()

    def _toggle_enhance_on_hold(self):
        """E: stop (or resume) holding a slide meaning "enhance this"."""
        if self._on_enhance is None:
            return
        self._enhance_on_hold = not self._enhance_on_hold
        self._flash_note(
            "Enhance on hold: on" if self._enhance_on_hold else "Enhance on hold: off"
        )

    def _enhance_current(self):
        """Ask the gallery to enhance the slide on screen, if it wants one.

        The gallery decides whether it does — it holds the settings, and it is
        the one that knows whether this image already carries a version made at
        exactly them. ``True`` back means a run started, and the corner says so
        until the finished version arrives.
        """
        if self._on_enhance is None or not self._enhance_on_hold:
            return
        prompt_id = self._current_prompt_id()
        if prompt_id is None or prompt_id in self._enhancing:
            return
        if self._on_enhance(prompt_id):
            self._enhancing.add(prompt_id)
            self._refresh_note()

    def note_enhanced(self, prompt_id: str, path, media_type: str = "image",
                      still=None) -> None:
        """An enhancement of one of these items landed: the show points at it
        from here on, wherever that item sits in the running order.

        Not only while it is the one on screen. It was asked for minutes ago and
        the show has paged on since; and the playlist is the fixed set the show
        opened with — nothing re-reads the folder — so a swap confined to the
        current slide would leave every later pass replaying the version this
        one replaced. What is on screen changes only when the upgraded item is
        what's on it.
        """
        self._enhancing.discard(prompt_id)
        if self._playlist.replace_item(prompt_id, path, media_type, still):
            if self._current_prompt_id() == prompt_id:
                self._preview.show_media(path, media_type)
            self._update_neighbors()  # it may be the still riding either side
        self._refresh_note()

    def _current_prompt_id(self):
        """The id of the item on screen, or ``None`` — a playlist assembled
        without ids (a test's) names nothing."""
        item = self._playlist.current()
        return item[2] if item is not None and len(item) > 2 else None

    def _refresh_note(self):
        """Show "Enhancing…" while the slide on screen has a run in flight."""
        prompt_id = self._current_prompt_id()
        if prompt_id is not None and prompt_id in self._enhancing:
            self._note.setText("Enhancing…")
            self._note.show()
            self._reposition_note()
        else:
            self._note.hide()

    def _flash_note(self, text: str, ms: int = 1500):
        """Say something in the corner for a moment, then fall back to whatever
        the corner would otherwise be saying."""
        self._note.setText(text)
        self._note.show()
        self._reposition_note()
        self._note_timer.start(ms)

    def _reposition_note(self):
        """Centered just above the position counter, so everything this view
        says about the item on screen reads as one group."""
        self._note.adjustSize()
        self._counter.adjustSize()
        x = (self.width() - self._note.width()) // 2
        y = self.height() - self._counter.height() - self._note.height() - 30
        self._note.move(x, max(0, y))
        self._note.raise_()

    def _toggle_lock(self) -> bool:
        """Flip the lock; returns whether the slide is now held.

        Locking also stars what is on screen: holding a slide is how the user says
        this one is worth keeping, and having said it they should not have to say
        it twice in two ways.
        """
        if self._playlist.toggle_lock():
            self._timer.stop()  # hold on the current item
            self._star_current()
            self._update_counter()
            return True
        self._show_current()  # released, re-arming the dwell timer
        return False

    def _star_current(self):
        """Bookmark the item on screen, if a starrer is wired and it has an id."""
        item = self._playlist.current()
        if self._on_star is not None and item is not None and len(item) > 2:
            self._on_star(item[2])

    def _open_current(self):
        """Enter: leave the slideshow and hand its item to the gallery, which
        opens the folder it lives in — the way out of a shelf's slideshow, where
        what you're watching came from folders all over the tree."""
        prompt_id = self._current_prompt_id()
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
        self._counter.show_position(
            self._playlist.order[self._playlist.index] + 1, len(self._playlist),
            "  ·  locked" if self._playlist.locked else "",
        )

    # --- Qt events ---------------------------------------------------------

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close()
        elif key == Qt.Key.Key_Left:
            self._step(-1)
        elif key == Qt.Key.Key_Right:
            self._step(1)
        elif key == Qt.Key.Key_Up:
            self._delete_current()  # cull this one and move on
        elif key == Qt.Key.Key_Down:
            self._hold_current()    # hold it, star it, and enhance it
        elif key == Qt.Key.Key_E:
            self._toggle_enhance_on_hold()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._open_current()    # out of the slideshow, into its folder
        elif apply_stroke_key(self._stroke, key):
            # Space belongs to the stroke cluster now, everywhere — locking the
            # slideshow is Down, matching the auto-generate view's lock.
            self._stroke_panel.refresh()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._counter.reposition()
        self._reposition_neighbors()
        self._reposition_note()
        if self._stroke_panel is not None:
            self._stroke_panel.reposition()

    def closeEvent(self, event):
        self._timer.stop()
        self._preview.clear()  # release any held video file so it can be deleted
        super().closeEvent(event)
