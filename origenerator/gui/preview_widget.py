"""A preview pane that shows an image or video for the selected generation.

The gallery hands it a resolved ``(path, media_type)`` and it does the rest:
static images are scaled to fit (and rescaled on resize), animated images
(animated WebP/GIF) loop via ``QMovie``, and videos auto-play on a loop, muted, so
selecting one gives an immediate moving preview without stealing audio.

A pane the owner has armed (:meth:`PreviewWidget.set_actions`) also carries the
three controls a gallery thumbnail of the same generation wears in its corners,
and offers the same right-click menu over the picture — because it IS the same
generation, and where you are standing should not change what you can do to it.
Unarmed — a live frame, a message — the picture is inert.
"""

from __future__ import annotations

import os
from pathlib import Path

from app_support.funscript import read_actions
from PyQt6.QtCore import (
    QEvent,
    QPoint,
    QRect,
    QSize,
    Qt,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import QImageReader, QMovie, QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaMetaData, QMediaPlayer
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from origenerator.config import COMFYUI_OUTPUT_DIR
from origenerator.funscript import funscript_of
from origenerator.gui import omnipause
from origenerator.gui.combination_view import CombinationView
from origenerator.gui.contact_sheet import ContactSheet
from origenerator.gui.corner_controls import CornerControls
from origenerator.gui.drag_thumbnail import (
    DragOut,
    fit_thumbnail,
    label_thumbnail,
)
from origenerator.gui.generation_drag import generation_mime
from origenerator.gui.video_surface import VideoSurface
from origenerator.gui.video_timeline import VideoTimeline
from origenerator.media import MediaType

_PLACEHOLDER = "Select a generation to preview"

_NOTICE_PLATE = ("color: white; background: rgba(0, 0, 0, 200);"
                 " padding: 6px 12px; border-radius: 4px;")
_NOTICE_MARGIN = 12  # how far the plate floats from the media's top-left corner


def _path_key(path) -> str:
    """One comparable form for a file path, so two spellings of the same file —
    a ``Path`` against a string, or Windows' case-blind pair — match."""
    return os.path.normcase(os.path.abspath(str(path)))


class PreviewWidget(QWidget):
    media_resized = pyqtSignal()  # the media was refitted (an overlay must re-place)
    action_triggered = pyqtSignal(str, str)  # a corner control: prompt_id, action
    context_requested = pyqtSignal(str, QPoint)  # right-clicked: prompt_id, global pos

    def __init__(self, parent=None, *, player: QMediaPlayer | None = None,
                 show_timeline: bool = False):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._movie: QMovie | None = None
        self._movie_native = None
        # The current on-disk media as (path, media_type), or None while showing a
        # placeholder or a live frame — what a double-click pops open fullscreen.
        self._media: tuple | None = None
        # Whether a generation is running under this pane — its streamed frames, or
        # the wait before the first one arrives — and that latest frame. A double-click
        # opens fullscreen over these too, and the view opened that way keeps following
        # from here: later frames, then the finished file. Without it, watching a
        # generation had to wait for it to land.
        self._live = False
        self._live_frame: bytes | None = None
        self._fullscreen = None  # the show a double-click here opened, kept alive here
        self._open_fullscreen_view = None
        self._generation: str | None = None
        self.drag_out = DragOut()

        # The shown generation's prompt_id when the owner has armed the corner
        # controls and the right-click menu over it, else None. Armed separately
        # from the drag because they answer different questions: a drag needs
        # something to carry, and these need a row to act on.
        self._actions_id: str | None = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # Right-click the picture for the same menu a gallery thumbnail of it gives.
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

        # Parented before the pane that will hold its video surface: Qt takes a
        # widget's children down in the order they were parented, so the player
        # goes first, stopped and detached, rather than rendering into a surface
        # already gone (test_the_player_is_torn_down_before_the_surface_it_renders_to).
        # The player is injectable so unit tests can drive playback intent
        # without spinning up the real (WMF) backend, which deadlocks at exit.
        self._player = player if player is not None else QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._audio.setMuted(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        media_host = QWidget()
        self._media_host = media_host
        outer.addWidget(media_host, 1)
        self._stack = QStackedLayout(media_host)
        self._stack.setContentsMargins(0, 0, 0, 0)

        self._image_label = QLabel(_PLACEHOLDER)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setMinimumHeight(240)
        # Let the placeholder wrap so its text width doesn't set a wide minimum
        # on the preview pane (and thus the whole window).
        self._image_label.setWordWrap(True)
        # Rescale the media whenever the label itself resizes — see eventFilter for
        # why this can't ride on the widget's own resizeEvent.
        self._image_label.installEventFilter(self)
        # The media area itself resizes when the timeline appears or goes, whichever
        # page is up -- and a video's page is not the label -- so what is placed
        # against the media's rect re-places off the host too (see eventFilter).
        media_host.installEventFilter(self)
        # Let mouse events fall through to this widget, so a press/drag/double-click
        # over the media is handled here (drag-out, open-fullscreen) rather than being
        # swallowed by the label or the video surface.
        self._image_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._stack.addWidget(self._image_label)

        self._video = VideoSurface()
        self._video.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video.video_sink())
        self._player.setLoops(QMediaPlayer.Loops.Infinite)

        # Until a clip's resolution arrives, media_rect can only answer "the whole
        # pane"; the corners have to move to the real picture once it can.
        self._player.metaDataChanged.connect(self._place_controls)
        self._stack.addWidget(self._video)

        # A third page, for what is not a generation at all: an image and the
        # settings of a past video, waiting to be run together (see
        # :meth:`show_combination`).
        self._combination = CombinationView()
        self._combination.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._stack.addWidget(self._combination)

        # A fourth page, for what is not one generation but a whole folder of
        # them: every picture in it, tiled to fill (see :meth:`show_folder`).
        self._sheet = ContactSheet()
        self._sheet.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._stack.addWidget(self._sheet)

        self._stack.setCurrentWidget(self._image_label)

        self._notice = QLabel(media_host)
        self._notice.setStyleSheet(_NOTICE_PLATE)
        self._notice.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._notice.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._notice.hide()

        self._controls = CornerControls(self)
        self._controls.triggered.connect(self._on_control)

        self._timeline = VideoTimeline() if show_timeline else None
        if self._timeline is not None:
            outer.addWidget(self._timeline)
            self._timeline.hide()
            self._player.durationChanged.connect(self._timeline.set_duration)
            self._player.positionChanged.connect(self._timeline.set_position)

        # The real WMF backend can deadlock during Qt/Python shutdown if a player
        # is still active, so release it before the app quits. Injected test
        # players don't touch the backend and don't need (or want) this hook.
        app = QApplication.instance()
        if player is None and app is not None:
            app.aboutToQuit.connect(self.release_player)

        # Last, once there is something to hold: a pane built into a frozen room
        # is told so here rather than by whoever built it (see the module).
        omnipause.holds(self)

    def _take_the_pane(self, media, *, generation: str | None = None,
                       stop_player: bool = True, enhancing: bool = False,
                       live: bool = False, live_frame: bytes | None = None) -> None:
        """Put down everything the pane is holding, ready for new content.

        This is what showing anything means, said once: the movie and the still
        are retired and the other pages put down (:meth:`_set_movie` clears the
        combination and the wall), the timeline drops, the playback stops,
        the notice and the corner controls — both of which are about the picture
        being replaced, and so can no more outlive it than it can — go, and the
        pane records what it is about to be showing (``media``, or ``None`` for
        anything that is not a file on disk) and hands a fullscreen view opened
        over a running generation the file it landed as.

        The two switches are the deliberate exceptions, one caller each.
        ``stop_player`` — a clip does not stop the player it is about to hand a
        new source to. ``enhancing`` — frames of an enhancement of the picture
        on screen are the coming state of that picture, so its notice and its
        corners are as true of them and stay.
        """
        self._set_movie(None)
        self._pixmap = None
        self._hide_timeline()
        if stop_player:
            self._stop_playback()
        if not enhancing:
            self.set_notice(None)
            self.set_actions(None)
        self._media, self._generation = media, generation
        self._end_live(media)
        if live:
            self._live, self._live_frame = True, live_frame

    def show_media(self, path, media_type: str, generation: str | None = None) -> None:
        """Display ``path`` as an image or video per ``media_type``."""
        if media_type == MediaType.VIDEO:
            self.show_video(path, generation)
        else:
            self.show_image(path, generation)

    def show_image(self, path, generation: str | None = None) -> None:
        self._take_the_pane((path, MediaType.IMAGE), generation=generation)
        reader = QImageReader(str(path))
        if reader.supportsAnimation() and reader.imageCount() > 1:
            self._set_movie(QMovie(str(path)), reader.size())
            self._stack.setCurrentWidget(self._image_label)
        else:
            self._show_picture(QPixmap(str(path)))

    def _show_picture(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self._rescale()
        self._stack.setCurrentWidget(self._image_label)

    def show_video(self, path, generation: str | None = None) -> None:
        self._take_the_pane((path, MediaType.VIDEO), generation=generation,
                            stop_player=False)
        self._image_label.clear()
        self._player.setSource(QUrl.fromLocalFile(str(Path(path))))
        self._stack.setCurrentWidget(self._video)
        self._player.play()
        if omnipause.frozen():
            self._player.pause()  # a clip loaded into a frozen room opens held
        self._show_timeline(path)

    def show_frame(self, data: bytes, *, enhancing: bool = False) -> None:
        """Display one in-progress preview frame from raw encoded image bytes.

        ComfyUI streams live previews as encoded images over the websocket
        rather than writing a file, so this loads straight from memory. Bytes
        that don't decode (a truncated frame) are ignored, leaving the current
        view untouched — which is why the decode happens before the pane is put
        down rather than after.

        ``enhancing`` marks the frames as the coming state of the picture
        already on display — an enhancement of it — rather than a run of the
        settings beside it. Whatever a notice says about that picture is just as
        true of the version being made, so it stays where it is: cleared by each
        frame and re-asserted by each keystroke, it flickers at the rate the run
        streams while the form is being typed in. The corners stay for the same
        reason, since what they act on is that picture.
        """
        pixmap = QPixmap()
        if not pixmap.loadFromData(data) or pixmap.isNull():
            return
        self._take_the_pane(None, enhancing=enhancing, live=True, live_frame=data)
        self._show_picture(pixmap)
        self._raise_notice()  # a kept notice, back over the frame that just landed
        win = self._following_fullscreen()
        if win is not None:
            win.show_frame(data)  # keep a view watching this generation up to date

    def show_combination(self, combination) -> None:
        """Show a combination waiting to be run: the frame on the left, a plus,
        and the gray looping clip whose settings go with it
        (:class:`~origenerator.gui.combination_view.CombinationView`).

        What "Edit…" leaves a tab holding. Nothing has been generated
        from it yet, so there is no media to show and the idle placeholder — the
        line a tab pointed at nothing wears — said only that, when the two things
        the tab is actually about were both on hand to be shown.
        """
        self._take_the_pane(None)
        self._image_label.clear()
        self._combination.show_pair(combination)
        self._stack.setCurrentWidget(self._combination)

    def mark_recipe_prompt_edited(self, edited: bool) -> None:
        self._combination.mark_recipe_prompt_edited(edited)

    def show_folder(self, paths) -> None:
        """Show a whole folder at once: every picture in ``paths``, tiled to fill.

        What a tab about a folder rather than a generation puts in the pane —
        the rewrite a folder's Request card opens. There is no one file on display, so
        nothing here is draggable, openable fullscreen, or scripted; the wall is
        the folder, and the folder is what the settings below it are about — and
        no one of them is what the corner controls would act on, which is why
        they come down here as they do everywhere else.
        """
        self._take_the_pane(None)
        self._image_label.clear()
        self._sheet.show_pictures(paths)
        self._stack.setCurrentWidget(self._sheet)

    def show_message(self, text: str, *, live: bool = False) -> None:
        """Show a plain text message in place of any media.

        For a transient state the idle placeholder would misdescribe — a re-roll
        that's generating but hasn't streamed a preview frame yet.

        ``live`` marks the message as a running generation's, so a double-click
        opens fullscreen over it all the same — the view comes up saying it's
        generating and fills in as the frames arrive.
        """
        self._take_the_pane(None, live=live)
        self._image_label.setText(text)
        self._stack.setCurrentWidget(self._image_label)

    def set_notice(self, text: str | None) -> None:
        """Write ``text`` over the media, or take the notice away (``None``).

        For a pane whose picture no longer answers the settings beside it: the
        media stays on screen — it is still the last thing generated — but is
        plainly marked as not what those settings would now make. Anything that
        changes what's on screen clears it, so a notice can never outlive the
        picture it was about; the owner re-asserts it if it still applies.
        """
        if not text:
            self._notice.hide()
            return
        if not self._notice.isHidden() and self._notice.text() == text:
            return  # already saying exactly this — don't re-raise it mid-typing
        self._notice.setText(text)
        self._notice.show()
        self._place_notice()
        self._raise_notice()

    def _place_notice(self) -> None:
        """Float the message plate in the media's top-left corner.

        The plate stays one line wherever the pane is wide enough for it, and
        wraps only where it isn't: ``adjustSize`` on a wrapping label picks a
        squarish block instead, which turns a one-line message into a slab.
        """
        host = self._media_host
        limit = max(1, host.width() - 2 * _NOTICE_MARGIN)
        self._notice.setWordWrap(False)
        self._notice.adjustSize()
        if self._notice.width() > limit:
            self._notice.setWordWrap(True)
            self._notice.resize(limit, self._notice.heightForWidth(limit))
        self._notice.move(_NOTICE_MARGIN, _NOTICE_MARGIN)

    def _raise_notice(self) -> None:
        """A stacked layout raises the widget it switches to above every sibling
        it has, the notice included."""
        self._notice.raise_()

    def _end_live(self, media: tuple | None) -> None:
        """Stop mirroring a running generation, handing ``media`` — the file it
        landed as, if any — to a fullscreen show opened over its live frames, so
        watching a generation fullscreen ends on the finished image rather than the
        last low-res frame.

        What decides the hand-off is the *view's* own liveness, never this pane's:
        the pane blanks to its placeholder on every gallery rebuild while a run
        streams — including the one that lands it, moments before the saved file
        arrives here — so its own flag is already off by then."""
        self._live, self._live_frame = False, None
        if media is None:
            return
        win = self._following_fullscreen()
        if win is not None:
            win.show_landed(media, self._generation)

    def _following_fullscreen(self):
        """The fullscreen show this pane opened over a running generation and is
        still feeding, or ``None``. One that's been dismissed — or that already
        landed on a file, and so is an ordinary show of it now — follows
        nothing."""
        win = self._fullscreen
        if win is None or not win.is_showing() or not win.is_live():
            return None
        return win

    def clear(self) -> None:
        self.show_message(_PLACEHOLDER)
        self._player.setSource(QUrl())  # release any held video file so it can be deleted

    def is_showing_any(self, paths) -> bool:
        """Whether the file on screen is one of ``paths``, however each is spelled."""
        if self._media is None:
            return False
        return _path_key(self._media[0]) in {_path_key(p) for p in paths}

    def release_media(self, paths) -> None:
        """Let go of ``paths`` — files about to be moved or deleted.

        A loaded video keeps its file open for as long as it's the player's
        source, and Windows refuses to move a file anything holds open, so a
        pane still showing a condemned item is what makes its own deletion
        fail. Panes showing anything else are left exactly as they are: only
        what's about to go is dropped, along with a fullscreen show of it.
        """
        if self._fullscreen is not None:
            self._fullscreen.release_media(paths)
        if self.is_showing_any(paths):
            self.clear()

    def is_showing_video(self) -> bool:
        return self._stack.currentWidget() is self._video

    def media_rect(self) -> QRect:
        """Where the media is actually drawn inside this pane, in its coordinates.

        Media is fitted keeping its aspect ratio, so a portrait image on a wide
        screen leaves surround either side of it — which is what an overlay (the
        slideshows' neighbor stills) needs to know to keep clear of the picture.
        Falls back to the whole media area whenever the drawn size isn't
        knowable yet -- a video whose resolution hasn't arrived, or nothing on
        screen at all -- and never to the timeline along the foot, which is no
        picture: a corner chip laid over it, attached to the video's lower edge.
        """
        drawn = self._drawn_size()
        if drawn is None or drawn.isEmpty():
            return self._media_host.geometry()
        rect = QRect(QPoint(0, 0), drawn)
        # Centered on the media area itself, not on the label: a stacked layout
        # sizes only the page it is showing, so while a video is up the label
        # keeps whatever geometry it last had -- the pane's before the timeline
        # took its rows -- and a rect centered on it sits low by half the timeline.
        rect.moveCenter(self._media_host.geometry().center())
        return rect

    def _drawn_size(self):
        """The media's rendered size — the scaled pixmap or movie frame, or a
        video's resolution fitted to its surface — or ``None`` when unknown."""
        if self.is_showing_video():
            resolution = self._player.metaData().value(QMediaMetaData.Key.Resolution)
            if isinstance(resolution, QSize) and resolution.isValid():
                return resolution.scaled(self._video.size(),
                                         Qt.AspectRatioMode.KeepAspectRatio)
            return None
        if self._movie is not None:
            scaled = self._movie.scaledSize()
            return scaled if scaled.isValid() else None
        pixmap = self._image_label.pixmap()
        return None if pixmap is None or pixmap.isNull() else pixmap.size()

    def player(self) -> QMediaPlayer:
        """The underlying media player — the OSR2 driver follows its position."""
        return self._player

    def set_frozen(self, frozen: bool) -> None:
        """Hold what is moving here, or let it go: a playing video, or an
        animated image's own movie.

        This pane is re-pointed constantly — a click, a landing generation, a
        tab change — and each of those starts the new media playing, so every
        one of them asks :mod:`~origenerator.gui.omnipause` again rather than
        this pane keeping the answer. A still takes it inertly; its advance is
        the owning view's dwell timer, not this pane's.
        """
        if self._movie is not None:
            self._movie.setPaused(frozen)
        if not self.is_showing_video():
            return
        if frozen:
            self._player.pause()
        else:
            self._player.play()

    def media_size(self) -> tuple[int, int] | None:
        """The shown media's own ``(width, height)``, or ``None`` for nothing.

        The MEDIA's shape, not the widget's — what a caller laying out around it
        needs, and the widget's shape is the answer to a different question.
        A video's frame is measured off its player where one is up, and an image
        off the pixmap the label was scaled from rather than the scaled copy.
        """
        if self._movie is not None:
            frame = self._movie.currentPixmap()
            if not frame.isNull():
                return frame.width(), frame.height()
        if self._pixmap is not None and not self._pixmap.isNull():
            return self._pixmap.width(), self._pixmap.height()
        video = getattr(self, "_video_size", None)
        return tuple(video) if video else None

    def set_actions(self, prompt_id: str | None, *, favorite: bool = False,
                    enhance: str | None = None) -> None:
        """Arm the corner controls and the right-click menu over the shown media.

        ``prompt_id`` is the saved generation on screen — the row every act here
        lands on — with the state its corners report beside it: whether it is
        bookmarked, and what its enhance corner has to say
        (:func:`~origenerator.gui.corner_controls.enhance_state`). ``None`` leaves
        the picture inert, which is what everything transient is: a live frame is
        a file that does not exist yet, and a message is not a picture at all.

        Re-armed rather than remembered, because the answers move under the
        picture — a star toggled from the menu, an enhancement landing, a setting
        turned on the Enhance panel — and the owner is what hears about that.
        """
        self._actions_id = prompt_id
        if prompt_id is None:
            self._controls.hide_all()
            return
        self._controls.show_for(favorite=favorite, enhance=enhance)
        self._place_controls()

    def actions_id(self) -> str | None:
        return self._actions_id

    def _on_control(self, action: str) -> None:
        if self._actions_id is not None:
            self.action_triggered.emit(self._actions_id, action)

    def _on_context_menu(self, pos: QPoint) -> None:
        if self._actions_id is not None:
            self.context_requested.emit(self._actions_id, self.mapToGlobal(pos))

    def _place_controls(self) -> None:
        """Put the corner controls back in the corners of the picture.

        Re-run on every resize and every refit rather than once: what the corners
        are pinned to is the media's own rectangle, which moves whenever the pane
        does — and, for a video, again when its resolution finally arrives and the
        pane stops guessing at where the picture is.
        """
        self._controls.place(self.media_rect())

    def resizeEvent(self, event) -> None:
        self._place_controls()
        super().resizeEvent(event)

    def _show_timeline(self, video_path) -> None:
        if self._timeline is None:
            return
        actions = (read_actions(funscript_of(video_path, output_dir=COMFYUI_OUTPUT_DIR))
                   if video_path else [])
        self._timeline.set_actions(actions)
        self._timeline.setVisible(bool(video_path))

    def _hide_timeline(self) -> None:
        if self._timeline is not None:
            self._timeline.set_actions([])
            self._timeline.hide()

    def mousePressEvent(self, event) -> None:
        # The media children are transparent to the mouse, so a press over the
        # image or video lands here. Note the origin for a possible drag of the
        # shown generation; a plain click still falls through to the double-click.
        if self._generation is not None:
            self.drag_out.note_press(event)

    def mouseMoveEvent(self, event) -> None:
        # Drag the shown generation out to a combine slot, but only once the press
        # has travelled far enough to read as a drag rather than a click — so a
        # plain click still just opens fullscreen on the following double-click.
        if self._generation is None or not self.drag_out.should_start(event):
            return
        self._start_drag(self._generation)

    def _start_drag(self, prompt_id: str) -> None:
        """Carry the shown generation out under the shared drag type, so a combine
        slot can read its prompt_id — the same payload a gallery thumbnail drags."""
        self.drag_out.start(
            generation_mime(prompt_id),
            self._drag_picture(),  # what is shown trails the cursor
            prompt_id=prompt_id,
        )

    def _drag_picture(self) -> QPixmap:
        if self.is_showing_video():
            picture = self._video.picture()
            return QPixmap() if picture.isNull() else fit_thumbnail(QPixmap.fromImage(picture))
        return label_thumbnail(self._image_label)

    def set_fullscreen_factory(self, make) -> None:
        """Wire what a double-click here opens: ``make(media, frame)`` returns the
        show it put up -- a slideshow of the folder this pane's generation sits
        in, which only the gallery knows -- or ``None``."""
        self._open_fullscreen_view = make

    def mouseDoubleClickEvent(self, event) -> None:
        self.open_fullscreen()

    def open_fullscreen(self):
        """Pop what's on screen open fullscreen (Escape or a double-click closes it):
        a slideshow of this generation's folder, held on this one.

        That's the current file, or — while a generation is running under this pane —
        its live frames, in a view that goes on following the run from here and swaps
        to the finished file when it lands. A no-op when nothing has wired
        :meth:`set_fullscreen_factory`, or when there's nothing to watch at all:
        the idle placeholder or a plain message."""
        if self._media is None and not self._live:
            return None
        if self._open_fullscreen_view is None:
            return None
        self._fullscreen = self._open_fullscreen_view(self._media, self._live_frame,
                                                      self._generation)
        return self._fullscreen

    def _stop_playback(self) -> None:
        self._player.stop()
        self._player.setSource(QUrl())

    def release_player(self) -> None:
        """Stop the player and point it at nothing, for a pane about to be
        dropped and for the app about to quit (where a still-active real
        backend deadlocks)."""
        self._stop_playback()
        self._player.setVideoOutput(None)
        self._player.setAudioOutput(None)

    def _set_movie(self, movie: QMovie | None, native_size=None) -> None:
        """Attach (or clear) an animated movie, retiring any previous one.

        The movie is parented to this widget so the label's pointer can't dangle
        if Python drops the wrapper before the next paint.

        Every ``show_*`` passes through here, so it is also where the other pages
        are put down — a combination's clip would otherwise keep looping under
        whatever replaced it, and a folder's wall would hold every one of its
        pictures in memory. Both :meth:`show_combination` and
        :meth:`show_folder` call this before laying their own out, so neither
        is undoing itself.
        """
        self._combination.clear()
        self._sheet.clear()
        if self._movie is not None:
            self._movie.stop()
            self._movie.deleteLater()
        self._movie = movie
        self._movie_native = native_size
        if movie is not None:
            movie.setParent(self)
            self._image_label.setMovie(movie)
            self._scale_movie()
            movie.start()
            movie.setPaused(omnipause.frozen())  # an animated still, in a frozen room

    def _scale_movie(self) -> None:
        if self._movie is None or self._movie_native is None or not self._movie_native.isValid():
            return
        target = self._movie_native.scaled(
            self._image_label.size(), Qt.AspectRatioMode.KeepAspectRatio
        )
        if not target.isEmpty():
            self._movie.setScaledSize(target)

    def _rescale(self) -> None:
        if self._movie is not None:
            return
        if self._pixmap is None or self._pixmap.isNull():
            self._image_label.setText("No preview available")
            return
        self._image_label.setPixmap(
            self._pixmap.scaled(
                self._image_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def eventFilter(self, obj, event):
        # Refit the media to the label's *own* size whenever the label resizes, rather
        # than reacting to this widget's resizeEvent. Going fullscreen resizes the
        # label a beat after the widget, so scaling to the widget's not-yet-grown size
        # left the image scaled small and then centered on the full screen — black on
        # all four sides. Keying off the label's resize fits it to the real pane every
        # time that changes, initial fullscreen included.
        if obj is self._image_label and event.type() == QEvent.Type.Resize:
            if self._movie is not None:
                self._scale_movie()
            elif self._pixmap is not None:
                self._rescale()
            if not self._notice.isHidden():
                self._place_notice()
            # The label lags this widget going fullscreen, so anything placed
            # against the media's rect has to re-place when the refit lands.
            self._place_controls()
            self.media_resized.emit()
        elif obj is self._media_host and event.type() == QEvent.Type.Resize:
            if not self._notice.isHidden():
                self._place_notice()
            self._place_controls()
        return super().eventFilter(obj, event)
