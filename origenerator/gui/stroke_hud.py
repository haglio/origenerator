"""The OSR2 stroke's on-screen presence: one key cluster, one caption, shared.

The stroke driver is app-global — the device shouldn't care which window is in
front — so every surface that can drive it (the gallery window, the plain
fullscreen viewer, the folder slideshow, the auto-generate slideshow) answers
the same keys and shows the same standing line, through these helpers. The keys
are genau's own, so the muscle memory carries: Space starts/stops, J/L speed,
7/9 amplitude, U/O center, I shape.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel

# The legend shown while the stroke is off — the one visible invitation that
# the controls exist at all.
STROKE_KEY_LEGEND = "Space drives · J/L speed · 7/9 travel · U/O center · I shape"

# The translucent overlay style every fullscreen caption shares.
CAPTION_CSS = (
    "color: white; background: rgba(0, 0, 0, 140);"
    " padding: 4px 10px; border-radius: 4px;"
)


def apply_stroke_key(stroke, key) -> bool:
    """Route one of genau's stroke keys to ``stroke``; ``False`` for any other
    key (or with no driver wired), so the caller falls through to its own
    handling."""
    if stroke is None:
        return False
    if key == Qt.Key.Key_Space:
        stroke.toggle()
    elif key == Qt.Key.Key_J:
        stroke.adjust_speed(-5)
    elif key == Qt.Key.Key_L:
        stroke.adjust_speed(5)
    elif key == Qt.Key.Key_7:
        stroke.adjust_amplitude(-10)
    elif key == Qt.Key.Key_9:
        stroke.adjust_amplitude(10)
    elif key == Qt.Key.Key_U:
        stroke.adjust_center(-5)
    elif key == Qt.Key.Key_O:
        stroke.adjust_center(5)
    elif key == Qt.Key.Key_I:
        stroke.cycle_shape()
    else:
        return False
    return True


def stroke_caption_text(stroke) -> str:
    """The standing caption: the stroke's state, plus the key legend while it's
    off — the invitation to press Space."""
    text = stroke.status_text()
    if not stroke.active:
        text += f"   ·   {STROKE_KEY_LEGEND}"
    return text


class StrokeCaption(QLabel):
    """The standing OSR2 line along the top of a fullscreen view.

    Always visible: an idle line naming its keys is the only way the stroke
    controls are discoverable at all. The owning view calls :meth:`refresh`
    after routing a stroke key and :meth:`reposition` from its resizeEvent.
    """

    def __init__(self, stroke, parent):
        super().__init__(parent)
        self._stroke = stroke
        self.setStyleSheet(CAPTION_CSS)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.refresh()

    def refresh(self) -> None:
        self.setText(stroke_caption_text(self._stroke))
        self.reposition()
        self.raise_()
        self.show()

    def reposition(self) -> None:
        self.adjustSize()
        parent = self.parentWidget()
        if parent is not None:
            self.move(max(0, (parent.width() - self.width()) // 2), 24)
