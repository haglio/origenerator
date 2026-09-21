"""The picture a fullscreen show fills the screen with, drawn by the players' own engine.

Every other pane in this app draws its media itself -- a fitted pixmap, a
QMovie, a Qt video widget (:mod:`origenerator.gui.preview_widget`).  The show
does not: it hands the file to the same engine Fun Time's players run on
(:class:`player_core.render_player.MpvRenderPlayer`), which decodes on the GPU,
holds a picture for the pace and ends it the way it ends a finished video, and
creeps slowly into a still while it holds the screen.  So a show looks and
behaves the same whether it is this window or one of a session's players
showing the slides, and there is one copy of each of those behaviours rather
than two.

The engine draws into a window the caller owns -- that is how Genau runs it
under a pygame window -- so here it is handed one of this pane's own.  A press
over the picture still arrives as an ordinary Qt event (asked of Windows
itself: the window under the middle of the picture is Qt's), and what is
floated over it -- the stills either side, the panels, the queue -- stacks
against it the way it already had to stack against a video surface
(:mod:`origenerator.gui.media_overlay`).

What the engine cannot show is a generation that has no file yet -- the frames
streaming out of a run in flight, and the wait before the first of them.  Those
are a fitted pixmap on a label, the page this pane turns to when there is no
file to open.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from app_support.funscript import read_actions
from PyQt6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from origenerator.config import COMFYUI_OUTPUT_DIR, project_dir
from origenerator.funscript import funscript_of
from origenerator.gui.funscript_strip import FunscriptStrip
from origenerator.media import MediaType

logger = logging.getLogger(__name__)

# How often the engine is asked where it has got to: whether the item ran out,
# whether anything opened, how big the picture is, and the next step of the
# creep into a still.  Sixty times a second, which is the creep's rate: the
# engine paints its own window, so drawing is not on this clock.
_TICK_MS = 16


class ShowSurface(QWidget):
    """The show's pane: the engine's picture, with a live run's frames over it."""

    # The item on screen ran out -- a video that finished, or a picture whose
    # dwell expired.  One signal for both, because to a show they are one thing.
    media_ended = pyqtSignal()
    # Nothing opened: a file the engine would not play.
    media_unplayable = pyqtSignal()
    # The picture is a different size, so whatever is placed against it moves.
    media_resized = pyqtSignal()

    def __init__(self, parent=None, *, engine=None, muted: bool = False,
                 on_double_click=None, on_press=None):
        super().__init__(parent)
        self._on_double_click = on_double_click
        self._on_press = on_press
        # The on-disk media as (path, media_type), or None while a live run's
        # frames or a message is up.
        self._media: tuple | None = None
        # The newest frame of a run still being made, kept so a resize redraws
        # it rather than dropping to an empty label.
        self._frame: QPixmap | None = None
        self._paused = False
        self._dims: tuple[int, int] = (0, 0)
        # What was said about the item on screen already: the engine goes on
        # reporting an item that ran out for as long as it holds the last
        # frame, and a show told twice pages twice.
        self._said = False
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._media_host = QWidget()
        outer.addWidget(self._media_host, 1)
        self._stack = QStackedLayout(self._media_host)
        self._stack.setContentsMargins(0, 0, 0, 0)

        self._picture = QLabel()
        self._picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._picture.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        # The frame it holds must never set a floor under the window: a label
        # sized by its pixmap keeps the show at the size of the biggest frame
        # it has shown, and a show is whatever size the screen is.
        self._picture.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        # Refit off the label's OWN resize rather than this widget's: going
        # fullscreen resizes the label a beat after the window, and a frame
        # fitted to the not-yet-grown size lands small and centered in black.
        self._picture.installEventFilter(self)
        self._stack.addWidget(self._picture)
        self._engine_pane = _EnginePane(self)
        self._stack.addWidget(self._engine_pane)

        # A scripted clip shows its motion along the lower edge, as the inline
        # pane does for the same file.
        self._strip = FunscriptStrip(self)
        self._strip.hide()
        outer.addWidget(self._strip)

        # The engine is handed a window, so it cannot exist before there is
        # one to hand it.  Until the pane is first shown -- and where the
        # platform has no windows in it at all -- what stands in for the
        # engine keeps whatever it was told, and the real one takes that over
        # the moment it opens.
        self._muted = muted
        self._engine = engine if engine is not None else _NotYetOpened()
        self._engine.set_muted(muted)

        self._tick = QTimer(self)
        self._tick.setInterval(_TICK_MS)
        self._tick.timeout.connect(self._follow_the_engine)
        self._tick.start()

    def open_the_engine(self) -> None:
        """Give the engine the pane's window, and hand it what the stand-in was
        told while there was none.

        A platform with no windows in it -- the suite's -- has nothing for the
        engine to draw into, so the stand-in keeps the pane.
        """
        if not isinstance(self._engine, _NotYetOpened):
            return
        application = QApplication.instance()
        if application is None or application.platformName() == "offscreen":
            return
        _offer_the_copy_beside_the_checkouts()
        from player_core.mpv_player import MpvPlayer  # noqa: PLC0415

        waiting = self._engine
        try:
            engine = MpvPlayer(int(self._engine_pane.winId()),
                               muted=self._muted, loop_file=False)
        except Exception:
            logger.exception("A show could not open the players' engine")
            return
        self._engine = engine
        waiting.replay(engine)

    # --- what the show puts on it -------------------------------------------

    def show_media(self, path, media_type: str) -> None:
        """Open *path* on the engine and keep it there until the next slide."""
        # Kept as it was handed over, not as a string: what is asked for it
        # afterwards -- the clip to drive the device off, the file to let go of
        # -- is asked in the caller's own spelling.
        self._media = (path, media_type)
        self._stack.setCurrentWidget(self._engine_pane)
        self._said = False
        self._dims = (0, 0)
        self._engine.load(Path(path))
        self._engine.set_paused(self._paused)
        self._update_strip(str(path) if media_type == MediaType.VIDEO else None)

    def current_media_path(self) -> str:
        return str(self._media[0]) if self._media else ""

    def set_pace(self, seconds: float) -> None:
        """How long a picture holds the screen, nought holding it indefinitely.

        The engine's own, so it ends a picture the way it ends a finished
        video, and paces the creep into a still by it.
        """
        self._engine.set_pace(seconds)

    def show_frame(self, data: bytes) -> None:
        """A frame of a run still being made: no file, so no engine."""
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        self._take_the_pane()
        self._frame = pixmap
        self._draw_the_frame()

    def show_message(self, text: str) -> None:
        """A line where the picture would be -- the wait before a run's first frame."""
        self._take_the_pane()
        self._picture.setText(text)

    def clear(self) -> None:
        """Nothing on screen at all."""
        self._take_the_pane()

    def _take_the_pane(self) -> None:
        """Turn to the label, with nothing on it and nothing on the engine.

        A run in flight arrives frame after frame, so the engine is only asked
        to let go where it was holding something.
        """
        if self._media is not None:
            self._engine.stop()
        self._media = None
        self._said = False
        self._frame = None
        self._picture.clear()
        self._picture.setText("")
        self._strip.set_actions([])
        self._strip.hide()
        self._stack.setCurrentWidget(self._picture)

    def _draw_the_frame(self) -> None:
        if self._frame is None or self._frame.isNull():
            return
        self._picture.setPixmap(self._frame.scaled(
            self._picture.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def set_paused(self, paused: bool) -> None:
        """Freeze or resume what is on screen, and keep it frozen across slides:
        a step while the room is frozen must land frozen, not play out from
        under the freeze."""
        self._paused = paused
        self._engine.set_paused(paused)

    def set_audio_muted(self, muted: bool) -> None:
        self._muted = muted
        self._engine.set_muted(muted)

    def audio_muted(self) -> bool:
        return self._muted

    def media_rect(self) -> QRect:
        """Where the picture is actually drawn inside this pane.

        Fitted keeping its aspect, so a portrait picture on a wide screen
        leaves surround either side of it -- which is what the stills floated
        beside it have to keep clear of.  The whole pane whenever the engine
        has no size yet: a file still opening, or nothing on it.
        """
        width, height = self._engine.video_dims
        area = self._media_host.geometry()
        if not width or not height or self._media is None:
            return area
        drawn = QSize(width, height).scaled(area.size(), Qt.AspectRatioMode.KeepAspectRatio)
        rect = QRect(QPoint(0, 0), drawn)
        rect.moveCenter(area.center())
        return rect

    def release_media(self, paths) -> None:
        """Let go of any of *paths* on screen, so the file can be moved or
        deleted -- the engine holds an open handle on whatever it is playing."""
        wanted = {str(path) for path in paths}
        if self._media is not None and str(self._media[0]) in wanted:
            self.clear()

    def current_video_path(self):
        """The clip on screen, or None for a picture -- what a funscript lookup
        and the device drive key off."""
        if self._media is not None and self._media[1] == MediaType.VIDEO:
            return self._media[0]
        return None

    def is_showing_video(self) -> bool:
        return self.current_video_path() is not None

    def position(self) -> int:
        """How far into the clip on screen the engine has got, in milliseconds.

        The OSR2 drive follows this the way it follows the media player under
        the config panel's pane -- one name for the question, whichever surface
        is foreground.
        """
        return int(self._engine.position_ms)

    def close_engine(self) -> None:
        """Let the engine go, before the framebuffer it draws into is taken down."""
        self._tick.stop()
        self._engine.close()

    # --- the presses over it -------------------------------------------------

    def mousePressEvent(self, event) -> None:
        """A click on the picture: the show's, which pauses it.

        The engine draws into this widget's own framebuffer rather than into a
        window of its own, so there is no native child here to swallow the
        press -- it arrives like any other Qt event.
        """
        if self._on_press is not None:
            self._on_press()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self._on_double_click is not None:
            self._on_double_click()
        super().mouseDoubleClickEvent(event)

    def eventFilter(self, watched, event):
        if watched is self._picture and event.type() == QEvent.Type.Resize:
            self._draw_the_frame()
        return super().eventFilter(watched, event)

    def _follow_the_engine(self) -> None:
        """Carry the creep on, and pass on whatever the engine has to report."""
        self._engine.push_still()
        dims = self._engine.video_dims
        if dims != self._dims:
            self._dims = dims
            self.media_resized.emit()
        if self._media is None or self._said:
            return
        if self._engine.idle:
            self._said = True
            logger.warning("A show's engine would not open %s", self._media[0])
            self.media_unplayable.emit()
        elif self._engine.eof:
            self._said = True
            self.media_ended.emit()

    def _update_strip(self, video_path) -> None:
        actions = (read_actions(funscript_of(video_path, output_dir=COMFYUI_OUTPUT_DIR))
                   if video_path else [])
        self._strip.set_actions(actions)
        self._strip.setVisible(bool(actions))


def _offer_the_copy_beside_the_checkouts() -> None:
    """Put the copy of the engine's file that sits beside the checkouts first.

    The engine is one ~117 MB file, fetched once into a folder for the whole
    machine, and a player_core checkout keeps its own copy beside it.  The
    engine is found by walking the folders in PATH, and the machine-wide one
    has answered "nothing here" to this app while answering for every other
    process on the same machine -- with the file plainly sitting in it.  So the
    copy beside the checkouts goes in front of it: a second folder, in another
    part of the disk, holding the same engine.
    """
    beside = project_dir("player_core") / "vendor"
    try:
        if not (beside / "libmpv-2.dll").is_file():
            return
    except OSError:
        return
    rest = [entry for entry in os.environ.get("PATH", "").split(os.pathsep)
            if entry != str(beside)]
    os.environ["PATH"] = os.pathsep.join([str(beside), *rest])


class _NotYetOpened:
    """What stands in for the engine until there is a context to build one on.

    Answers nothing is playing, so the pane reports neither an item that ran
    out nor one that would not open, and remembers what it was told so the
    real engine opens on the same slide, pace, freeze and sound.
    """

    eof = False
    idle = False
    video_dims = (0, 0)
    position_ms = 0.0

    def __init__(self) -> None:
        self.file: Path | None = None
        self.pace: float | None = None
        self.paused: bool | None = None
        self.muted: bool | None = None

    def load(self, path: Path) -> None:
        self.file = path

    def set_pace(self, seconds: float) -> None:
        self.pace = seconds

    def set_paused(self, paused: bool) -> None:
        self.paused = paused

    def set_muted(self, muted: bool) -> None:
        self.muted = muted

    def push_still(self) -> None:
        pass

    def stop(self) -> None:
        self.file = None

    def close(self) -> None:
        pass

    def replay(self, engine) -> None:
        engine.set_muted(bool(self.muted))
        if self.pace is not None:
            engine.set_pace(self.pace)
        if self.file is not None:
            engine.load(self.file)
        if self.paused is not None:
            engine.set_paused(self.paused)


class _EnginePane(QWidget):
    """The window the engine draws into.

    Native, because that is what the engine is handed and what it paints; the
    show asks for one the moment the pane is first shown, since a window that
    has never been on screen is not one to hand over.
    """

    def __init__(self, surface):
        super().__init__(surface)
        self._surface = surface
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._surface.open_the_engine()
