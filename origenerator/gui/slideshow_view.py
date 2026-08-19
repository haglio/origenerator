"""The fullscreen player — the one way this app fills the screen with a picture.

It plays a set of generations: a folder's, a shelf's (Recents, Starred), or the
one folder a double-clicked picture came from. Reuses :class:`PreviewWidget` (in
play-once mode) for the actual image/video rendering and a
:class:`~origenerator.slideshow.SlideshowPlaylist` for the order and pacing.
Images advance on a dwell timer; videos play once and advance when they end
(``PreviewWidget.video_ended``). The arrows step, Shift+arrows step the
enhancement levels of the picture on screen, Up culls, Down locks the slide
against the advance (a locked clip replays, and the hold both stars the slide and
asks for an enhancement — see :meth:`SlideshowView._hold_current`), Enter leaves
for the shown item's own folder (``open_requested``), and Escape closes. Ending
a show on a locked slide leaves for that slide's folder too: holding one is the
user saying this is the one, so the gallery lands there rather than back where
it was when the show started.

**Double-clicking a picture opens this same view at a pace of nought** — its
folder in the browser's own order, starting on the picture that was clicked,
holding it until an arrow moves it. There used to be a second full-screen
viewer for that, with its own keys to learn and its own copy of the counter, the
neighbor stills, the level stepping and the culling; a show that simply never
moves on is the same thing with nothing to keep in sync. Turning the console's
clip-seconds pace up off nought is what sets such a show going.

Anything that moves off a locked slide — a step either way, a cull — releases the
lock, the way Fun Time's next/prev cancel a satellite's: the lock holds the slide
it was set on, not wherever the user wanders to.

A second hold is the show's own: :meth:`SlideshowView.hold_for_request` stops the
advance while a spoken request is being said, since the request is about what is
on screen and a show that pages on mid-sentence would aim it at the wrong slide.
It is independent of the lock, so releasing it never unlocks a held slide.

The set is not frozen at the opening. It holds only generations there is
something to look at — one still being made is not a slide — and the gallery
hands each one over as it lands (:meth:`SlideshowView.note_added`), so a show of
a folder that is auto-generating keeps up with it.

It also opens over a generation that's still running: built with no items, it
shows that generation's streamed low-res frames (:meth:`show_frame`) until the
pane that opened it hands over the finished file (:meth:`show_landed`), at which
point it is an ordinary show of that file. So a generation can be watched
full-screen while it's made, not only once it lands.

The items either side of the one on screen ride along as small stills
(see :mod:`origenerator.gui.neighbor_previews`), and the bottom strip's queue
itself is floated into the bottom-left corner
(:mod:`origenerator.gui.slideshow_queue`) — live frame, progress bar, rows and
their buttons — since the strip that carries it is behind this window, and a show
is exactly when the line stops moving and when the user keeps adding to it. The
shared OSR2 stroke keys ride along too (Space and friends — see
:mod:`origenerator.gui.stroke_hud`) with genau's drive panel floated up top, so
the device can run over a show of stills; a clip that carries a funscript instead
offers itself as an
:meth:`osr2_drive_target`. Being the deliberate foreground view, it plays sound —
the inline preview stays muted.
"""

from PyQt6.QtWidgets import QLabel, QWidget, QVBoxLayout
from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

from origenerator.gui.neighbor_previews import NeighborPreviews, still_for
from origenerator.gui.osr2_driver import drive_target_for
from origenerator.gui.position_caption import PositionCaption
from origenerator.gui.slideshow_pace import SlideshowPace
from origenerator.gui.slideshow_queue import SlideshowQueue
from origenerator.gui.preview_widget import PreviewWidget
from origenerator.gui.stroke_hud import apply_stroke_key
from origenerator.gui.stroke_panel import StrokePanel
from origenerator.slideshow import SlideshowPlaylist, in_order

_GENERATING = "Generating…"
# What the corner says about an enhancement of the slide on screen. Which of the
# two is a fact about the run, not about the ask: holding slide after slide
# sends out a line of runs, and ComfyUI is making exactly one of them.
_ENHANCING = "Enhancing…"
_ENHANCE_QUEUED = "Enhancement queued"


class SlideshowView(QWidget):
    # Enter on an item: leave the slideshow for that generation's own folder.
    open_requested = pyqtSignal(str)
    # The show was dismissed (Escape, Enter out, or culled empty) — the gallery
    # keeps voice-command listening tied to a fullscreen surface being up.
    closed = pyqtSignal()
    # A different item (or version) is on screen — re-aim the OSR2 drive.
    media_changed = pyqtSignal()

    def __init__(self, items, *, frame=None, start=None, image_dwell_ms=None,
                 shuffle=None, on_delete=None, on_enhance=None, on_star=None,
                 player=None, stroke=None, pace=None, on_drive_toggle=None,
                 parent=None):
        super().__init__(parent)
        self._on_delete = on_delete
        # Holding a slide is also how you ask for it: Down enhances what is on
        # screen if it has never been enhanced, so the one you stopped on is the
        # one that gets the better version — and one that already has a better
        # version is left alone. ``E`` turns that off for the session, for when
        # it is in the way.
        self._on_enhance = on_enhance
        self._enhance_on_hold = on_enhance is not None
        self._enhancing: set[str] = set()  # prompt_ids with a run in flight
        # How each enhancement in flight is actually going, as the gallery
        # reads it (``prompt_id`` -> "running"/"queued"). Pushed in by
        # :meth:`note_enhancing`: the show knows what it asked for, and only
        # the side holding the jobs knows which of them is on the GPU.
        self._enhance_status: dict[str, str] = {}
        self._on_star = on_star
        self._stroke = stroke  # the gallery's app-global stroke driver, or None
        # Space goes to the gallery's one OSR2 switch rather than straight to
        # the stroke: which source drives is that switch's call, not a key's.
        self._on_drive_toggle = on_drive_toggle
        # Following a generation still in flight: no items of its own, so the pane
        # that opened this feeds the frames and hands over the file that lands.
        self._live = not items
        self._frame = frame  # the frame the double-click landed on, if any
        # The item to hand the gallery on the way out, once there is one: Enter
        # names it outright, and a lock names it by being the slide the show
        # ended on. Read in :meth:`closeEvent`, which is where every way out of
        # the show meets.
        self._land_on: str | None = None
        # The enhancement levels of each item that has any, keyed by the file the
        # set lists it under, so Shift+Left/Right steps the versions of whatever
        # is on screen. The base path is remembered separately: once you have
        # stepped onto a level, the file showing is no longer the key.
        self._levels_by_path: dict[str, list[tuple]] = {}
        self._level_base: str | None = None
        self._level_index = 0
        # How long a slide holds the screen is app-wide, because the console
        # that sets it is: turned up here or in the main window, it is the
        # same number. An explicit dwell (a double-clicked picture's nought,
        # or a test's) wins until the console next moves the pace.
        self._pace = pace if pace is not None else SlideshowPace(parent=self)
        if image_dwell_ms is None:
            image_dwell_ms = self._pace.dwell_ms
        self._dwell_s = image_dwell_ms // 1000
        self._pace.changed.connect(self._on_pace_changed)
        playlist_kwargs = {"image_dwell_ms": image_dwell_ms, "start": start}
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
        # Already the fullscreen view, so a double-click leaves it rather than
        # spawning a nested one. It plays sound (mute_audio=False), unlike the
        # muted inline preview, and wears the funscript strip a scripted clip's
        # stroke motion shows in.
        self._preview = PreviewWidget(player=player, loop_videos=False,
                                      allow_fullscreen=False,
                                      show_funscript_strip=True, mute_audio=False,
                                      on_double_click=self.close)
        self._preview.video_ended.connect(self._on_video_ended)
        # The media is refitted a beat after the window resizes (and again when a
        # video's resolution arrives), so re-place the neighbors when it lands.
        self._preview.media_resized.connect(self._reposition_neighbors)
        layout.addWidget(self._preview, 1)

        # The items either side of this one, floated over the black surround.
        self._neighbors = NeighborPreviews(self)

        # Where in the set this one is, floated over the bottom of the media.
        self._counter = PositionCaption(self)
        # The bottom strip's queue itself — the live frame, the bar, the rows and
        # their buttons — floated into the corner this view leaves empty. The
        # strip that normally carries it is behind this window, and a show is
        # both when the queue stops moving (its videos are held) and when the
        # user keeps adding to it (a held slide asks for an enhancement).
        self._queue = SlideshowQueue(self)
        # A note about the item on screen: which of its versions this is, that an
        # enhancement of it is being made, and for a beat whatever a switch or a
        # spoken fix just did — the only way to tell, in a view with no panels,
        # that a press did anything. It sits just above the position counter at
        # the bottom, with the rest of what this view says about the item on
        # screen; the top-left corner belongs to genau's console, which would be
        # underneath it.
        self._note = QLabel(self)
        self._note.setStyleSheet(
            "color: white; background: rgba(0, 0, 0, 160);"
            " padding: 6px 12px; border-radius: 4px;"
        )
        self._note.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._note.hide()
        # What the corner reads while a spoken request holds the show; empty
        # whenever nothing is being dictated.
        self._request_note = ""
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
        """Render the current item and arm the dwell timer if it's an image."""
        self._timer.stop()
        if self._live:
            # Nothing on disk yet: the run's own frames stand in for a slide.
            if self._frame is not None:
                self._preview.show_frame(self._frame)
            else:
                self._preview.show_message(_GENERATING)  # opened before the first one
            self._update_counter()
            self._update_neighbors()
            return
        item = self._playlist.current()
        if item is None:
            return
        self._level_base = None  # a new item, so its own versions from the top
        self._level_index = 0
        self._preview.show_media(item[0], item[1])
        self._update_counter()
        self._update_neighbors()
        self._refresh_note()  # the note belongs to whatever is on screen now
        dwell = self._playlist.dwell_ms()
        if dwell is not None:
            self._timer.start(dwell)
        self.media_changed.emit()  # a different clip may need the OSR2 re-aimed

    def set_playlist(self, items, index: int) -> None:
        """Re-seed the set this show plays, on ``index``.

        What a double-clicked picture's show is armed with once the gallery has
        worked out the folder behind it: the view comes up on the one item the
        pane had, and this hands it the rest in the browser's own order. A view
        still following a generation keeps its frames — it has no place among
        those files until an arrow leaves them for one.
        """
        self._playlist = SlideshowPlaylist(
            items, image_dwell_ms=self._dwell_s * 1000, shuffle=in_order,
            start=index,
        )
        if self._live:
            self._update_counter()
            self._update_neighbors()
        else:
            self._show_current()

    def set_levels(self, levels_by_path: dict) -> None:
        """Arm Shift+Left/Right to step an image's enhancement levels.

        ``levels_by_path`` maps the file the set shows an image under to that
        image's versions, newest first, as ``(path, media_type, label)``. Plain
        Left/Right still steps the set; the shifted pair moves within the one
        image — its own axis, because a version is not a neighbor.
        """
        self._levels_by_path = {str(k): list(v) for k, v in levels_by_path.items()}
        self._refresh_note()

    def queue(self) -> SlideshowQueue:
        """The floated queue, for the gallery to wire its reorder and clear to —
        it is the same widget as the bottom strip and asks the same things."""
        return self._queue

    def set_queue(self, items, foreign_queued: int = 0) -> None:
        """Show what is in flight in the corner — the same list, in the same
        order, the bottom strip this view is covering would be showing."""
        self._queue.set_items(items, foreign_queued)
        self._reposition_queue()

    def _reposition_queue(self) -> None:
        """Place the queue, keeping it clear of the position counter — the two
        share the foot of the screen, and the counter's width moves with what it
        says."""
        counter = None if self._counter.isHidden() else self._counter.geometry()
        self._queue.reposition(avoid=counter)

    def note_added(self, path, media_type: str, prompt_id: str, still=None) -> None:
        """A generation that belongs to what this show is playing has landed: it
        joins the set, queued to come up next.

        A folder that is auto-generating is the case this is for. Without it the
        show plays the fixed set it opened with, so the very items being made
        while it runs — the ones being watched for — are the ones it never gets
        to. The slide on screen is left alone; only the counter and the stills
        either side move, since the set they describe just grew.
        """
        if self._playlist.add((path, media_type, prompt_id, still)):
            self._update_counter()
            self._update_neighbors()

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
        if self._live and self._playlist.is_empty():
            return  # a run with no folder armed behind it: nowhere to step to
        self._playlist.unlock()
        self._live = False  # stepped off a live generation: its frames stop landing
        if delta > 0:
            self._playlist.advance()
        else:
            self._playlist.back()
        self._show_current()

    def _step_level(self, delta: int) -> None:
        """Step ``delta`` enhancement levels within the image on screen.

        A no-op for an image with one version, and for a video — there is
        nothing to compare it against, and silently doing nothing is better
        than stepping the set when the shift was the whole point.
        """
        base = self._level_base or self._current_base()
        levels = self._levels_by_path.get(base) or []
        if len(levels) <= 1:
            return
        self._live = False
        self._level_base = base
        self._level_index = (self._level_index + delta) % len(levels)
        self._preview.show_media(*levels[self._level_index][:2])
        self._refresh_note()
        self.media_changed.emit()

    # --- opened over a generation still being made --------------------------

    def is_live(self) -> bool:
        """Whether this show is still following a generation in flight — the pane
        that opened it checks before feeding it another frame or its result."""
        return self._live

    def show_frame(self, data: bytes) -> None:
        """One more streamed frame of the generation being followed. Ignored once
        it has landed (or the show has stepped away), which is no longer this run."""
        if self._live:
            self._frame = data
            self._preview.show_frame(data)

    def show_landed(self, media: tuple) -> None:
        """The followed generation finished: show the saved file in place of its
        frames, and become an ordinary show of it."""
        if not self._live:
            return
        self._live = False
        self._playlist = SlideshowPlaylist(
            [media], image_dwell_ms=self._dwell_s * 1000, shuffle=in_order,
        )
        self._show_current()

    # --- what Genau's console acts on here ---------------------------------
    # Its transport steps Genau's clips and its clip-seconds pace how long an
    # unheld one stays up. Here the clips are the slides, so the same four
    # buttons step, hold and cull them, and the same pair sets the dwell.

    @property
    def dwell_s(self) -> int:
        """The seconds this show leaves an unheld slide up — nought while it is
        holding one picture, which is how a double-clicked one opens."""
        return self._dwell_s

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
        """Take a new pace, and hand it on: the number is app-wide, so a show
        opened at nought that is turned up sets the pace for the next one too.

        Applied here as well as posted to the pace, rather than only waiting for
        the signal back — a show sitting at nought while the app-wide pace already
        reads one gets no signal from a step up to one, and would stay frozen.
        """
        self._pace.set_seconds(seconds)  # fires _on_pace_changed if it moved
        self._apply_dwell(self._pace.seconds)  # and take it even if it didn't

    def _on_pace_changed(self, seconds: int) -> None:
        """The pace moved — here or in another window — so the slide on screen
        takes the new one rather than waiting out the old."""
        self._apply_dwell(seconds)

    def _apply_dwell(self, seconds: int) -> None:
        seconds = max(0, int(seconds))
        if seconds == self._dwell_s:
            return
        self._dwell_s = seconds
        self._playlist.image_dwell_ms = seconds * 1000
        if not self._playlist.locked and not self._live:
            self._show_current()

    def _on_video_ended(self):
        """A clip finished: replay it while held, else move on. A lock is
        repeat-one here, as it is on a Fun Time satellite — and a pace of nought
        holds the clip the same way, since nought means nothing moves on its own.
        A request being spoken holds it too: paging on mid-sentence is exactly
        what that pause exists to stop.
        """
        if self._playlist.holding() or not self._dwell_s:
            self._show_current()
        else:
            self._advance()

    # --- the hold a spoken request puts on the show ------------------------

    def hold_for_request(self, holding: bool, note: str = "") -> None:
        """Stop (or release) the advance while a request is being spoken.

        Not the user's lock: a slide they had locked is still locked when the
        request ends, and one they hadn't goes back to its dwell. ``note`` is
        what the corner should say while it holds — the only sign, in a view
        with no panels, that the mic is taking a sentence.
        """
        self._playlist.set_paused(holding)
        if holding:
            self._timer.stop()
            self._note_timer.stop()  # it holds, rather than fading after a beat
            self._request_note = note
            self._refresh_note()
        else:
            self._request_note = ""
            self._refresh_note()
            if not self._playlist.locked:
                self._rearm_dwell()

    def note_request(self, message: str) -> None:
        """Say what a spoken request did, where the speaker is looking."""
        self._flash_note(message, ms=3000)

    def _rearm_dwell(self) -> None:
        """Start the dwell timer again for the slide already on screen — a
        released pause resumes the show rather than restarting the media, which
        for a video part-way through would send it back to its first frame."""
        dwell = self._playlist.dwell_ms()
        if dwell is not None:
            self._timer.start(dwell)

    def _hold_current(self):
        """Down: hold the slide, star it, and ask for it to be enhanced.

        Stopping on a picture is the gesture that says you want it, so it is
        also the one that stars it and the one that asks for the better version
        — nothing extra to press, and the run happens while you keep looking at
        it. Releasing the hold asks for nothing; only stopping does, and only on
        a picture that has never been enhanced (the gallery's call).
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

        The gallery decides whether it does — it is the one that knows whether
        this image has already been enhanced, and an enhanced one wants nothing.
        ``True`` back means a run started, and the note says so until the
        finished version arrives.
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
        the show may have paged on since; and the playlist is the fixed set the
        show opened with — nothing re-reads the folder — so a swap confined to the
        current slide would leave every later pass replaying the version this
        one replaced. What is on screen changes only when the upgraded item is
        what's on it.
        """
        self._enhancing.discard(prompt_id)
        self._enhance_status.pop(prompt_id, None)
        if self._playlist.replace_item(prompt_id, path, media_type, still):
            if self._current_prompt_id() == prompt_id:
                self._level_base = None  # its versions are a level deeper now
                self._level_index = 0
                self._preview.show_media(path, media_type)
                self.media_changed.emit()
            self._update_neighbors()  # it may be the still riding either side
        self._refresh_note()

    def note_enhancing(self, statuses: dict) -> None:
        """How every enhancement in flight is going, as the gallery reads it:
        ``prompt_id`` -> ``"running"`` or ``"queued"``.

        Pushed in whenever it changes rather than asked for, because the show has
        no way to tell: a hold launches a run and hears only that one started,
        and a show of held slides has a line of them out at once with ComfyUI
        working through it one at a time. Without this the note claimed every one
        of them was being made the moment it was asked for.

        Carries every run in flight, not only the ones this show asked for —
        which of them the corner speaks for is :meth:`_refresh_note`'s call, and
        the ones it doesn't cost a dict entry each.
        """
        if statuses == self._enhance_status:
            return
        self._enhance_status = dict(statuses)
        # Not over a flash: a status arriving mid-sentence would wipe the answer
        # to a spoken command. The flash's own timer refreshes on the way out.
        if not self._note_timer.isActive():
            self._refresh_note()

    def _current_prompt_id(self):
        """The id of the item on screen, or ``None`` — a playlist assembled
        without ids (a test's) names nothing.

        Read off the playlist item rather than off the file showing, so it is
        still the right answer while Shift+Left/Right has stepped onto one of
        that item's other versions.
        """
        item = self._playlist.current()
        return item[2] if item is not None and len(item) > 2 else None

    def _current_base(self) -> str:
        """The file the set lists the item on screen under — what its versions
        are keyed by."""
        item = self._playlist.current()
        return str(item[0]) if item is not None else ""

    def voice_target(self):
        """The generation a spoken order or request is about: the slide on
        screen — what the speaker is looking at while saying it."""
        return self._current_prompt_id()

    def note_voice_run(self, prompt_id, message: str) -> None:
        """Say what a spoken order did and, when it launched a run
        (``prompt_id``), keep the note on that run once the flash fades — the
        same note a hold's enhance earns, and it reads the same way: where the
        run has got to, not merely that one was asked for."""
        if prompt_id is not None:
            self._enhancing.add(prompt_id)
        self.note_voice_command(message)

    def note_voice_command(self, message: str) -> None:
        """Say what a spoken command did. Here rather than in the gallery's own
        caption because the speaker is looking at this — the window behind it is
        covered by the very show being talked to."""
        self._flash_note(message, ms=2500)

    def _refresh_note(self):
        """Say what there is to say about the item on screen: the request being
        spoken (which holds the show, so it outranks the rest), where the version
        being made of it has got to, or — failing those — which of its versions
        this one is.

        Stepping levels is invisible without the last line: two versions of one
        picture differ by texture, which is exactly what you cannot tell apart
        from memory.
        """
        if self._request_note:
            self._show_note(self._request_note)
            return
        prompt_id = self._current_prompt_id()
        if prompt_id is not None and prompt_id in self._enhancing:
            # Being made, or still in the line — an ask made minutes ago on a
            # slide the show has come back around to is usually the latter, and
            # "Enhancing…" over a run nobody has started yet is simply wrong
            # about the picture being looked at. A run nothing has been said
            # about counts as waiting: the ask is what has happened to it so far.
            self._show_note(_ENHANCING
                            if self._enhance_status.get(prompt_id) == "running"
                            else _ENHANCE_QUEUED)
            return
        levels = self._levels_by_path.get(self._level_base or self._current_base()) or []
        if len(levels) <= 1:
            self._note.hide()
            return
        level = levels[self._level_index]
        label = level[2] if len(level) > 2 else f"Version {self._level_index + 1}"
        self._show_note(f"{label} — {self._level_index + 1} of {len(levels)}")

    def _show_note(self, text: str) -> None:
        self._note.setText(text)
        self._note.show()
        self._reposition_note()

    def _flash_note(self, text: str, ms: int = 1500):
        """Say something for a moment, then fall back to whatever the note would
        otherwise be saying."""
        self._show_note(text)
        self._note_timer.start(ms)

    def _reposition_note(self):
        """Centered just above the position counter, so everything this view
        says about the item on screen reads as one group."""
        self._note.adjustSize()
        self._counter.adjustSize()
        floor = self._counter.height() if not self._counter.isHidden() else 0
        x = (self.width() - self._note.width()) // 2
        y = self.height() - floor - self._note.height() - 30
        self._note.move(max(0, x), max(0, y))
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
        self._land_on = self._current_prompt_id()
        self.close()  # the handover is closeEvent's, so it happens exactly once

    def osr2_drive_target(self):
        """``(video_path, player, actions)`` for the video on screen, or ``None`` for
        an image or a video with no funscript — mirrors the config panel's target so
        the gallery can point its one driver at whichever surface is foreground."""
        return drive_target_for(self._preview.current_video_path(), self._preview.player())

    # --- the neighboring items ---------------------------------------------

    def _update_neighbors(self):
        """Draw the items either side of this one — nothing on a set too short
        for a neighbor to be anything but the item already on screen, and nothing
        at all while this is following a generation, which has no place among
        them yet."""
        if self._live or len(self._playlist) < 2:
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
        """Say where in the set this is — nothing at all while following a
        generation still being made, which is nowhere in it yet."""
        if self._live or self._playlist.is_empty():
            self._counter.hide()
            return
        self._counter.show()
        # Show the item's number within the set (its shuffled position), not the
        # step count — so a random slideshow visibly jumps around, e.g. 7, 23, 16.
        self._counter.show_position(
            self._playlist.order[self._playlist.index] + 1, len(self._playlist),
            "  ·  locked" if self._playlist.locked else "",
        )

    # --- Qt events ---------------------------------------------------------

    def keyPressEvent(self, event):
        key = event.key()
        shifted = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if key == Qt.Key.Key_Escape:
            self.close()
        elif key == Qt.Key.Key_Left:
            self._step_level(-1) if shifted else self._step(-1)
        elif key == Qt.Key.Key_Right:
            self._step_level(1) if shifted else self._step(1)
        elif key == Qt.Key.Key_Up:
            self._delete_current()  # cull this one and move on
        elif key == Qt.Key.Key_Down:
            self._hold_current()    # hold it, star it, and enhance it
        elif key == Qt.Key.Key_E:
            self._toggle_enhance_on_hold()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._open_current()    # out of the slideshow, into its folder
        elif apply_stroke_key(self._stroke, key,
                              on_drive_toggle=self._on_drive_toggle):
            # Space belongs to the stroke cluster now, everywhere — locking the
            # slideshow is Down, matching the auto-generate view's lock.
            self._stroke_panel.refresh()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._counter.reposition()
        self._reposition_queue()
        self._reposition_neighbors()
        self._reposition_note()
        if self._stroke_panel is not None:
            self._stroke_panel.reposition()

    def closeEvent(self, event):
        """Leave, handing the gallery the item the show ended on if there is one.

        Enter names that item; so does a lock, which is the user saying this is
        the one — so a show ended on a held slide lands on that slide, rather
        than leaving the gallery wherever it was before the show. Ended on a
        slide nobody held (Escape, a double-click, the spoken "close", the last
        item culled), it hands nothing over and leaves the gallery alone.
        """
        self._timer.stop()
        self._preview.clear()  # release any held video file so it can be deleted
        landing = self._land_on
        if landing is None and self._playlist.locked:
            landing = self._current_prompt_id()
        # Cleared before the signals go out, so a second close hands over nothing.
        self._land_on = None
        self._playlist.unlock()
        self.closed.emit()
        if landing is not None:
            self.open_requested.emit(landing)
        super().closeEvent(event)
