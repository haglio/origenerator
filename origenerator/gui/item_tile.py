from __future__ import annotations

from dataclasses import dataclass
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
    RestoreOffer,
)
from origenerator.gui.drag_thumbnail import DragOut, label_thumbnail
from origenerator.gui.generation_drag import generation_mime
from origenerator.gui.inflight import TICK_MS, RunReading
from origenerator.gui.item_type_icon import ItemTypeIcon
from origenerator.gui.looping_preview import play_in
from origenerator.gui.looping_preview import set_in_sight as video_in_sight
from origenerator.gui.progress_bar import BAR_HEIGHT, ProgressBar
from origenerator.gui.tile_status_scrim import TileStatusScrim
from origenerator.trash_collection import why_it_cannot_be_restored

_IMAGE_SIZE = tile_shape.thumbnail_size()
_BORDER_PX = 2
_CORNER_BUTTON_CSS = (
    GROUND_CSS + f"QPushButton:hover {{ background: {as_rgba(BLUE, 0.9)}; }}"
)

# A plain QWidget subclass paints no stylesheet background without WA_StyledBackground, and the app's global QWidget background paints child labels opaque unless they are transparent.
_SELECTED_TILE_CSS = (
    f"#thumbnailTile {{ background-color: {palette.SELECTED_FILL}; border-radius: {BUTTON_RADIUS}px; }}")
_BORDER_UNSELECTED = f"2px solid {palette.TILE_BORDER}"
_BORDER_SELECTED = f"2px solid {palette.SELECTED_BORDER}"


class CornerButton(NamedTuple):
    action_id: str
    icon: QIcon
    tooltip: str


@dataclass(frozen=True)
class TileAppearance:
    caption: str | None = None
    media_type: str | None = None
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


class ItemTile(QWidget):
    pressed = pyqtSignal(str, Qt.KeyboardModifier)
    clicked = pyqtSignal(str)
    double_clicked = pyqtSignal(str)
    context_requested = pyqtSignal(str, QPoint)
    corner_button_triggered = pyqtSignal(str, str)
    control_triggered = pyqtSignal(str, str)

    def __init__(self, prompt_id: str, thumb_path: str | None, label_text: str,
                 appearance: TileAppearance = PLAIN_APPEARANCE, parent=None):
        super().__init__(parent)
        self.prompt_id = prompt_id
        self.look = self.look_of(prompt_id, thumb_path, label_text, appearance)
        self._selected = False
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

        if appearance.movie_path and Path(appearance.movie_path).exists():
            play_in(self._image_label, appearance.movie_path, _IMAGE_SIZE)
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
        self._text_label.setStyleSheet("background-color: transparent;")

        # Qt: without it enter/leave flicker as the cursor crosses a child.
        self._image_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        layout.addWidget(self._image_label)
        layout.addWidget(self._text_label)
        self._apply_styles()

        if appearance.media_type:
            ItemTypeIcon(appearance.media_type, self)

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
                appearance.movie_path, appearance.restore,
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
        video_in_sight(self._image_label, in_sight)

    def set_favorite(self, favorite: bool):
        self._favorite = favorite
        self._sync_controls()

    def _sync_controls(self):
        self._controls.show_for(favorite=self._favorite, enhance=self._enhance)

    def set_enhancing(self, run: RunReading | None):
        self._enhancing = run
        if run is None and self._resting_pixmap is not None:
            self._image_label.setPixmap(self._resting_pixmap)
            self._resting_pixmap = None
        if run is not None and run.frame:
            self._paint_enhancing_frame(run.frame)
        self._show_enhancing_run()

    def _paint_enhancing_frame(self, frame: bytes):
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
        self._image_label.setStyleSheet(
            f"background-color: transparent; border: {border}; border-radius: {BUTTON_RADIUS}px;"
        )

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

