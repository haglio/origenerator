"""A preview pane that shows an image or video for the selected generation.

The gallery hands it a resolved ``(path, media_type)`` and it does the rest:
static images are scaled to fit (and rescaled on resize), animated images
(animated WebP/GIF) loop via ``QMovie``, and videos auto-play on a loop — muted by
default, so selecting one gives an immediate moving preview without stealing audio,
while the fullscreen slideshow opts in to sound.

A still can also be drawn part-way into itself (:meth:`PreviewWidget.set_zoom`),
which is how the fullscreen show creeps into each picture while it holds the
screen; every other pane leaves that at the whole picture.

A pane the owner has armed (:meth:`PreviewWidget.set_actions`) also carries the
three controls a gallery thumbnail of the same generation wears in its corners,
and offers the same right-click menu over the picture — because it IS the same
generation, and where you are standing should not change what you can do to it.
Unarmed — a live frame, a message, a slideshow's own inner pane — the picture is
inert.
"""

from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import (
    QEvent,
    QPoint,
    QRect,
    QRectF,
    QSize,
    Qt,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import QDrag, QImageReader, QMovie, QPainter, QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaMetaData, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from origenerator.config import COMFYUI_OUTPUT_DIR
from origenerator.funscript import funscript_of, read_actions
from origenerator.gui.combination_view import CombinationView
from origenerator.gui.contact_sheet import ContactSheet
from origenerator.gui.corner_controls import CornerControls
from origenerator.gui.drag_thumbnail import (
    fit_thumbnail,
    label_thumbnail,
    set_drag_thumbnail,
)
from origenerator.gui.funscript_strip import FunscriptStrip
from origenerator.gui.generation_drag import generation_mime
from origenerator.ken_burns import ZOOM_SPAN, crop_box

_PLACEHOLDER = "Select a generation to preview"

# The notice laid over media that no longer matches the settings beside it: a
# plate carrying the message, over a dimmed picture (see set_notice).
_NOTICE_DIM = "background: rgba(0, 0, 0, 130);"
_NOTICE_PLATE = ("color: white; background: rgba(0, 0, 0, 200);"
                 " padding: 6px 12px; border-radius: 4px;")
_NOTICE_MARGIN = 12  # how far the plate floats from the media's top-left corner


def _path_key(path) -> str:
    """One comparable form for a file path, so two spellings of the same file —
    a ``Path`` against a string, or Windows' case-blind pair — match."""
    return os.path.normcase(os.path.abspath(str(path)))


class PreviewWidget(QWidget):
    video_ended = pyqtSignal()  # a non-looping video reached its end (slideshow use)
    # This backend cannot open the clip at all — a different thing from ending,
    # and the one a show has to be told about (see _on_media_status).
    video_unplayable = pyqtSignal()
    media_resized = pyqtSignal()  # the media was refitted (an overlay must re-place)
    drag_started = pyqtSignal(str)  # the shown generation began dragging out (prompt_id)
    drag_ended = pyqtSignal()       # that drag finished (dropped or canceled)
    action_triggered = pyqtSignal(str, str)  # a corner control: prompt_id, action
    context_requested = pyqtSignal(str, QPoint)  # right-clicked: prompt_id, global pos

    def __init__(self, parent=None, *, player: QMediaPlayer | None = None,
                 loop_videos: bool = True, allow_fullscreen: bool = True,
                 show_funscript_strip: bool = False, mute_audio: bool = True,
                 on_double_click=None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._movie: QMovie | None = None
        self._movie_native = None
        # The current on-disk media as (path, media_type), or None while showing a
        # placeholder or a live frame — what a double-click pops open fullscreen.
        self._media: tuple | None = None
        # Whether a generation is running behind this pane — its streamed frames, or
        # the wait before the first one arrives — and that latest frame. A double-click
        # opens fullscreen over these too, and the view opened that way keeps following
        # from here: later frames, then the finished file. Without it, watching a
        # generation had to wait for it to land.
        self._live = False
        self._live_frame: bytes | None = None
        self._allow_fullscreen = allow_fullscreen  # a slideshow's own preview opts out
        self._fullscreen: QWidget | None = None    # the open fullscreen window, kept alive here
        # What builds that window. The gallery sets it, because what a double-click
        # opens is a slideshow of the folder behind this pane — which this pane
        # knows nothing about. Unset, a double-click opens nothing.
        self._open_fullscreen_view = None
        # A double-click that doesn't open fullscreen (this preview opted out, or has
        # nothing to open) runs this instead — the slideshow uses it so a second
        # double-click dismisses it.
        self._on_double_click = on_double_click
        # The shown generation's prompt_id when the owner has armed the preview to be
        # dragged out onto a combine slot (like a gallery thumbnail), else None; a
        # transient view (a live frame, a message) disarms it. _drag_origin holds the
        # left-press point while measuring whether a move is a drag or just a click.
        self._draggable_id: str | None = None
        self._drag_origin: QPoint | None = None
        # How far into the still this pane is drawn — the fullscreen show's slow
        # push (see set_zoom). 1.0, the whole picture, for every other pane:
        # nothing but a show ever moves it, and a pane that is never pushed into
        # keeps the plain fit it always had rather than going through the
        # painter below.
        self._zoom = 1.0
        self._pushing = False
        # What the push is drawn FROM and AT, prepared once per picture: see
        # _ready_the_push. The key is what they were prepared for, so a new
        # picture or a resized pane rebuilds them and nothing else does.
        self._push_key: tuple | None = None
        self._push_source: QPixmap | None = None
        self._push_size = QSize()

        # The shown generation's prompt_id when the owner has armed the corner
        # controls and the right-click menu over it, else None. Armed separately
        # from the drag because they answer different questions: a drag needs
        # something to carry, and these need a row to act on.
        self._actions_id: str | None = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # Right-click the picture for the same menu a gallery thumbnail of it gives.
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

        # The media (image/video) fills the pane; an optional funscript strip rides
        # along its bottom edge, so a scripted clip shows its stroke motion at a glance.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        media_host = QWidget()
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
        # Let mouse events fall through to this widget, so a press/drag/double-click
        # over the media is handled here (drag-out, open-fullscreen) rather than being
        # swallowed by the label or the video surface.
        self._image_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._stack.addWidget(self._image_label)

        self._video = QVideoWidget()
        self._video.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._audio = QAudioOutput(self)
        self._audio.setMuted(mute_audio)
        # The player is injectable so unit tests can drive playback intent
        # without spinning up the real (WMF) backend, which deadlocks at exit.
        # A hosting session's OmniPause over this pane, held rather than edged:
        # the pane is re-pointed constantly and each new media starts playing.
        self._playback_paused = False
        self._player = player if player is not None else QMediaPlayer(self)
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video)
        # Infinite for the info-pane preview (an immediate moving thumbnail); a
        # slideshow plays each clip once and advances when it ends.
        self._player.setLoops(
            QMediaPlayer.Loops.Infinite if loop_videos else QMediaPlayer.Loops.Once
        )
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(self._on_media_error)

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

        # The notice's two pieces, over the media host so they cover the picture
        # and leave the funscript strip below it clear. Two, because a video
        # surface is a native window that a plain sibling cannot paint over: the
        # dim is an ordinary sibling, so it blends into a still or an animation
        # and simply stays under a clip, while the message itself is native and
        # rides over either. Both hidden until set_notice says otherwise.
        self._media_host = media_host
        self._notice_dim = QLabel(media_host)
        self._notice_dim.setStyleSheet(_NOTICE_DIM)
        self._notice_dim.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._notice_dim.hide()
        self._notice = QLabel(media_host)
        self._notice.setStyleSheet(_NOTICE_PLATE)
        self._notice.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._notice.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._notice.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self._notice.hide()

        # The same three corner controls a gallery thumbnail of this generation
        # wears, in the same three corners, so the acts are where they were learned
        # whichever surface the picture is on. Native, because a video plays on a
        # surface an ordinary sibling cannot paint over — the notice above it is
        # native for the very same reason. They stay hidden until the owner arms
        # them (:meth:`set_actions`): a live frame or a message is no row to act on.
        self._controls = CornerControls(self, native=True)
        self._controls.triggered.connect(self._on_control)

        # Opt-in funscript heatmap along the bottom edge (the info-pane and fullscreen
        # previews use it); hidden until a scripted video is shown.
        self._strip = FunscriptStrip() if show_funscript_strip else None
        if self._strip is not None:
            outer.addWidget(self._strip)
            self._strip.hide()

        # The real WMF backend can deadlock during Qt/Python shutdown if a player
        # is still active, so release it before the app quits. Injected test
        # players don't touch the backend and don't need (or want) this hook.
        if player is None:
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self._release)

    def _take_the_pane(self, media, *, stop_player: bool = True,
                       keep_notice: bool = False,
                       live: bool = False, live_frame: bytes | None = None) -> None:
        """Put down everything the pane is holding, ready for new content.

        This is what showing anything means, said once: the movie and the still
        are retired and the other pages put down (:meth:`_set_movie` clears the
        combination and the wall), the stroke strip drops, the playback stops,
        the notice and the corner controls — both of which are about the picture
        being replaced, and so can no more outlive it than it can — go, and the
        pane records what it is about to be showing (``media``, or ``None`` for
        anything that is not a file on disk) and hands a fullscreen view opened
        over a running generation the file it landed as.

        The drag follows ``media`` rather than a switch of its own: a view with
        no file on disk has nothing to drag out, and a view that has one leaves
        the arming to its owner, since only the owner knows which generation the
        file belongs to.

        The two switches are the deliberate exceptions, one caller each.
        ``stop_player`` — a clip does not stop the player it is about to hand a
        new source to. ``keep_notice`` — frames of an enhancement of the picture
        on screen are the coming state of that picture, so what a notice says
        about it is just as true of them.
        """
        self._set_movie(None)
        self._pixmap = None
        self._hide_strip()
        if stop_player:
            self._player.stop()
        if not keep_notice:
            self.set_notice(None)
        self.set_actions(None)
        self._media = media
        self._end_live(media)
        if live:
            self._live, self._live_frame = True, live_frame
        if media is None:
            self._draggable_id = None

    def show_media(self, path, media_type: str) -> None:
        """Display ``path`` as an image or video per ``media_type``."""
        if media_type == "video":
            self.show_video(path)
        else:
            self.show_image(path)

    def show_image(self, path) -> None:
        self._take_the_pane((path, "image"))
        reader = QImageReader(str(path))
        if reader.supportsAnimation() and reader.imageCount() > 1:
            self._set_movie(QMovie(str(path)), reader.size())
        else:
            self._pixmap = QPixmap(str(path))
            self._rescale()
        self._stack.setCurrentWidget(self._image_label)

    def show_video(self, path) -> None:
        self._take_the_pane((path, "video"), stop_player=False)
        self._image_label.clear()
        self._player.setSource(QUrl.fromLocalFile(str(Path(path))))
        self._stack.setCurrentWidget(self._video)
        self._player.play()
        if self._playback_paused:
            self._player.pause()  # a clip loaded into a frozen room opens held
        self._update_strip(path)  # …and wears its stroke script, if it has one

    def show_frame(self, data: bytes, *, keep_notice: bool = False) -> None:
        """Display one in-progress preview frame from raw encoded image bytes.

        ComfyUI streams live previews as encoded images over the websocket
        rather than writing a file, so this loads straight from memory. Bytes
        that don't decode (a truncated frame) are ignored, leaving the current
        view untouched — which is why the decode happens before the pane is put
        down rather than after.

        ``keep_notice`` marks the frames as the coming state of the picture
        already on display — an enhancement of it — rather than a run of the
        settings beside it. Whatever a notice says about that picture is just as
        true of the version being made, so it stays where it is: cleared by each
        frame and re-asserted by each keystroke, it flickers at the rate the run
        streams while the form is being typed in.
        """
        pixmap = QPixmap()
        if not pixmap.loadFromData(data) or pixmap.isNull():
            return
        self._take_the_pane(None, keep_notice=keep_notice, live=True, live_frame=data)
        self._pixmap = pixmap
        self._rescale()
        self._stack.setCurrentWidget(self._image_label)
        self._raise_notice()  # a kept notice, back over the frame that just landed
        win = self._following_fullscreen()
        if win is not None:
            win.show_frame(data)  # keep a view watching this generation up to date

    def show_combination(self, image_path, video_path) -> None:
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
        self._combination.show_pair(image_path, video_path)
        self._stack.setCurrentWidget(self._combination)

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
        """Dim the media behind ``text``, or take the notice away (``None``).

        For a pane whose picture no longer answers the settings beside it: the
        media stays on screen — it is still the last thing generated — but is
        plainly marked as not what those settings would now make. Anything that
        changes what's on screen clears it, so a notice can never outlive the
        picture it was about; the owner re-asserts it if it still applies.
        """
        if not text:
            self._notice.hide()
            self._notice_dim.hide()
            return
        if not self._notice.isHidden() and self._notice.text() == text:
            return  # already saying exactly this — don't re-raise it mid-typing
        self._notice.setText(text)
        self._notice_dim.show()
        self._notice.show()
        self._place_notice()
        self._raise_notice()

    def _place_notice(self) -> None:
        """Spread the dim over the whole media area and float the message plate
        in its top-left corner.

        The plate stays one line wherever the pane is wide enough for it, and
        wraps only where it isn't: ``adjustSize`` on a wrapping label picks a
        squarish block instead, which turns a one-line message into a slab.
        """
        host = self._media_host
        self._notice_dim.setGeometry(host.rect())
        limit = max(1, host.width() - 2 * _NOTICE_MARGIN)
        self._notice.setWordWrap(False)
        self._notice.adjustSize()
        if self._notice.width() > limit:
            self._notice.setWordWrap(True)
            self._notice.resize(limit, self._notice.heightForWidth(limit))
        self._notice.move(_NOTICE_MARGIN, _NOTICE_MARGIN)

    def _raise_notice(self) -> None:
        """Put a showing notice back on top of the media — over a video surface,
        which is a native window a plain sibling cannot paint over, and over a
        picture that has just landed under it: a stacked layout raises the widget
        it switches to above every sibling it has.

        A no-op when no notice is up, so anything putting a new view in the pane
        can call it without asking first.
        """
        if self._notice.isHidden():
            return
        self._notice_dim.raise_()
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
            win.show_landed(media)

    def _following_fullscreen(self):
        """The fullscreen show this pane opened over a running generation and is
        still feeding, or ``None``. One that's been dismissed — or that already
        landed on a file, and so is an ordinary show of it now — follows
        nothing."""
        win = self._fullscreen
        if win is None or not win.isVisible() or not win.is_live():
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
        Falls back to the whole pane whenever the drawn size isn't knowable yet:
        a video whose resolution hasn't arrived, or nothing on screen at all.
        """
        drawn = self._drawn_size()
        if drawn is None or drawn.isEmpty():
            return self.rect()
        rect = QRect(QPoint(0, 0), drawn)
        rect.moveCenter(self._image_label.mapTo(self, self._image_label.rect().center()))
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

    def set_zoom(self, zoom: float) -> None:
        """Draw the still *zoom* deep into itself — the show's Ken Burns push.

        Every frame of the push is drawn at ONE size, the size the whole picture
        was fitted to, and what moves is a real-valued window sampled out of the
        picture (:func:`~origenerator.ken_burns.crop_box`). Both halves of that
        matter and each was learned the hard way:

        * a frame whose size changes by a pixel is re-centered by the label, so
          the picture hops sideways — several times a second, in whichever
          direction the fit happened to round;
        * a window snapped to whole pixels does not creep at all at this speed,
          it holds and then steps, and its two axes step at different moments.

        Together those made a still picture twitch rather than drift. Drawn
        through a painter at a fixed size from a real-valued window, the
        sampling grid slides between source pixels and the motion is continuous
        — and :meth:`media_rect` is genuinely constant, which is what the
        neighbor stills and the HUD map are placed against.

        Stills only. An animated image is already moving and a video is its own
        motion, so both take the number inertly — as does every pane but a
        show's, none of which ever calls this.
        """
        zoom = max(1.0, float(zoom))
        was_pushing, self._pushing = self._pushing, True
        if zoom == self._zoom and was_pushing:
            return
        self._zoom = zoom
        self._rescale()

    def set_audio_muted(self, muted: bool) -> None:
        """Silence (or voice) this pane's playback outright."""
        self._audio.setMuted(muted)

    def audio_muted(self) -> bool:
        return self._audio.isMuted()

    def set_playback_paused(self, paused: bool) -> None:
        """Freeze or resume whatever is moving here (a hosted session's
        OmniPause): a playing video, or an animated image's own movie.

        Remembered rather than only applied, because this pane is re-pointed
        constantly — a click, a landing generation, a tab change — and each of
        those starts the new media playing.  A pane frozen once has to stay
        frozen through every one of them until the room resumes.  A still takes
        the flag inertly; its advance is the owning view's dwell timer, not
        this pane's.
        """
        self._playback_paused = paused
        self._apply_playback_pause()

    def _apply_playback_pause(self) -> None:
        """Hold what is on screen now, if the freeze is on."""
        if self._movie is not None:
            self._movie.setPaused(self._playback_paused)
        if not self.is_showing_video():
            return
        if self._playback_paused:
            self._player.pause()
        else:
            self._player.play()

    def current_media_path(self) -> str:
        """The file on screen, or "" while showing a placeholder or live frame."""
        return str(self._media[0]) if self._media is not None else ""

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

    def set_actions(self, prompt_id: str | None, *, starred: bool = False,
                    enhance: str | None = None) -> None:
        """Arm the corner controls and the right-click menu over the shown media.

        ``prompt_id`` is the saved generation on screen — the row every act here
        lands on — with the state its corners report beside it: whether it is
        bookmarked, and what its enhance corner has to say
        (:func:`~origenerator.gui.corner_controls.enhance_state`). ``None`` leaves
        the picture inert, which is what everything transient is: a live frame is
        a file that does not exist yet, and a message is not a picture at all.

        Re-armed rather than remembered, because the answers move under the
        picture — a star toggled from the menu, an enhancement landing, a knob
        turned on the Enhance panel — and the owner is what hears about that.
        """
        self._actions_id = prompt_id
        if prompt_id is None:
            self._controls.hide_all()
            return
        self._controls.show_for(starred=starred, enhance=enhance)
        self._place_controls()

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

    def set_draggable_id(self, prompt_id: str | None) -> None:
        """Arm (or disarm) dragging the shown media out as a generation.

        The owner passes the displayed generation's prompt_id so the preview can be
        dragged onto a combine slot exactly like a gallery thumbnail; ``None`` leaves
        it undraggable. A transient view (a live frame or a message) disarms itself,
        so this only ever needs re-arming when a saved generation is shown."""
        self._draggable_id = prompt_id

    def _update_strip(self, video_path) -> None:
        """Aim the funscript strip at ``video_path``'s script, showing it only when
        one exists — so the strip's presence is itself the "this clip has a script"
        cue (the same script the OSR2 drive would read for this video)."""
        if self._strip is None:
            return
        actions = (read_actions(funscript_of(video_path, output_dir=COMFYUI_OUTPUT_DIR))
                   if video_path else None)
        self._strip.set_actions(actions or [])
        self._strip.setVisible(bool(actions))

    def _hide_strip(self) -> None:
        """Drop the strip whenever the pane isn't showing a video."""
        if self._strip is not None:
            self._strip.set_actions([])
            self._strip.hide()

    def current_video_path(self):
        """The on-disk video currently shown, or ``None`` for an image/placeholder/
        live frame — what a funscript lookup and device driving key off."""
        if self._media is not None and self._media[1] == "video":
            return self._media[0]
        return None

    def mousePressEvent(self, event) -> None:
        # The media children are transparent to the mouse, so a press over the
        # image or video lands here. Note the origin for a possible drag of the
        # shown generation; a plain click still falls through to the double-click.
        if event.button() == Qt.MouseButton.LeftButton and self._draggable_id is not None:
            self._drag_origin = event.position().toPoint()

    def mouseMoveEvent(self, event) -> None:
        # Drag the shown generation out to a combine slot, but only once the press
        # has travelled far enough to read as a drag rather than a click — so a
        # plain click still just opens fullscreen on the following double-click.
        if self._drag_origin is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if self._draggable_id is None:
            return
        moved = (event.position().toPoint() - self._drag_origin).manhattanLength()
        if moved < QApplication.startDragDistance():
            return
        prompt_id = self._draggable_id
        self._drag_origin = None
        self._start_drag(prompt_id)

    def _start_drag(self, prompt_id: str) -> None:
        """Carry the shown generation out under the shared drag type, so a combine
        slot can read its prompt_id — the same payload a gallery thumbnail drags."""
        drag = QDrag(self)
        drag.setMimeData(generation_mime(prompt_id))
        set_drag_thumbnail(drag, self._drag_picture())  # what is shown trails the cursor
        # Announce the drag so a combine slot can light the moment it starts —
        # QDrag.exec is modal, so the highlight is on for the whole gesture.
        self.drag_started.emit(prompt_id)
        try:
            drag.exec(Qt.DropAction.CopyAction)
        finally:
            self.drag_ended.emit()

    def _drag_picture(self) -> QPixmap:
        """The thumbnail that trails the cursor while this pane's media is dragged.

        Everything the pane can show has a picture, but not in the same place: a
        still is the label's pixmap, an animated image is the frame its movie is
        on, and a video is on the player's own surface with no pixmap anywhere —
        the last frame it handed its sink is the only handle on it. Reaching
        only for the label's pixmap is why a dragged video used to trail nothing.
        """
        if self.is_showing_video():
            sink = self._video.videoSink()
            frame = sink.videoFrame() if sink is not None else None
            if frame is None or not frame.isValid():
                return QPixmap()
            return fit_thumbnail(QPixmap.fromImage(frame.toImage()))
        return label_thumbnail(self._image_label)

    def set_fullscreen_factory(self, make) -> None:
        """Wire what a double-click here opens: ``make(media, frame)`` returns a
        shown fullscreen window, or ``None``.

        The gallery supplies it, because the window is a slideshow of the folder
        this pane's generation sits in and the pane has no idea what that folder
        holds. Left unset — a bare preview in a test — a double-click opens
        nothing.
        """
        self._open_fullscreen_view = make

    def mouseDoubleClickEvent(self, event) -> None:
        # Open fullscreen, or — when this preview can't (it opted out, e.g. the
        # slideshow's own inner preview) — run the double-click callback, so a
        # second double-click that lands here closes the slideshow.
        if self.open_fullscreen() is None and self._on_double_click is not None:
            self._on_double_click()

    def open_fullscreen(self):
        """Pop what's on screen open fullscreen (Escape or a double-click closes it):
        a slideshow of this generation's folder, held on this one.

        That's the current file, or — while a generation is running behind this pane —
        its live frames, in a view that goes on following the run from here and swaps
        to the finished file when it lands. A no-op when this preview opted out (a
        slideshow's own inner preview), when nothing has wired
        :meth:`set_fullscreen_factory`, or when there's nothing to watch at all:
        the idle placeholder or a plain message."""
        if not self._allow_fullscreen or (self._media is None and not self._live):
            return None
        if self._open_fullscreen_view is None:
            return None
        self._fullscreen = self._open_fullscreen_view(self._media, self._live_frame)
        return self._fullscreen

    def _on_media_status(self, status) -> None:
        """Report a finished video so a slideshow can advance — and separately,
        one this backend cannot open at all.

        The second is not a kind of ending, and treating it as one is what left
        a show on a black rectangle: a clip with no codec here never reports
        EndOfMedia, and a video carries no dwell timer (its own length is its
        dwell), so nothing was ever going to move the show off it again.  A
        browse of the whole library is exactly where such a clip turns up.
        """
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.video_ended.emit()
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self.video_unplayable.emit()

    def _on_media_error(self, error, _message: str = "") -> None:
        """Same report, from the other direction: the backend can raise the
        error without ever moving the status to InvalidMedia."""
        if error != QMediaPlayer.Error.NoError and self.is_showing_video():
            self.video_unplayable.emit()

    def _release(self) -> None:
        """Tear down the media pipeline so shutdown can't deadlock the backend."""
        self._player.stop()
        self._player.setSource(QUrl())

    def _set_movie(self, movie: QMovie | None, native_size=None) -> None:
        """Attach (or clear) an animated movie, retiring any previous one.

        The movie is parented to this widget so the label's pointer can't dangle
        if Python drops the wrapper before the next paint.

        Every ``show_*`` passes through here, so it is also where the other pages
        are put down — a combination's clip would otherwise keep looping behind
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
            movie.setPaused(self._playback_paused)  # an animated still, in a frozen room

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
        if self._pushing:
            self._image_label.setPixmap(self._push_frame())
            return
        self._image_label.setPixmap(
            self._pixmap.scaled(
                self._image_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    # --- the push, drawn ----------------------------------------------------

    def _ready_the_push(self) -> None:
        """Fix the size every frame of this picture is drawn at, and prepare the
        picture the frames are sampled from. Once per picture, not per frame.

        The frames are drawn at the size the WHOLE picture fits the pane at, so
        the drawn rect is the same at every point of the push — see
        :meth:`set_zoom` for what a changing one does.

        The source is shrunk once, with the good filter, to the resolution the
        deepest point of the push actually needs. That leaves every frame a
        near-1:1 draw. Sampling a much larger picture afresh each frame would
        instead minify it thirty times a second with a grid that has crawled a
        fraction of a pixel since the last one, and a fine texture under that
        shimmers. A picture already smaller than that is left alone rather than
        blown up to meet it.
        """
        key = (self._pixmap.cacheKey(),
               self._image_label.width(), self._image_label.height())
        if key == self._push_key:
            return
        self._push_key = key
        self._push_size = self._pixmap.size().scaled(
            self._image_label.size(), Qt.AspectRatioMode.KeepAspectRatio)
        deepest = QSize(max(1, round(self._push_size.width() * ZOOM_SPAN)),
                        max(1, round(self._push_size.height() * ZOOM_SPAN)))
        oversized = (self._pixmap.width() > deepest.width()
                     or self._pixmap.height() > deepest.height())
        self._push_source = (
            self._pixmap.scaled(deepest, Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
            if oversized else self._pixmap
        )

    def _push_frame(self) -> QPixmap:
        """This picture at the push's current depth, drawn at the fixed size."""
        self._ready_the_push()
        if self._push_size.isEmpty() or self._push_source.isNull():
            return QPixmap()
        frame = QPixmap(self._push_size)
        frame.fill(Qt.GlobalColor.transparent)
        painter = QPainter(frame)
        # The one render hint that matters here: without it the window's
        # fractional offset is thrown away and the push snaps pixel to pixel,
        # which is the twitch this whole approach exists to remove.
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(
            QRectF(0, 0, self._push_size.width(), self._push_size.height()),
            self._push_source,
            QRectF(*crop_box(self._push_source.width(),
                             self._push_source.height(), self._zoom)),
        )
        painter.end()
        return frame

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
        return super().eventFilter(obj, event)
