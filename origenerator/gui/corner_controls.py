"""The controls a generation's picture wears in its own corners.

A thumbnail in the browser pane and the preview in a config tab are showing the
same thing, so they offer the same three acts on it, in the same three corners:
bookmark it (top left), bin it (bottom left), enhance it (bottom right). Learn
them once and they are in the same places wherever a generation is on screen.

Each mark is the state and the button at once. A filled green star IS the
bookmark, and pressing it is what takes the bookmark away; the yellow plus IS
the enhancement the image holds. That is why the badges these replaced are gone
rather than sitting beside them: a picture can no longer carry a badge saying
one thing next to a control doing another, because there is only the one mark.

Two of them therefore stay up whenever they have something to report — a starred
item keeps its star and an enhanced one its plus, cursor or no cursor — and the
rest appear on hover, so a resting wall of thumbnails is pictures rather than
chrome.
"""

from PyQt6.QtWidgets import QPushButton, QWidget
from PyQt6.QtCore import QObject, QRect, QSize, Qt, pyqtSignal

from origenerator import gallery
from origenerator.gui import icons

STAR = "star"
TRASH = "trash"
ENHANCE = "enhance"

# The geometry the browser pane's other hover controls (a tile's per-seed
# re-rolls, a review shelf's keep/reject) already use, shared so the star can sit
# in a row with them along the top of a tile and read as one bank rather than as
# a stray chip beside two matching ones.
CORNER_SIZE = 28
CORNER_GAP = 4
# How far a control sits inside the picture it is laid over. Small: the corners
# of the picture are what these mark, and a control floated well inside one
# reads as sitting ON the image rather than as belonging to its corner.
CORNER_INSET = 2
_GLYPH_SIZE = CORNER_SIZE - 8

# The translucent chip every hover control sits on, so white or colored line art
# reads over a thumbnail of any color.
CHIP_CSS = (
    "QPushButton { background: rgba(0,0,0,0.55); border: none; border-radius: 6px; }"
)

_TIPS = {
    STAR: ("Star this item", "Unstar this item"),
    TRASH: ("Delete this item",),
    icons.ENHANCE_OPEN: ("Enhance this image (upscale + re-sample)",),
    icons.ENHANCE_HELD: ("Already enhanced at these settings — "
                         "change one to make a different version",),
    icons.ENHANCE_MORE: ("Enhance again, at the settings now on the panel",),
}


def enhance_state(row: dict, settings) -> str | None:
    """Which of :mod:`~origenerator.gui.icons`' three readings the enhance corner
    shows for ``row`` at ``settings`` — or ``None`` for a picture the enhancer
    cannot take at all, which grows no plus.

    The middle answer is the one worth having: an image that already holds an
    enhancement is not finished with the enhancer, it is finished with *these
    settings*. So the corner says "you have this one" only while the panel would
    reproduce what is already there, and goes back to offering another the moment
    a knob moves — which is the same question the version list's ``+ Enhance``
    card and the button bank's Enhance both answer
    (:func:`~origenerator.gallery.enhance.level_matching_settings`).
    """
    if not gallery.is_enhanceable_row(row):
        return None
    if not gallery.is_enhanced_row(row):
        return icons.ENHANCE_OPEN
    held = gallery.level_matching_settings(row, settings)
    return icons.ENHANCE_HELD if held is not None else icons.ENHANCE_MORE


class _CornerButton(QPushButton):
    """One corner's chip, which re-draws itself while the cursor is on it.

    Qt's own hover state would do this through a stylesheet, but what changes
    here is the *mark* rather than the button — a trash can going red, a star
    going light gray — so the icon is swapped on the crossing instead.
    """

    def __init__(self, host: QWidget, render, *, native: bool = False):
        super().__init__(host)
        self._render = render  # (armed) -> QIcon
        self._armed = False
        if native:
            # A video plays on a native surface, which an ordinary sibling widget
            # cannot paint over -- the same reason the preview's notice plate is
            # native (see :mod:`origenerator.gui.preview_widget`). Only asked for
            # where a video can turn up: a native window per button is real cost,
            # and a wall of thumbnails would be paying it dozens of times over.
            self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setFixedSize(CORNER_SIZE, CORNER_SIZE)
        self.setIconSize(QSize(_GLYPH_SIZE, _GLYPH_SIZE))
        self.setStyleSheet(CHIP_CSS)
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


class CornerControls(QObject):
    """The three controls laid over one host widget's picture.

    Passive about hover: the host says when the cursor is over it
    (:meth:`set_revealed`) and where the picture currently is (:meth:`place`),
    because only the host knows — a thumbnail's picture is a fixed rectangle and
    a preview's moves with every resize and every change of aspect ratio.
    """

    triggered = pyqtSignal(str)  # STAR / TRASH / ENHANCE

    def __init__(self, host: QWidget, *, native: bool = False):
        super().__init__(host)
        self._available = False   # is there a saved generation here to act on?
        self._revealed = False    # is the cursor over the host?
        self._starred = False
        self._enhance: str | None = None
        self._star = _CornerButton(
            host, lambda armed: icons.corner_star_icon(starred=self._starred,
                                                       armed=armed), native=native)
        self._trash = _CornerButton(host, lambda armed: icons.corner_trash_icon(
            armed=armed), native=native)
        self._enhance_button = _CornerButton(
            host, lambda armed: icons.corner_enhance_icon(
                self._enhance or icons.ENHANCE_OPEN, armed=armed), native=native)
        self._star.clicked.connect(lambda: self.triggered.emit(STAR))
        self._trash.clicked.connect(lambda: self.triggered.emit(TRASH))
        self._enhance_button.clicked.connect(lambda: self.triggered.emit(ENHANCE))
        self._retip()

    def buttons(self) -> list[QPushButton]:
        """The three, for a host that has to know its own children — telling a
        cursor that left for a button from one that left the picture entirely."""
        return [self._star, self._trash, self._enhance_button]

    def show_for(self, *, starred: bool, enhance: str | None):
        """Arm the controls for the generation now on show, in its current state."""
        self._available = True
        self._starred = starred
        self._enhance = enhance
        self._redraw()

    def hide_all(self):
        """Nothing here to act on — a live frame, a message, an empty pane."""
        self._available = False
        self._sync()

    def set_starred(self, starred: bool):
        """Follow a bookmark toggled from anywhere: this corner, the menu, the
        button bank. Idempotent, so a rebuild that re-asserts the same state
        doesn't redraw."""
        if starred == self._starred:
            return
        self._starred = starred
        self._redraw()

    def set_enhance(self, enhance: str | None):
        """Follow the enhance corner's reading changing under the item — which a
        turn of the Enhance panel's knobs does to every picture on screen at
        once, without any of them being touched."""
        if enhance == self._enhance:
            return
        self._enhance = enhance
        self._redraw()

    def set_revealed(self, revealed: bool):
        """The cursor arrived over (or left) the host's picture."""
        if revealed == self._revealed:
            return
        self._revealed = revealed
        self._sync()

    def place(self, picture: QRect):
        """Put each control in its own corner of ``picture``, in host coordinates."""
        inner = picture.adjusted(CORNER_INSET, CORNER_INSET,
                                 -CORNER_INSET, -CORNER_INSET)
        self._star.move(inner.left(), inner.top())
        self._trash.move(inner.left(), inner.bottom() - CORNER_SIZE + 1)
        self._enhance_button.move(inner.right() - CORNER_SIZE + 1,
                                  inner.bottom() - CORNER_SIZE + 1)
        for button in self.buttons():
            button.raise_()

    def _redraw(self):
        for button in self.buttons():
            button.redraw()
        self._retip()
        self._sync()

    def _retip(self):
        self._star.setToolTip(_TIPS[STAR][1 if self._starred else 0])
        self._trash.setToolTip(_TIPS[TRASH][0])
        if self._enhance is not None:
            self._enhance_button.setToolTip(_TIPS[self._enhance][0])

    def _sync(self):
        """Show each control per what it has to say and whether the host is hovered.

        A control that is reporting a state stays up on its own — that is the
        whole of what the star and plus badges used to do, and dropping it on
        mouse-out would make a wall of thumbnails stop saying which of them are
        bookmarked. The rest are offers, and an offer is only worth the space
        while the cursor is on the item it's about.
        """
        self._star.setVisible(self._available and (self._starred or self._revealed))
        self._trash.setVisible(self._available and self._revealed)
        holds = self._enhance in (icons.ENHANCE_HELD, icons.ENHANCE_MORE)
        self._enhance_button.setVisible(
            self._available and self._enhance is not None
            and (holds or self._revealed))
        # The solid plus is a finished statement rather than an offer: this image
        # already holds the very version the panel describes, so pressing would
        # spend a generation arriving at the picture that is already there. Turn
        # any knob and it becomes an offer again.
        self._enhance_button.setEnabled(self._enhance != icons.ENHANCE_HELD)
