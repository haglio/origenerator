from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QIcon, QMovie, QPixmap
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget
from shared_ui.palette import BLUE, as_rgba
from shared_ui.spacing import BUTTON_RADIUS

from origenerator.gui import icons, palette, tile_shape
from origenerator.gui.corner_buttons import (
    CORNER_GAP,
    CORNER_INSET,
    CORNER_SIZE,
    GROUND_CSS,
    CornerButtons,
    RestoreOffer,
    bar_between_the_bottom_corners,
)
from origenerator.gui.drag_thumbnail import DragOut, label_thumbnail
from origenerator.gui.generation_drag import generation_mime
from origenerator.gui.inflight import TICK_MS, RunReading
from origenerator.gui.item_type_icon import ItemTypeIcon, VideoLength
from origenerator.gui.live_frames import pixmap_of
from origenerator.gui.looping_preview import play_in, what_plays_in
from origenerator.gui.looping_preview import set_in_sight as video_in_sight
from origenerator.gui.progress_bar import ProgressBar
from origenerator.gui.style_property import set_style_property
from origenerator.gui.tile_status_scrim import TileStatusScrim
from origenerator.media import MediaType
from origenerator.trash_collection import why_it_cannot_be_restored

_IMAGE_SIZE = tile_shape.thumbnail_size()
_BORDER_PX = 2
_CORNER_BUTTON_CSS = (
    GROUND_CSS + f"QPushButton:hover {{ background: {as_rgba(BLUE, 0.9)}; }}"
)

_SELECTED = "selected"
# A plain QWidget subclass paints no stylesheet background without WA_StyledBackground, and the app's global QWidget background paints child labels opaque unless they are transparent.
_TILE_CSS = (
    f'#thumbnailTile[{_SELECTED}="true"] {{ background-color: {palette.SELECTED_FILL}; '
    f"border-radius: {BUTTON_RADIUS}px; }}")
_THUMBNAIL_CSS = (
    f"QLabel {{ background-color: transparent; border: 2px solid {palette.TILE_BORDER}; "
    f"border-radius: {BUTTON_RADIUS}px; }}"
    f'QLabel[{_SELECTED}="true"] {{ border-color: {palette.SELECTED_BORDER}; }}')


class CornerButton(NamedTuple):
    action_id: str
    icon: QIcon
    tooltip: str


@dataclass(frozen=True)
class TileAppearance:
    caption: str | None = None
    media_type: str | None = None
    video_seconds: float | None = None
    movie_path: str | None = None
    favorite: bool = False
    enhance: str | None = None
    enhancing: RunReading | None = None
    corner_buttons: list[CornerButton] | None = None
    restore: RestoreOffer | None = None


PLAIN_APPEARANCE = TileAppearance()


def restore_offer_of(item: dict) -> RestoreOffer:
    why_not = why_it_cannot_be_restored(item)
    if why_not:
        return RestoreOffer(why_not, can_restore=False)
    return RestoreOffer("Restore — make it again" if item.get("emptied")
                        else "Restore — put it and its files back where they were")


def _let_go_of_its_frames(movie: QMovie | None) -> None:
    if movie is not None:
        # Qt: a QMovie empties its frame cache only when it is given its file again.
        movie.setFileName(movie.fileName())


class ItemTile(QWidget):
    pressed = Signal(str, Qt.KeyboardModifier)
    clicked = Signal(str)
    double_clicked = Signal(str)
    context_requested = Signal(str, QPoint)
    corner_button_triggered = Signal(str, str)
    control_triggered = Signal(str, str)

    def __init__(self, prompt_id: str, thumb_path: str | None, label_text: str,
                 appearance: TileAppearance = PLAIN_APPEARANCE, parent=None):
        super().__init__(parent)
        self.prompt_id = prompt_id
        self.look = self.look_of(prompt_id, thumb_path, label_text, appearance)
        self._selected = False
        self._in_sight = True
        self._hidden = False
        self._favorite = appearance.favorite
        self._enhance = appearance.enhance
        self._enhancing = appearance.enhancing
        self._resting_pixmap: QPixmap | None = None
        self._corner_buttons: list[QPushButton] = []
        self.drag_out = DragOut()
        self.setObjectName("thumbnailTile")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
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
        self._fill_the_thumbnail(thumb_path, appearance.movie_path)

        self._text_label = QLabel(label_text)
        self._text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._text_label.setWordWrap(True)
        tile_shape.style_caption(self._text_label)
        self._text_label.setStyleSheet("background-color: transparent;")

        # Qt: without it enter/leave flicker as the cursor crosses a child.
        self._image_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout.addWidget(self._image_label)
        layout.addWidget(self._text_label)
        self._style_by_selection()

        self._media_type = appearance.media_type
        self._mark_its_kind(appearance)

        layout.activate()  # Qt gives the thumbnail its rectangle only once the layout has run
        self._controls = CornerButtons(self, restore=appearance.restore)
        self._controls.place(self._image_label.geometry())
        self._controls.triggered.connect(
            lambda action: self.control_triggered.emit(self.prompt_id, action))
        for button in self._controls.buttons():
            button.installEventFilter(self)  # Qt reports a cursor leaving through a control only to the control
        self._sync_controls()

        self._build_the_enhancing_bar()

        self._build_corner_buttons(appearance.corner_buttons or [])

    def _fill_the_thumbnail(self, thumb_path: str | None, movie_path: str | None) -> None:
        if movie_path and Path(movie_path).exists():
            play_in(self._image_label, movie_path, _IMAGE_SIZE).setCacheMode(
                QMovie.CacheMode.CacheAll)
        elif thumb_path and Path(thumb_path).exists():
            pm = QPixmap(str(thumb_path))
            self._image_label.setPixmap(
                pm.scaled(_IMAGE_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
            )
        else:
            self._image_label.setText("No preview")

    def _mark_its_kind(self, appearance: TileAppearance) -> None:
        if not appearance.media_type:
            return
        mark = ItemTypeIcon(appearance.media_type, self)
        if appearance.media_type == MediaType.VIDEO and appearance.video_seconds:
            VideoLength(appearance.video_seconds, mark)

    def _build_the_enhancing_bar(self) -> None:
        self._status_scrim = TileStatusScrim(self)
        self._enhancing_bar = ProgressBar(self)
        self._enhancing_bar.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._enhancing_bar.hide()
        self._enhancing_tick = QTimer(self)
        self._enhancing_tick.setInterval(TICK_MS)
        self._enhancing_tick.timeout.connect(self._render_enhancing_timing)
        self._place_enhancing_bar()
        self._show_enhancing_run()

    @staticmethod
    def look_of(prompt_id: str, thumb_path: str | None, label_text: str,
                appearance: TileAppearance = PLAIN_APPEARANCE) -> tuple:
        return (prompt_id, thumb_path, label_text, appearance.media_type,
                appearance.video_seconds, appearance.movie_path, appearance.restore,
                tuple(action.action_id for action in appearance.corner_buttons or ()))

    def set_selected(self, selected: bool):
        if selected == self._selected:
            return
        self._selected = selected
        self._apply_styles()

    def enhance_state(self) -> str | None:
        return self._enhance

    def set_enhance(self, enhance: str | None):
        if enhance == self._enhance:
            return
        self._enhance = enhance
        self._sync_controls()

    def set_in_sight(self, in_sight: bool) -> None:
        if in_sight == self._in_sight:
            return
        self._in_sight = in_sight
        self._play_while_seen()
        if not in_sight:
            _let_go_of_its_frames(what_plays_in(self._image_label))

    def hideEvent(self, event):
        self._hidden = True
        self._play_while_seen()
        super().hideEvent(event)

    def showEvent(self, event):
        self._hidden = False
        self._play_while_seen()
        super().showEvent(event)

    def _play_while_seen(self) -> None:
        video_in_sight(self._image_label, self._in_sight and not self._hidden)

    def set_favorite(self, favorite: bool):
        self._favorite = favorite
        self._sync_controls()

    def _sync_controls(self):
        waiting = self._enhancing is not None and not self._enhancing.rendering
        self._controls.show_for(favorite=self._favorite,
                                enhance=icons.ENHANCE_QUEUED if waiting else self._enhance,
                                kind=self._media_type)

    @property
    def enhancing(self) -> RunReading | None:
        return self._enhancing

    def set_enhancing(self, run: RunReading | None):
        self._enhancing = run
        self._sync_controls()
        if run is None and self._resting_pixmap is not None:
            self._image_label.setPixmap(self._resting_pixmap)
            self._resting_pixmap = None
        if run is not None and run.frame:
            self._paint_enhancing_frame(run.frame)
        self._show_enhancing_run()

    def _paint_enhancing_frame(self, frame: bytes):
        if (pixmap := pixmap_of(frame)) is None:
            return
        if self._resting_pixmap is None:
            self._resting_pixmap = self._image_label.pixmap()
        self._image_label.setPixmap(
            pixmap.scaled(_IMAGE_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
        )

    def _show_enhancing_run(self):
        run = self._enhancing
        self._status_scrim.cover(
            self._image_label, "Enhancing…" if run is not None else None,
            inset=_BORDER_PX)
        self._controls.place(self._image_label.geometry())
        self._enhancing_bar.setVisible(run is not None)
        if run is None:
            self._enhancing_tick.stop()
            return
        self._enhancing_bar.raise_()
        self._render_enhancing_timing()
        if run.started_at is None:
            self._enhancing_tick.stop()
        else:
            self._enhancing_tick.start()

    def _render_enhancing_timing(self):
        run = self._enhancing
        if run is None:
            return

        self._enhancing_bar.show_progress(
            run.caption(compact=True),
            *run.bars(),
        )

    def _place_enhancing_bar(self):
        self._enhancing_bar.setGeometry(
            bar_between_the_bottom_corners(self._image_label.geometry(), _BORDER_PX))

    def _style_by_selection(self):
        for widget, sheet in ((self, _TILE_CSS), (self._image_label, _THUMBNAIL_CSS)):
            widget.setProperty(_SELECTED, False)
            widget.setStyleSheet(sheet)

    def _apply_styles(self):
        set_style_property(self, _SELECTED, self._selected)
        set_style_property(self._image_label, _SELECTED, self._selected)

    def _build_corner_buttons(self, actions: list[CornerButton]):
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
            button.installEventFilter(self)
            button.clicked.connect(
                lambda _=False, a=action.action_id:
                self.corner_button_triggered.emit(self.prompt_id, a))
            self._corner_buttons.append(button)

    def _set_corner_buttons_visible(self, visible: bool):
        for button in self._corner_buttons:
            button.setVisible(visible)

    def _cursor_over_tile(self) -> bool:
        return self.rect().contains(self.mapFromGlobal(QCursor.pos()))

    def _hover_buttons(self) -> list:
        return self._corner_buttons + self._controls.buttons()

    def eventFilter(self, obj, event):
        if (event.type() == QEvent.Type.Leave and obj in self._hover_buttons()
                and not self._cursor_over_tile()):
            self._set_corner_buttons_visible(False)
        return super().eventFilter(obj, event)

    def enterEvent(self, event):
        self._set_corner_buttons_visible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._cursor_over_tile():
            self._set_corner_buttons_visible(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_out.note_press(event)
            self.pressed.emit(self.prompt_id, event.modifiers())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.drag_out.pressed:
            self.drag_out.forget()
            self.clicked.emit(self.prompt_id)

    def mouseMoveEvent(self, event):
        if not self.drag_out.should_start(event):
            return
        self.drag_out.start(generation_mime(self.prompt_id), label_thumbnail(self._image_label))

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.prompt_id)

