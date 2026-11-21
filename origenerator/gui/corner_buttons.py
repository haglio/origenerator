from __future__ import annotations

from typing import NamedTuple

from PySide6.QtCore import QObject, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import QPushButton, QWidget
from shared_ui.spacing import BUTTON_GAP, BUTTON_SIZE, GAP_SMALL

from origenerator import gallery
from origenerator.gui import icons, square_buttons
from origenerator.gui.progress_bar import BAR_HEIGHT
from origenerator.gui.tile_rules import CORNER_FACE

STAR = "star"
TRASH = "trash"
ENHANCE = "enhance"
RESTORE = "restore"

_AROUND_THE_GLYPH = 8


def corner_size() -> int:
    return square_buttons.landing(BUTTON_SIZE)


def corner_gap() -> int:
    return square_buttons.landing(BUTTON_GAP)


def corner_inset() -> int:
    return square_buttons.landing(GAP_SMALL)


def size_a_corner_button(button: QPushButton) -> None:
    glyph = square_buttons.landing(BUTTON_SIZE - _AROUND_THE_GLYPH)
    button.setFixedSize(corner_size(), corner_size())
    button.setIconSize(QSize(glyph, glyph))

_DELETE_FOR_GOOD_TIP = "Delete permanently — remove it and its files for good"
_TIPS = {
    icons.ENHANCE_OPEN: ("Enhance this image (upscale + re-sample)",),
    icons.ENHANCE_HELD: (("Already enhanced at these settings — "
                          "change one to make a different version"),),
    icons.ENHANCE_MORE: ("Enhance again, at the settings now on the panel",),
    icons.ENHANCE_QUEUED: ("An enhancement of this image is queued",),
}
BLINK_MS = 900


def bar_between_the_bottom_corners(area: QRect, inset: int = 0) -> QRect:
    clear_of_a_corner = corner_inset() + corner_size() + corner_gap()
    return QRect(area.x() + clear_of_a_corner, area.y() + area.height() - inset - BAR_HEIGHT,
                 area.width() - 2 * clear_of_a_corner, BAR_HEIGHT)


class RestoreOffer(NamedTuple):
    tip: str
    can_restore: bool = True


def enhance_state(row: dict, settings) -> str | None:
    if not gallery.is_enhanceable_row(row):
        return None
    if not gallery.is_enhanced_row(row):
        return icons.ENHANCE_OPEN
    held = gallery.version_matching_settings(row, settings)
    return icons.ENHANCE_HELD if held is not None else icons.ENHANCE_MORE


class _CornerButtonFace(QPushButton):
    """One corner button's face, which swaps its icon as the cursor crosses it: Qt's hover state would change the button, not the mark."""

    def __init__(self, host: QWidget, render, *, enabled: bool = True):
        super().__init__(host)
        self.setEnabled(enabled)
        self._render = render
        self._armed = False
        size_a_corner_button(self)
        self.setObjectName(CORNER_FACE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hide()
        self.redraw()

    def redraw(self):
        self.setIcon(self._render(self._armed))

    def enterEvent(self, event):
        self._arm(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._arm(False)
        super().leaveEvent(event)

    def _arm(self, armed: bool):
        if armed == self._armed:
            return
        self._armed = armed
        self.redraw()


class CornerButtons(QObject):
    triggered = Signal(str)

    def __init__(self, host: QWidget, *, restore: RestoreOffer | None = None):
        super().__init__(host)
        self._restore_tip, can_restore = restore or (None, True)
        self._available = False
        self._favorite = False
        self._enhance: str | None = None
        self._kind = "item"
        self._placed_in: QRect | None = None
        self._star = _CornerButtonFace(
            host, lambda armed: icons.corner_star_icon(favorite=self._favorite, armed=armed)
            if restore is None
            else icons.corner_restore_icon(can_restore=can_restore, armed=armed),
            enabled=can_restore)
        self._trash = _CornerButtonFace(host, lambda armed: icons.corner_trash_icon(
            armed=armed))
        self._lit = False
        self._blink = QTimer(self)
        self._blink.setInterval(BLINK_MS)
        self._blink.timeout.connect(self._blink_once)
        self._enhance_button = _CornerButtonFace(
            host, lambda armed: icons.corner_enhance_icon(self._enhance_look(), armed=armed))
        self._star.clicked.connect(lambda: self.triggered.emit(STAR if restore is None else RESTORE))
        self._trash.clicked.connect(lambda: self.triggered.emit(TRASH))
        self._enhance_button.clicked.connect(lambda: self.triggered.emit(ENHANCE))
        self._retip()

    def _enhance_look(self) -> str:
        if self._enhance == icons.ENHANCE_QUEUED and self._lit:
            return icons.ENHANCE_HELD
        return self._enhance or icons.ENHANCE_OPEN

    def _blink_once(self):
        self._lit = not self._lit
        self._enhance_button.redraw()

    def buttons(self) -> list[QPushButton]:
        return [self._star, self._trash, self._enhance_button]

    def show_for(self, *, favorite: bool, enhance: str | None, kind: str | None = None):
        self._available = True
        self._favorite = favorite
        self._enhance = enhance
        self._kind = kind or "item"
        self._redraw()

    def hide_all(self):
        self._available = False
        self._sync()

    def set_enhance(self, enhance: str | None):
        if enhance == self._enhance:
            return
        self._enhance = enhance
        self._redraw()

    def draw_at_the_huds_scale_again(self) -> None:
        for button in self.buttons():
            size_a_corner_button(button)
            button.redraw()
        if self._placed_in is not None:
            self.place(self._placed_in)

    def place(self, area: QRect):
        self._placed_in = QRect(area)
        inset, size = corner_inset(), corner_size()
        inner = area.adjusted(inset, inset, -inset, -inset)
        right = inner.right() - size + 1
        lower = inner.bottomLeft().y() - size + 1
        self._star.move(right, inner.top())
        self._trash.move(inner.left(), lower)
        self._enhance_button.move(right, lower)
        for button in self.buttons():
            button.raise_()

    def _redraw(self):
        for button in self.buttons():
            button.redraw()
        self._retip()
        self._sync()

    def _retip(self):
        favoring = "Unfavorite" if self._favorite else "Favorite"
        self._star.setToolTip(self._restore_tip or f"{favoring} this {self._kind}")
        self._trash.setToolTip(_DELETE_FOR_GOOD_TIP if self._restore_tip
                               else f"Delete this {self._kind}")
        if self._enhance is not None:
            self._enhance_button.setToolTip(_TIPS[self._enhance][0])

    def _sync(self):
        self._star.setVisible(self._available)
        self._trash.setVisible(self._available)
        self._enhance_button.setVisible(self._available and self._enhance is not None)
        self._enhance_button.setEnabled(self._enhance not in (icons.ENHANCE_HELD,
                                                              icons.ENHANCE_QUEUED))
        queued = self._available and self._enhance == icons.ENHANCE_QUEUED
        if queued and not self._blink.isActive():
            self._blink.start()
        elif not queued:
            self._blink.stop()
            self._lit = False
