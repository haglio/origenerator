"""A live fullscreen slideshow of an auto-generate loop.

Opened by double-clicking the preview while a folder is auto-generating, this
view cycles through everything the loop has produced so far — each finished item
in the order it was generated, plus a trailing slot showing the low-res frames
of the generation currently streaming — instead of staring only at the in-flight
image. It is a dumb display driven by the gallery, which seeds it, feeds it the
loop's live frames and finished items, and reacts to its signals.

The arrow keys are laid out like a Fun Time satellite's controls:

* Left/Right — step back / forward through the rotation (stepping releases a lock).
* Up         — condemn what's on screen: cancel the in-flight generation
               (``cancel_requested``), or mark a finished item weird
               (``weird_requested`` — the gallery trashes it, undoably) and drop
               it from the rotation.
* Down       — lock: hold the current item against the auto-advance (a locked
               video replays); press again to release.

And since a still image gives the OSR2 nothing to follow, the view carries the
OSR2 side of genau — the direct stroke engine, none of the visuals — on genau's
own keys: Space starts/stops the device, J/L speed, 7/9 amplitude, U/O center,
I shape. A standing caption along the top shows the stroke's state, naming
those keys while it's off so they can be found at all. The gallery listens to
:attr:`stroke_active_changed` to keep the funscript driver off the device while
the stroke runs.

Escape closes the view (the loop keeps running); :attr:`closed` fires so the
gallery can forget it.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QApplication
from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

from origenerator.gui.preview_widget import PreviewWidget
from origenerator.slideshow import LIVE, AutoGeneratePlaylist

_GENERATING = "Generating…"
_CAPTION_CSS = (
    "color: white; background: rgba(0, 0, 0, 140);"
    " padding: 4px 10px; border-radius: 4px;"
)


class AutoGenerateView(QWidget):
    closed = pyqtSignal()            # dismissed (Esc / close) — loop keeps running
    cancel_requested = pyqtSignal()  # Up on the live slot: cancel the generation
    weird_requested = pyqtSignal(str)  # Up on a finished item: mark it weird (prompt_id)
    stroke_active_changed = pyqtSignal(bool)  # the stroke engine took/released the device

    def __init__(self, *, player=None, stroke=None, image_dwell_ms=4000, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Auto-generate")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("black"))
        self.setPalette(palette)

        self._playlist = AutoGeneratePlaylist(image_dwell_ms=image_dwell_ms)
        self._live_frame: bytes | None = None  # the in-flight generation's latest frame

        # The stroke driver is injectable so unit tests can watch the calls
        # without touching the broker; built here by default so the gallery's
        # montage seam stays a bare constructor call.
        if stroke is None:
            # Imported here, not at module scope, so tests injecting a stub
            # never pull the device stack in at all.
            from origenerator.gui.osr2_stroke_driver import Osr2StrokeDriver
            stroke = Osr2StrokeDriver(parent=self)
            # Quitting mid-stroke still parks the device and restores genau.
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(stroke.stop)
        self._stroke = stroke

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # Muted like the inline preview — a rotation shouldn't blast each clip's
        # audio — playing videos once so they advance on their end, and never
        # opening a nested fullscreen of its own.
        self._preview = PreviewWidget(player=player, allow_fullscreen=False,
                                      mute_audio=True, loop_videos=False)
        self._preview.video_ended.connect(self._on_video_ended)
        layout.addWidget(self._preview, 1)

        # A translucent position caption floating over the bottom of the media,
        # and the stroke engine's state standing along the top — always shown,
        # since an idle line naming its keys is the only way the OSR2 controls
        # are discoverable at all (nothing else on screen hints they exist).
        self._counter = QLabel(self)
        self._counter.setStyleSheet(_CAPTION_CSS)
        self._counter.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._stroke_caption = QLabel(self)
        self._stroke_caption.setStyleSheet(_CAPTION_CSS)
        self._stroke_caption.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._advance)

        self._update_stroke_caption()
        self._show_current()

    # --- the gallery feeds these as the loop runs --------------------------

    def show_live_frame(self, data: bytes) -> None:
        """Remember the current generation's streamed frame, mirroring it into
        the view while the rotation is showing the live slot."""
        self._live_frame = data
        if self._playlist.on_live():
            self._preview.show_frame(data)

    def add_finished(self, path, media_type: str, prompt_id: str) -> None:
        """Seed one already-finished item into the rotation (oldest first); an
        opening view stays on the live slot while these pour in."""
        self._playlist.add_finished(path, media_type, prompt_id, stay_live=True)
        self._update_counter()

    def note_finished(self, path, media_type: str, prompt_id: str) -> None:
        """The in-flight generation completed: join the rotation as its newest
        finished item. If the live slot was on screen, its low-res frame hands
        over to the finished file right there."""
        was_on_live = self._playlist.on_live()
        self._live_frame = None  # the next launch streams its own frames
        self._playlist.add_finished(path, media_type, prompt_id)
        if was_on_live:
            self._show_current()
        else:
            self._update_counter()

    def set_generating(self, generating: bool) -> None:
        """Add or drop the rotation's live slot as the loop starts or ends."""
        showing_live = self._playlist.on_live()
        self._playlist.set_live(generating)
        if showing_live != self._playlist.on_live():
            self._show_current()
        else:
            self._update_counter()

    # --- playback ----------------------------------------------------------

    def _show_current(self):
        """Render the current slot and arm the dwell timer when it should advance."""
        self._timer.stop()
        current = self._playlist.current()
        if current is None:
            self._preview.show_message("Nothing to show")
        elif current is LIVE:
            if self._live_frame is not None:
                self._preview.show_frame(self._live_frame)
            else:
                self._preview.show_message(_GENERATING)
        else:
            self._preview.show_media(current[0], current[1])
        self._update_counter()
        dwell = self._playlist.dwell_ms()
        if dwell is not None:
            self._timer.start(dwell)

    def _advance(self):
        self._playlist.advance()
        self._show_current()

    def _step(self, delta: int):
        """Manual Left/Right: stepping away releases a lock — the lock holds the
        item it was set on, not wherever the user wanders to."""
        self._playlist.unlock()
        if delta > 0:
            self._playlist.advance()
        else:
            self._playlist.back()
        self._show_current()

    def _condemn(self):
        """Up: cancel the in-flight generation, or mark the finished item on
        screen weird — out of the rotation, and the gallery's to trash."""
        self._playlist.unlock()
        current = self._playlist.current()
        if current is None:
            return
        if current is LIVE:
            self._live_frame = None  # the replacement launch streams fresh frames
            self.cancel_requested.emit()
            self._show_current()  # "Generating…" until those arrive
            return
        self._playlist.remove_current()
        if self._playlist.count == 0:
            # Nothing left to rotate and no loop running. Close before the trash
            # below, so the preview has released the file being condemned.
            self.close()
        else:
            self._show_current()  # off the condemned media before it's trashed
        self.weird_requested.emit(current[2])

    def _toggle_lock(self):
        """Down: hold the current item against the auto-advance, or release it."""
        if self._playlist.toggle_lock():
            self._timer.stop()
            self._update_counter()
        else:
            self._show_current()  # re-arms the dwell

    def _on_video_ended(self):
        """A finished clip played through: replay it while locked, else move on."""
        if self._playlist.locked:
            self._show_current()
        else:
            self._advance()

    # --- the OSR2 stroke (genau's keys, none of its visuals) ---------------

    def _toggle_stroke(self):
        active = self._stroke.toggle()
        self.stroke_active_changed.emit(active)
        self._update_stroke_caption()

    def _stroke_adjust(self, action):
        action()
        self._update_stroke_caption()

    def _update_stroke_caption(self):
        """The standing OSR2 line along the top: the stroke's state, plus its
        keys while it's off — the invitation to press Space."""
        text = self._stroke.status_text()
        if not self._stroke.active:
            text += "   ·   Space drives · J/L speed · 7/9 travel · U/O center · I shape"
        self._stroke_caption.setText(text)
        self._reposition_stroke_caption()
        self._stroke_caption.raise_()

    # --- captions ----------------------------------------------------------

    def _update_counter(self):
        if self._playlist.count == 0:
            self._counter.hide()  # an emptied rotation has no position to report
            return
        self._counter.show()
        text = f"{self._playlist.index + 1} / {self._playlist.count}"
        if self._playlist.on_live():
            text += "  ·  generating"
        if self._playlist.locked:
            text += "  ·  locked"
        self._counter.setText(text)
        self._reposition_counter()

    def _reposition_counter(self):
        self._counter.adjustSize()
        x = (self.width() - self._counter.width()) // 2
        y = self.height() - self._counter.height() - 24
        self._counter.move(max(0, x), max(0, y))

    def _reposition_stroke_caption(self):
        self._stroke_caption.adjustSize()
        x = (self.width() - self._stroke_caption.width()) // 2
        self._stroke_caption.move(max(0, x), 24)

    # --- keys & lifecycle --------------------------------------------------

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close()
        elif key == Qt.Key.Key_Left:
            self._step(-1)
        elif key == Qt.Key.Key_Right:
            self._step(1)
        elif key == Qt.Key.Key_Up:
            self._condemn()
        elif key == Qt.Key.Key_Down:
            self._toggle_lock()
        elif key == Qt.Key.Key_Space:
            self._toggle_stroke()
        elif key == Qt.Key.Key_J:
            self._stroke_adjust(lambda: self._stroke.adjust_speed(-5))
        elif key == Qt.Key.Key_L:
            self._stroke_adjust(lambda: self._stroke.adjust_speed(5))
        elif key == Qt.Key.Key_7:
            self._stroke_adjust(lambda: self._stroke.adjust_amplitude(-10))
        elif key == Qt.Key.Key_9:
            self._stroke_adjust(lambda: self._stroke.adjust_amplitude(10))
        elif key == Qt.Key.Key_U:
            self._stroke_adjust(lambda: self._stroke.adjust_center(-5))
        elif key == Qt.Key.Key_O:
            self._stroke_adjust(lambda: self._stroke.adjust_center(5))
        elif key == Qt.Key.Key_I:
            self._stroke_adjust(self._stroke.cycle_shape)
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_counter()
        if self._stroke_caption.isVisible():
            self._reposition_stroke_caption()

    def closeEvent(self, event):
        self._timer.stop()
        if self._stroke.active:
            self._stroke.stop()  # never leave the device running unattended
            self.stroke_active_changed.emit(False)
        self._preview.clear()  # release any held video file so it can be deleted
        self.closed.emit()
        super().closeEvent(event)
