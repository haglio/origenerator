import time
from pathlib import Path

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QApplication
from PyQt6.QtGui import QPixmap, QDrag, QCursor
from PyQt6.QtCore import Qt, QPoint, QRect, QSize, QEvent, QTimer, pyqtSignal

from origenerator.gui.corner_controls import (
    CHIP_CSS, CORNER_GAP, CORNER_INSET, CORNER_SIZE, CornerControls,
)
from origenerator.gui.drag_thumbnail import label_thumbnail, set_drag_thumbnail
from origenerator.gui.generation_drag import generation_mime
from origenerator.gui.inflight import EnhancingRun
from origenerator.gui.looping_preview import looping_movie
from origenerator.gui.media_badge import MediaBadge
from origenerator.gui.progress_caption import ProgressCaption
from origenerator.gui.stage_scrim import StageScrim
from origenerator.timing import progress_status_label

_IMAGE_SIZE = QSize(172, 160)  # the thumbnail image area, inside the 180x200 tile
_BORDER_PX = 2                 # the image's own edge, which the overlays stay inside
_BAR_HEIGHT = 26               # the enhancement's bar, along the picture's foot
_TICK_MS = 1000                # how often the bar's clock re-reads itself

# Hover-revealed corner action buttons (an i2v tile's per-seed re-rolls, a review
# shelf's keep/reject): the same translucent chip the corner controls sit on, blue
# on hover, laid along the tile's top-left edge — the one edge the three corner
# controls leave alone.
_CORNER_BUTTON_CSS = (
    CHIP_CSS + "QPushButton:hover { background: rgba(48,128,224,0.9); }"
)

# A selected thumbnail lightens its whole tile — behind both the image and the
# caption — the way a file browser highlights a picked item. Two things make
# the fill actually show:
#   * WA_StyledBackground, or a plain QWidget subclass paints no stylesheet
#     background at all; and
#   * transparent child labels, or the app's global `QWidget { background-color }`
#     paints them opaque and the fill only peeks through the 4px margin as a
#     frame (which is what an earlier attempt did).
# The image also lightens its resting border a touch when selected.
_SELECTED_BG = "#3a3a3a"
_SELECTED_TILE_CSS = f"#thumbnailTile {{ background-color: {_SELECTED_BG}; border-radius: 4px; }}"
_BORDER_UNSELECTED = "2px solid #3f3f3f"
_BORDER_SELECTED = "2px solid #8a8a8a"


class ThumbnailWidget(QWidget):
    clicked = pyqtSignal(str)  # prompt_id
    double_clicked = pyqtSignal(str)  # prompt_id — an "open" gesture
    context_requested = pyqtSignal(str, QPoint)  # prompt_id, global position
    drag_started = pyqtSignal(str)  # prompt_id — a drag of this tile began
    drag_ended = pyqtSignal()       # that drag finished (dropped or canceled)
    corner_action_triggered = pyqtSignal(str, str)  # prompt_id, action_id
    control_triggered = pyqtSignal(str, str)  # prompt_id, corner_controls.STAR/TRASH/ENHANCE

    def __init__(self, prompt_id: str, thumb_path: str | None, label_text: str,
                 parent=None, *, media_type: str | None = None,
                 movie_path: str | None = None, starred: bool = False,
                 enhance: str | None = None, controls: bool = True,
                 enhancing: EnhancingRun | None = None,
                 corner_actions: list | None = None):
        super().__init__(parent)
        self.prompt_id = prompt_id
        self._selected = False
        self._starred = starred
        self._enhance = enhance       # what the enhance corner has to say, if anything
        self._enhancing = enhancing   # the run being made of this image, if any
        # The tile's own picture, held aside while a running enhancement streams
        # its frames over the top, so the end of the run restores it.
        self._resting_pixmap: QPixmap | None = None
        self._corner_buttons: list[QPushButton] = []
        self._press_pos: QPoint | None = None  # left-press origin, for drag detection
        self.setObjectName("thumbnailTile")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Right-click anywhere on the tile asks the gallery for a context menu.
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.context_requested.emit(self.prompt_id, self.mapToGlobal(pos))
        )
        self.setFixedSize(180, 200)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        self._image_label = QLabel()
        self._image_label.setFixedSize(_IMAGE_SIZE)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # A video tile loops its short WebP preview; an image (or a video whose
        # WebP couldn't be built) shows its static frame.
        if movie_path and Path(movie_path).exists():
            movie = looping_movie(movie_path, _IMAGE_SIZE, self._image_label)
            self._image_label.setMovie(movie)
            movie.start()
        elif thumb_path and Path(thumb_path).exists():
            pm = QPixmap(str(thumb_path))
            self._image_label.setPixmap(
                pm.scaled(_IMAGE_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
            )
        else:
            self._image_label.setText("No preview")

        self._text_label = QLabel(label_text)
        self._text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._text_label.setWordWrap(True)
        self._text_label.setMaximumHeight(30)
        # Transparent so the tile's fill shows through behind the caption.
        self._text_label.setStyleSheet("background-color: transparent;")

        # Let mouse events (clicks, hover) fall through to the tile, so enter/leave
        # track the whole tile instead of flickering as the cursor crosses a child.
        self._image_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout.addWidget(self._image_label)
        layout.addWidget(self._text_label)
        self._apply_styles()

        # In a mixed listing (the Recents shelf) a corner badge names the kind;
        # inside a single-type folder the caller leaves it off as redundant. It
        # takes the top-right, the one corner the controls below leave alone.
        if media_type:
            MediaBadge(media_type, self)

        # Star, trash and plus in the tile's other three corners: what the item is
        # (bookmarked, enhanced) and what can be done to it, as one mark each, all
        # of them up whenever there is an item under them. A Trash-shelf tile
        # passes controls=False — its item is already deleted, so there is nothing
        # here to bookmark, bin or enhance, and its own restore/purge controls are
        # the two acts left.
        layout.activate()  # so the picture has a rectangle for the controls to sit in
        self._controls = CornerControls(self) if controls else None
        if self._controls is not None:
            self._controls.place(self._image_label.geometry())
            self._controls.triggered.connect(
                lambda action: self.control_triggered.emit(self.prompt_id, action))
            for button in self._controls.buttons():
                button.installEventFilter(self)  # an off-tile exit from a control

        # While an enhancement of this image is cooking, the tile wears the same
        # two overlays an in-flight card does, so work in progress reads the same
        # whichever kind of work it is: a scrim naming the stage, and a bar along
        # the picture's foot saying how far along the run is. The scrim dims the
        # picture rather than replacing it — the base render is out and worth
        # looking at, which is the point of generating it first.
        self._enhancing_overlay = StageScrim(self)
        self._enhancing_bar = ProgressCaption(self)
        self._enhancing_bar.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._enhancing_bar.hide()
        # Its own clock rather than the gallery's poll, so the countdown advances
        # a second at a time whether or not a refresh has landed.
        self._enhancing_tick = QTimer(self)
        self._enhancing_tick.setInterval(_TICK_MS)
        self._enhancing_tick.timeout.connect(self._render_enhancing_timing)
        self._place_enhancing_bar()
        self._show_enhancing_run()

        # An i2v folder's tiles carry top-left hover controls to re-roll one seed
        # on its own; other tiles pass none and grow no buttons.
        self._build_corner_actions(corner_actions or [])

    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool):
        """Lighten the whole tile when selected; restore the resting look when not."""
        if selected == self._selected:
            return  # idempotent: skip restyling thumbnails a click didn't move
        self._selected = selected
        self._apply_styles()

    def is_starred(self) -> bool:
        return self._starred

    def set_starred(self, starred: bool):
        """Fill or hollow the corner star as the item's bookmark is toggled."""
        if starred == self._starred:
            return
        self._starred = starred
        self._sync_controls()

    def enhance_state(self) -> str | None:
        """What this tile's enhance corner is saying, or ``None`` where it has no
        plus at all (:mod:`origenerator.gui.corner_controls`)."""
        return self._enhance

    def set_enhance(self, enhance: str | None):
        """Re-read the enhance corner without rebuilding the tile — what a turn of
        the Enhance panel's knobs does to every picture on screen at once."""
        if enhance == self._enhance:
            return
        self._enhance = enhance
        self._sync_controls()

    def _sync_controls(self):
        """Point the corner controls at this tile's current state.

        A tile with a run cooking on it drops them entirely: the bar along the
        picture's foot is laid over those two corners, so a control there would
        be a button nobody can see and everybody can press — and what is on the
        tile meanwhile is a part-drawn frame of a file that does not exist yet,
        which is nothing to bookmark or bin.
        """
        if self._controls is None:
            return
        if self._enhancing is not None:
            self._controls.hide_all()
        else:
            self._controls.show_for(starred=self._starred, enhance=self._enhance)

    def is_enhancing(self) -> bool:
        return self._enhancing is not None

    def set_enhancing(self, run: EnhancingRun | None):
        """Show the enhancement being made of this image, or clear it away.

        Fed on every reconcile, so a fresh frame and another step of progress
        arrive the same way: the picture takes the run's latest frame, the scrim
        names the stage over it, and the bar at its foot carries how far along
        the run is and how much longer it has.

        A run that ends puts the tile's own picture back: the streamed frames
        are a partial render of a file that doesn't exist yet, so once the run
        is over they are no longer of anything. (A landed enhancement folds onto
        the row and the rebuild redraws the tile from the new file; a cancelled
        one leaves the base render, which is what was there before.)"""
        self._enhancing = run
        if run is None and self._resting_pixmap is not None:
            self._image_label.setPixmap(self._resting_pixmap)
            self._resting_pixmap = None
        if run is not None and run.frame:
            self._paint_enhancing_frame(run.frame)
        self._show_enhancing_run()

    def _paint_enhancing_frame(self, frame: bytes):
        """Paint the latest frame of the enhancement being made of this image.

        The tile is where the user is looking while a folder enhances itself, so
        the run streams here as well as in the info pane — the overlays stay over
        the top, because what is on the tile is still not the finished file."""
        pixmap = QPixmap()
        if not pixmap.loadFromData(frame) or pixmap.isNull():
            return
        if self._resting_pixmap is None:
            self._resting_pixmap = self._image_label.pixmap()
        self._image_label.setPixmap(
            pixmap.scaled(_IMAGE_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
        )

    def _show_enhancing_run(self):
        """Put the scrim and the bar up over the picture, or take them away.

        The scrim's place is re-read each time: the streamed frames leave the
        picture where it was, but a tile built before its layout ran has none yet.
        """
        run = self._enhancing
        self._sync_controls()
        self._enhancing_overlay.cover(
            self._image_label, "Enhancing…" if run is not None else None,
            inset=_BORDER_PX)
        self._enhancing_bar.setVisible(run is not None)
        if run is None:
            self._enhancing_tick.stop()
            return
        self._enhancing_bar.raise_()  # over the scrim just raised, and the badge
        self._render_enhancing_timing()
        # Only a run ComfyUI has actually started has a clock to advance; ticking
        # a queued one would redraw a line that cannot change.
        if run.started_at is None:
            self._enhancing_tick.stop()
        else:
            self._enhancing_tick.start()

    def _render_enhancing_timing(self):
        """Write the run's reading across the bar at the picture's foot — the
        compact one, since a tile is a third of the bottom strip's width."""
        run = self._enhancing
        if run is None:
            return
        elapsed = (None if run.started_at is None
                   else max(0.0, time.time() - run.started_at))
        self._enhancing_bar.show_progress(
            progress_status_label(elapsed, run.progress, run.typical_seconds,
                                  compact=True),
            run.progress if run.status == "running" else None,
        )

    def _place_enhancing_bar(self):
        """Lay the bar along the picture's foot, inside the picture's own border.

        It covers the enhanced badge while it is up, which is the right way
        round: the badge says this image has an enhancement, and the bar says
        another is being made right now.
        """
        picture = self._image_label.geometry()
        self._enhancing_bar.setGeometry(QRect(
            picture.x() + _BORDER_PX,
            picture.y() + picture.height() - _BORDER_PX - _BAR_HEIGHT,
            picture.width() - 2 * _BORDER_PX,
            _BAR_HEIGHT,
        ))

    def _apply_styles(self):
        if self._selected:
            self.setStyleSheet(_SELECTED_TILE_CSS)
            border = _BORDER_SELECTED
        else:
            self.setStyleSheet("")
            border = _BORDER_UNSELECTED
        # Transparent background so the tile fill shows behind any letterboxing.
        self._image_label.setStyleSheet(
            f"background-color: transparent; border: {border}; border-radius: 3px;"
        )

    # --- corner action buttons (hover-revealed per-seed re-rolls) -----------

    def _build_corner_actions(self, actions: list):
        """Lay out one hidden button per ``(action_id, icon, tooltip)`` along the
        tile's top-left edge.

        Each fires :attr:`corner_action_triggered` with this tile's prompt_id and
        its action_id. Hidden until the tile is hovered (see :meth:`enterEvent`);
        an event filter keeps them up while the cursor sits on a button rather than
        the tile itself, so they don't flicker out from under the pointer.
        """
        for i, (action_id, icon, tooltip) in enumerate(actions):
            button = QPushButton(self)
            button.setIcon(icon)
            button.setIconSize(QSize(CORNER_SIZE - 8, CORNER_SIZE - 8))
            button.setToolTip(tooltip)
            button.setFixedSize(CORNER_SIZE, CORNER_SIZE)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(_CORNER_BUTTON_CSS)
            button.move(self._image_label.x() + CORNER_INSET + i * (CORNER_SIZE + CORNER_GAP),
                        self._image_label.y() + CORNER_INSET)
            button.setVisible(False)
            button.installEventFilter(self)  # keep the set up while hovering a button
            button.clicked.connect(lambda _=False, a=action_id: self.corner_action_triggered.emit(self.prompt_id, a))
            self._corner_buttons.append(button)

    def _set_corner_actions_visible(self, visible: bool):
        for button in self._corner_buttons:
            button.setVisible(visible)

    def _cursor_over_tile(self) -> bool:
        """Whether the pointer is still anywhere within the tile — including over a
        corner button — so leaving for a button doesn't read as leaving the tile."""
        return self.rect().contains(self.mapFromGlobal(QCursor.pos()))

    def _hover_buttons(self) -> list:
        """Every child a cursor can be over while it is still "on the tile" — the
        shelf's own actions and the three corner controls alike."""
        controls = [] if self._controls is None else self._controls.buttons()
        return self._corner_buttons + controls

    def eventFilter(self, obj, event):
        # A button is a child, so the cursor leaving it (back onto the tile, or off
        # the tile entirely) is where an off-tile exit from a button surfaces.
        if event.type() == QEvent.Type.Leave and obj in self._hover_buttons():
            if not self._cursor_over_tile():
                self._set_corner_actions_visible(False)
        return super().eventFilter(obj, event)

    def enterEvent(self, event):
        self._set_corner_actions_visible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._cursor_over_tile():  # moving onto a button isn't leaving the tile
            self._set_corner_actions_visible(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        # Only a left click (re)selects. A right click opens the context menu via
        # the custom-context-menu signal and must NOT collapse a multi-selection.
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()  # origin for a possible drag
            self.clicked.emit(self.prompt_id)

    def mouseMoveEvent(self, event):
        # Drag the generation out to a combine drop slot, but only once the press
        # has travelled far enough to read as a drag rather than a click — so a
        # plain click still just selects, and a double-click still opens.
        if self._press_pos is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        moved = (event.position().toPoint() - self._press_pos).manhattanLength()
        if moved < QApplication.startDragDistance():
            return
        self._press_pos = None
        drag = QDrag(self)
        drag.setMimeData(generation_mime(self.prompt_id))
        # The tile's picture trails the cursor — the frame a video tile's looping
        # WebP is on, as much as a still image's pixmap.
        set_drag_thumbnail(drag, label_thumbnail(self._image_label))
        # Announce the drag so a combine slot can light up the moment it starts —
        # QDrag.exec is modal, so the highlight is on for the whole gesture.
        self.drag_started.emit(self.prompt_id)
        try:
            drag.exec(Qt.DropAction.CopyAction)
        finally:
            self.drag_ended.emit()

    def mouseDoubleClickEvent(self, event):
        # A left double-click is an "open" gesture; the first click's press has
        # already selected the tile, so the handler acts on the current selection.
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.prompt_id)
