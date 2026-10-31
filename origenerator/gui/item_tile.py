from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from PyQt6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QIcon, QPixmap
from PyQt6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget
from shared_ui.palette import BLUE, as_rgba
from shared_ui.spacing import BUTTON_RADIUS

from origenerator.gui import palette, tile_shape
from origenerator.gui.corner_buttons import (
    CORNER_GAP,
    CORNER_INSET,
    CORNER_SIZE,
    GROUND_CSS,
    CornerButtons,
)
from origenerator.gui.drag_thumbnail import DragOut, label_thumbnail
from origenerator.gui.generation_drag import generation_mime
from origenerator.gui.inflight import TICK_MS, RunReading
from origenerator.gui.item_type_icon import ItemTypeIcon
from origenerator.gui.looping_preview import play_in
from origenerator.gui.looping_preview import set_in_sight as video_in_sight
from origenerator.gui.progress_caption import BAR_HEIGHT, ProgressCaption
from origenerator.gui.stage_scrim import StageScrim

_IMAGE_SIZE = tile_shape.thumbnail_size()  # the thumbnail area, inside the family tile
_BORDER_PX = 2
# Hover-revealed corner buttons (an i2v tile's per-seed re-rolls, a review
# collection's keep/reject): the same translucent ground the corner buttons sit on, blue
# on hover, laid along the tile's top-left edge — the one edge the three corner
# controls leave alone.
_CORNER_BUTTON_CSS = (
    GROUND_CSS + f"QPushButton:hover {{ background: {as_rgba(BLUE, 0.9)}; }}"
)

# A selected thumbnail fills its whole tile — under both the image and the
# caption — the way a file browser highlights a picked item. Two things make
# the fill actually show:
#   * WA_StyledBackground, or a plain QWidget subclass paints no stylesheet
#     background at all; and
#   * transparent child labels, or the app's global `QWidget { background-color }`
#     paints them opaque and the fill only peeks through the 4px margin as a
#     frame (which is what an earlier attempt did).
_SELECTED_TILE_CSS = (
    f"#thumbnailTile {{ background-color: {palette.SELECTED_FILL}; border-radius: {BUTTON_RADIUS}px; }}")
_BORDER_UNSELECTED = f"2px solid {palette.TILE_BORDER}"
_BORDER_SELECTED = f"2px solid {palette.SELECTED_BORDER}"


class CornerButton(NamedTuple):
    """One hover control on a tile's corner: what it asks for, the icon it wears,
    and what it says on hover."""

    action_id: str
    icon: QIcon
    tooltip: str


class ItemTile(QWidget):
    pressed = pyqtSignal(str, Qt.KeyboardModifier)  # prompt_id, the keys held during the press
    clicked = pyqtSignal(str)  # prompt_id, let go of without being dragged
    double_clicked = pyqtSignal(str)  # prompt_id — an "open" gesture
    context_requested = pyqtSignal(str, QPoint)  # prompt_id, global position
    corner_button_triggered = pyqtSignal(str, str)  # prompt_id, action_id
    control_triggered = pyqtSignal(str, str)  # prompt_id, corner_buttons.STAR/TRASH/ENHANCE

    def __init__(self, prompt_id: str, thumb_path: str | None, label_text: str,
                 parent=None, *, media_type: str | None = None,
                 movie_path: str | None = None, favorite: bool = False,
                 enhance: str | None = None, controls: bool = True,
                 enhancing: RunReading | None = None,
                 corner_buttons: list[CornerButton] | None = None):
        super().__init__(parent)
        self.prompt_id = prompt_id
        self.look = self.look_of(prompt_id, thumb_path, label_text, media_type=media_type,
                                 movie_path=movie_path, controls=controls,
                                 corner_buttons=corner_buttons)
        self._selected = False
        self._favorite = favorite
        self._enhance = enhance       # what the enhance corner has to say, if anything
        self._enhancing = enhancing   # the run being made of this image, if any
        # The tile's own thumbnail, held aside while a running enhancement streams
        # its frames over the top, so the end of the run restores it.
        self._resting_pixmap: QPixmap | None = None
        self._corner_buttons: list[QPushButton] = []
        self.drag_out = DragOut()
        self.setObjectName("thumbnailTile")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Right-click anywhere on the tile asks the gallery for a context menu.
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.context_requested.emit(self.prompt_id, self.mapToGlobal(pos))
        )
        self.setFixedSize(*tile_shape.tile_size())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*(tile_shape.TILE_MARGIN,) * 4)
        layout.setSpacing(tile_shape.TILE_SPACING)

        self._image_label = QLabel()
        self._image_label.setFixedSize(_IMAGE_SIZE)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # A video tile loops its short WebP preview; an image (or a video whose
        # WebP couldn't be built) shows its static frame.
        if movie_path and Path(movie_path).exists():
            play_in(self._image_label, movie_path, _IMAGE_SIZE)
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
        tile_shape.style_caption(self._text_label)
        # Transparent so the tile's fill shows through under the caption.
        self._text_label.setStyleSheet("background-color: transparent;")

        # Let mouse events (clicks, hover) fall through to the tile, so enter/leave
        # track the whole tile instead of flickering as the cursor crosses a child.
        self._image_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout.addWidget(self._image_label)
        layout.addWidget(self._text_label)
        self._apply_styles()

        # In a mixed listing (the Latest collection) an item type icon names the kind;
        # inside a single-type folder the caller leaves it off as redundant. Which
        # corner it takes is ItemTypeIcon's own business, and it says so.
        if media_type:
            ItemTypeIcon(media_type, self)

        # Star, trash and plus in the tile's other three corners: what the item is
        # (favorited, enhanced) and what can be done to it, as one mark each, all
        # of them up whenever there is an item under them. A Trash-collection tile
        # passes controls=False — its item is already deleted, so there is nothing
        # here to favorite, trash or enhance, and its own restore/purge controls are
        # the two acts left.
        layout.activate()  # so the thumbnail has a rectangle for the controls to sit in
        self._controls = CornerButtons(self) if controls else None
        if self._controls is not None:
            self._controls.place(self._image_label.geometry())
            self._controls.triggered.connect(
                lambda action: self.control_triggered.emit(self.prompt_id, action))
            for button in self._controls.buttons():
                button.installEventFilter(self)  # an off-tile exit from a control
        self._sync_controls()

        # While an enhancement of this image is in flight, the tile wears the same
        # two overlays an in-flight tile does, so work in progress reads the same
        # whichever kind of work it is: a scrim naming the stage, and a bar along
        # the thumbnail's foot saying how far along the run is. The scrim dims the
        # thumbnail rather than replacing it — the base render is out and worth
        # looking at, which is the point of generating it first.
        self._enhancing_overlay = StageScrim(self)
        self._enhancing_bar = ProgressCaption(self)
        self._enhancing_bar.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._enhancing_bar.hide()
        # Its own clock rather than the gallery's poll, so the countdown advances
        # a second at a time whether or not a refresh has landed.
        self._enhancing_tick = QTimer(self)
        self._enhancing_tick.setInterval(TICK_MS)
        self._enhancing_tick.timeout.connect(self._render_enhancing_timing)
        self._place_enhancing_bar()
        self._show_enhancing_run()

        # An i2v folder's tiles carry top-left hover controls to re-roll one seed
        # on its own; other tiles pass none and grow no buttons.
        self._build_corner_buttons(corner_buttons or [])

    @staticmethod
    def look_of(prompt_id: str, thumb_path: str | None, label_text: str, *,
                media_type: str | None = None, movie_path: str | None = None,
                controls: bool = True,
                corner_buttons: list[CornerButton] | None = None, **_mutable) -> tuple:
        """What a tile cannot be changed into once built."""
        return (prompt_id, thumb_path, label_text, media_type, movie_path, controls,
                tuple(action.action_id for action in corner_buttons or ()))

    def set_selected(self, selected: bool):
        """Lighten the whole tile when selected; restore the resting look when not."""
        if selected == self._selected:
            return  # idempotent: skip restyling thumbnails a click didn't move
        self._selected = selected
        self._apply_styles()

    def enhance_state(self) -> str | None:
        """What this tile's enhance corner is saying, or ``None`` where it has no
        plus at all (:mod:`origenerator.gui.corner_buttons`)."""
        return self._enhance

    def set_enhance(self, enhance: str | None):
        """Re-read the enhance corner without rebuilding the tile — what a turn of
        the Enhance panel's settings does to every item on screen at once."""
        if enhance == self._enhance:
            return
        self._enhance = enhance
        self._sync_controls()

    def play_moving_preview(self, movie_path: str) -> None:
        play_in(self._image_label, movie_path, _IMAGE_SIZE)

    def set_in_sight(self, in_sight: bool) -> None:
        video_in_sight(self._image_label, in_sight)

    def set_favorite(self, favorite: bool):
        self._favorite = favorite
        self._sync_controls()

    def _sync_controls(self):
        if self._controls is None:
            return
        self._controls.show_for(favorite=self._favorite, enhance=self._enhance)

    def set_enhancing(self, run: RunReading | None):
        """Show the enhancement being made of this image, or clear it away.

        Fed on every reconcile, so a fresh frame and another step of progress
        arrive the same way: the thumbnail takes the run's latest frame, the scrim
        names the stage over it, and the bar at its foot carries how far along
        the run is and how much longer it has.

        A run that ends puts the tile's own thumbnail back: the streamed frames
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
        """Put the scrim and the bar up over the thumbnail, or take them away.

        The scrim's place is re-read each time: the streamed frames leave the
        thumbnail where it was, but a tile built before its layout ran has none yet.
        """
        run = self._enhancing
        self._enhancing_overlay.cover(
            self._image_label, "Enhancing…" if run is not None else None,
            inset=_BORDER_PX)
        if self._controls is not None:
            self._controls.place(self._image_label.geometry())
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
        """Write the run's reading across the bar at the thumbnail's foot — the
        compact one, since a tile is a third of the Job Queue's width."""
        run = self._enhancing
        if run is None:
            return

        self._enhancing_bar.show_progress(
            run.caption(compact=True),
            *run.bars(),
        )

    def _place_enhancing_bar(self):
        area = self._image_label.geometry()
        clear_of_a_corner = CORNER_INSET + CORNER_SIZE + CORNER_GAP
        self._enhancing_bar.setGeometry(QRect(
            area.x() + clear_of_a_corner,
            area.y() + area.height() - _BORDER_PX - BAR_HEIGHT,
            area.width() - 2 * clear_of_a_corner,
            BAR_HEIGHT,
        ))

    def _apply_styles(self):
        if self._selected:
            self.setStyleSheet(_SELECTED_TILE_CSS)
            border = _BORDER_SELECTED
        else:
            self.setStyleSheet("")
            border = _BORDER_UNSELECTED
        # Transparent background so the tile fill shows under any letterboxing.
        self._image_label.setStyleSheet(
            f"background-color: transparent; border: {border}; border-radius: {BUTTON_RADIUS}px;"
        )

    # --- corner buttons (hover-revealed per-seed re-rolls) -----------

    def _build_corner_buttons(self, actions: list[CornerButton]):
        """Lay out one hidden button per :class:`CornerButton` along the tile's
        top-left edge.

        Each fires :attr:`corner_button_triggered` with this tile's prompt_id and
        its action_id. Hidden until the tile is hovered (see :meth:`enterEvent`);
        an event filter keeps them up while the cursor sits on a button rather than
        the tile itself, so they don't flicker out from under the pointer.
        """
        for i, action in enumerate(actions):
            button = QPushButton(self)
            button.setIcon(action.icon)
            button.setIconSize(QSize(CORNER_SIZE - 8, CORNER_SIZE - 8))
            button.setToolTip(action.tooltip)
            button.setFixedSize(CORNER_SIZE, CORNER_SIZE)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(_CORNER_BUTTON_CSS)
            button.move(self._image_label.x() + CORNER_INSET + i * (CORNER_SIZE + CORNER_GAP),
                        self._image_label.y() + CORNER_INSET)
            button.setVisible(False)
            button.installEventFilter(self)  # keep the set up while hovering a button
            button.clicked.connect(
                lambda _=False, a=action.action_id:
                self.corner_button_triggered.emit(self.prompt_id, a))
            self._corner_buttons.append(button)

    def _set_corner_buttons_visible(self, visible: bool):
        for button in self._corner_buttons:
            button.setVisible(visible)

    def _cursor_over_tile(self) -> bool:
        """Whether the pointer is still anywhere within the tile — including over a
        corner button — so leaving for a button doesn't read as leaving the tile."""
        return self.rect().contains(self.mapFromGlobal(QCursor.pos()))

    def _hover_buttons(self) -> list:
        """Every child a cursor can be over while it is still "on the tile" — the
        collection's own actions and the three corner buttons alike."""
        controls = [] if self._controls is None else self._controls.buttons()
        return self._corner_buttons + controls

    def eventFilter(self, obj, event):
        # A button is a child, so the cursor leaving it (back onto the tile, or off
        # the tile entirely) is where an off-tile exit from a button surfaces.
        if event.type() == QEvent.Type.Leave and obj in self._hover_buttons():
            if not self._cursor_over_tile():
                self._set_corner_buttons_visible(False)
        return super().eventFilter(obj, event)

    def enterEvent(self, event):
        self._set_corner_buttons_visible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._cursor_over_tile():  # moving onto a button isn't leaving the tile
            self._set_corner_buttons_visible(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        # Only a left click (re)selects. A right click opens the context menu via
        # the custom-context-menu signal and must NOT collapse a multi-selection.
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_out.note_press(event)
            self.pressed.emit(self.prompt_id, event.modifiers())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.drag_out.pressed:
            self.drag_out.forget()
            self.clicked.emit(self.prompt_id)

    def mouseMoveEvent(self, event):
        # Drag the generation out to wherever it is dropped, but only once the press
        # has travelled far enough to read as a drag rather than a click.
        if not self.drag_out.should_start(event):
            return
        # The tile's thumbnail trails the cursor — the frame a video tile's looping
        # WebP is on, as much as a still image's pixmap.
        self.drag_out.start(generation_mime(self.prompt_id), label_thumbnail(self._image_label))

    def mouseDoubleClickEvent(self, event):
        # A left double-click is an "open" gesture; the first click's press has
        # already selected the tile, so the handler acts on the current selection.
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.prompt_id)

