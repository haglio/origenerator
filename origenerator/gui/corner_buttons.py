from __future__ import annotations

from typing import NamedTuple

from PyQt6.QtCore import QObject, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import QPushButton, QWidget
from shared_ui.palette import BLACK, as_rgba
from shared_ui.spacing import BUTTON_GAP, BUTTON_RADIUS, BUTTON_SIZE, GAP_SMALL

from origenerator import gallery
from origenerator.gui import icons

STAR = "star"
TRASH = "trash"
ENHANCE = "enhance"
RESTORE = "restore"

CORNER_SIZE = BUTTON_SIZE
CORNER_GAP = BUTTON_GAP
CORNER_INSET = GAP_SMALL
_GLYPH_SIZE = CORNER_SIZE - 8

GROUND_CSS = (
    f"QPushButton {{ background: {as_rgba(BLACK, 0.55)}; border: none; border-radius: {BUTTON_RADIUS}px; }}"
)

_DELETE_FOR_GOOD_TIP = "Delete permanently — remove it and its files for good"
_TIPS = {
    STAR: ("Favorite this item", "Unfavorite this item"),
    TRASH: ("Delete this item",),
    icons.ENHANCE_OPEN: ("Enhance this image (upscale + re-sample)",),
    icons.ENHANCE_HELD: (("Already enhanced at these settings — "
                          "change one to make a different version"),),
    icons.ENHANCE_MORE: ("Enhance again, at the settings now on the panel",),
}


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
        self.setFixedSize(CORNER_SIZE, CORNER_SIZE)
        self.setIconSize(QSize(_GLYPH_SIZE, _GLYPH_SIZE))
        self.setStyleSheet(GROUND_CSS)
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
    triggered = pyqtSignal(str)

    def __init__(self, host: QWidget, *, restore: RestoreOffer | None = None):
        super().__init__(host)
        self._restore_tip, can_restore = restore or (None, True)
        self._available = False
        self._favorite = False
        self._enhance: str | None = None
        self._star = _CornerButtonFace(
            host, lambda armed: icons.corner_star_icon(favorite=self._favorite, armed=armed)
            if restore is None
            else icons.corner_restore_icon(can_restore=can_restore, armed=armed),
            enabled=can_restore)
        self._trash = _CornerButtonFace(host, lambda armed: icons.corner_trash_icon(
            armed=armed))
        self._enhance_button = _CornerButtonFace(
            host, lambda armed: icons.corner_enhance_icon(
                self._enhance or icons.ENHANCE_OPEN, armed=armed))
        self._star.clicked.connect(lambda: self.triggered.emit(STAR if restore is None else RESTORE))
        self._trash.clicked.connect(lambda: self.triggered.emit(TRASH))
        self._enhance_button.clicked.connect(lambda: self.triggered.emit(ENHANCE))
        self._retip()

    def buttons(self) -> list[QPushButton]:
        return [self._star, self._trash, self._enhance_button]

    def show_for(self, *, favorite: bool, enhance: str | None):
        self._available = True
        self._favorite = favorite
        self._enhance = enhance
        self._redraw()

    def hide_all(self):
        self._available = False
        self._sync()

    def set_enhance(self, enhance: str | None):
        if enhance == self._enhance:
            return
        self._enhance = enhance
        self._redraw()

    def place(self, area: QRect):
        inner = area.adjusted(CORNER_INSET, CORNER_INSET,
                              -CORNER_INSET, -CORNER_INSET)
        right = inner.right() - CORNER_SIZE + 1
        lower = inner.bottomLeft().y() - CORNER_SIZE + 1
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
        self._star.setToolTip(self._restore_tip or _TIPS[STAR][1 if self._favorite else 0])
        self._trash.setToolTip(_DELETE_FOR_GOOD_TIP if self._restore_tip else _TIPS[TRASH][0])
        if self._enhance is not None:
            self._enhance_button.setToolTip(_TIPS[self._enhance][0])

    def _sync(self):
        self._star.setVisible(self._available)
        self._trash.setVisible(self._available)
        self._enhance_button.setVisible(self._available and self._enhance is not None)
        self._enhance_button.setEnabled(self._enhance != icons.ENHANCE_HELD)
