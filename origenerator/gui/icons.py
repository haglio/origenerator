"""The gallery's icons: shared glyphs, composed the way this app needs them.

The marks themselves live in :mod:`shared_ui.icons` now.  They used to be drawn
here, and Fun Time drew its own copies of the ones it shares -- which is how the
two apps ended up with microphones of different shapes on one screen.  What
stays here is what is genuinely this app's: which button wears which mark, what
color it wears it in, and the chips the badges sit on.

The toolbar-button icons each return a QIcon carrying a normal and a muted
"disabled" rendering (Qt swaps to the latter when a button is disabled).  The
recipe-level badges (:func:`level_badge_icon`) are lettered chips marking which
of workflow/model/LoRA a folder is; the media-type badges
(:func:`media_type_badge`) are corner chips marking a Recents tile as an image
or a video.

:func:`tab_close_icon` is the one mark that is neither drawn nor shared: it is
borrowed from the live style, so a button that closes tabs wears the very ✕ the
tabs themselves do.
"""

from functools import lru_cache

from PyQt6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor
from PyQt6.QtWidgets import QApplication, QStyle, QStyleOption
from PyQt6.QtCore import Qt, QRect, QRectF, QPointF

from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()

from shared_ui.colors import (
    TEXT_PRIMARY, BG_PRIMARY, BORDER_PANEL, BLUE, PINK, AMBER, GREEN, RED,
)
from shared_ui.icons import CANVAS, draw_glyph, glyph_icon, glyph_pixmap

_SIZE = int(CANVAS)  # drawn at the shared canvas, then scaled down on the button

# Hierarchy level badges. Every gallery folder above a settings leaf sits at one
# of these levels, and a small chip names which, so a tree row or a browser tile
# is self-describing without the reader counting indentation. The recipe levels
# take a lettered chip in their own color; the two media roots take the play and
# photo glyphs their own items wear, on a neutral chip — they are the shape of
# the library rather than a step of a recipe, and the color says so.
LEVEL_LABELS = {
    "workflow": "Workflow", "model": "Model", "lora": "LoRA",
    "source_image": "Source Image",
    "image": "Images", "video": "Videos",
}
_LEVEL_BADGES = {
    "workflow": ("W", BLUE), "model": ("M", PINK), "lora": ("L", AMBER),
    "source_image": ("I", GREEN),
}
_MEDIA_LEVEL_CHIP = BORDER_PANEL  # Images / Videos: the library's shape, not a recipe's

# The Recents shelf mixes images and videos in one flow, so each tile wears a
# small corner badge naming its kind. A white glyph on a translucent dark chip,
# so it reads over a thumbnail of any color.
_BADGE_CHIP = QColor(0, 0, 0, 160)
_BADGE_GLYPH = QColor(255, 255, 255)
_BADGE_DISPLAY = 22  # the badge's on-screen size, in px

# Every chip carries its mark at one size, whichever mark it is. A star badge and
# a media badge can sit on the same tile, and the two only read as one system if
# they are drawn to one scale — which they were not while each glyph was sized
# for itself.
_CHIP_GLYPH = 44
_CHIP_INSET = (_SIZE - _CHIP_GLYPH) / 2

# A starred item's star, in the green Fun Time paints its favorite ★ with: one
# color means "bookmarked" across both apps, so a star learned in one reads in
# the other. Worn by every star that says something IS starred — the tile's
# corner badge and a starred folder's row alike. The plus marking an enhanced
# tile is yellow (AMBER, this palette's yellow): green is spoken for and the two
# badges can sit on one tile, and blue is genau's across this family.
_STAR_GLYPH = GREEN

_REROLL_GLYPH = QColor(255, 255, 255)

# The re-roll glyph is a composite: the media mark up and to the left, leaving
# the bottom-right corner free for the small regenerate arrow that modifies it.
_REROLL_MEDIA = 34
_REROLL_MEDIA_AT = 1


def back_icon() -> QIcon:
    return glyph_icon("chevron_left", size=_SIZE)


def forward_icon() -> QIcon:
    return glyph_icon("chevron_right", size=_SIZE)


def undo_icon() -> QIcon:
    """A circular arrow curling back, its head to the left — undo."""
    return glyph_icon("undo_arrow", size=_SIZE)


def redo_icon() -> QIcon:
    """Undo's mirror image, head to the right — redo. The pair is a mirror on
    purpose: side by side in the bank, two arrowheads pointing opposite ways say
    which is which faster than any difference in the arc could."""
    return glyph_icon("redo_arrow", size=_SIZE)


def autoloop_icon() -> QIcon:
    """A lightning bolt bursting out of a ring — auto-generate: re-roll this
    folder, and keep re-rolling it.

    The ring is the "keep going" and the bolt is the "by itself". It sits three
    buttons from undo, which is a ring too, so the bolt has to be what the eye
    lands on: it is a solid where undo and redo are open arcs, and it breaks out
    of its ring at both ends where theirs merely stops short of an arrowhead.
    """
    return glyph_icon("bolt_ring", size=_SIZE)


def slideshow_icon() -> QIcon:
    """A play triangle in a frame — play this folder as a fullscreen slideshow."""
    return glyph_icon("slideshow", size=_SIZE)


def enhance_icon() -> QIcon:
    """A bold plus — enhance (upscale + re-sample) images.

    Yellow, the very plus an enhanced tile wears in its corner
    (:func:`enhance_badge`), so the button and the mark it leaves behind are one
    symbol in one color — and so it can't be read as a star, which is what green
    means across this family (:data:`_STAR_GLYPH`)."""
    return glyph_icon("plus", color=AMBER, size=_SIZE)


def mic_icon() -> QIcon:
    """A microphone — speak a prompt edit.

    The family's one microphone: Fun Time's dashboard paints this same drawing
    into its voice panel, so the two apps side by side show one control rather
    than two marks that merely mean the same thing."""
    return glyph_icon("mic", size=_SIZE)


def stroke_icon() -> QIcon:
    """A sine wave — the one OSR2 switch. It wears the waveform whichever source
    is driving, because from the outside they are the same thing: motion the app
    is sending the device."""
    return glyph_icon("wave", size=_SIZE)


def audio_icon() -> QIcon:
    """A speaker sounding off — the audio bed's on/off switch."""
    return glyph_icon("speaker", size=_SIZE)


def trash_icon(*, color=None) -> QIcon:
    """A trash can — the Trash shelf's caret marker, and the Delete button that
    fills it. One glyph for both ends of a deletion, so the shelf reads as where
    that button's items go."""
    return glyph_icon("trash", color=color, size=_SIZE)


def delete_icon() -> QIcon:
    """The button-bank trash can, in red — the one control in the bank that
    takes something away, and the only one worth stopping on before clicking."""
    return trash_icon(color=RED)


def star_icon(*, filled: bool) -> QIcon:
    """A five-pointed star — solid when the folder is starred, an outline when
    not, so the hover control shows the state it will toggle.

    A starred one is green (:data:`_STAR_GLYPH`), the color the corner badge and
    Fun Time's favorite ★ both wear; the outline stays the chrome's own gray,
    because it is an offer to star rather than a thing that is starred. The
    button bank's Star wears the filled one, so the control and the mark it
    leaves on a tile are one symbol in one color."""
    if filled:
        return glyph_icon("star", color=_STAR_GLYPH, size=_SIZE)
    return glyph_icon("star_outline", size=_SIZE)


def clock_icon() -> QIcon:
    """A clock face — the Recents shelf's caret marker, drawn to match the star."""
    return glyph_icon("clock", size=_SIZE)


def flask_icon() -> QIcon:
    """An Erlenmeyer flask — the Experiments shelf's caret marker."""
    return glyph_icon("flask", size=_SIZE)


def custom_folder_icon() -> QIcon:
    """A folder — the caret marker on a folder the user composed, and the toolbar
    button that composes one out of the picked folders."""
    return glyph_icon("folder", size=_SIZE)


@lru_cache(maxsize=None)
def experiment_verdict_icon(verdict: str) -> QIcon:
    """An experiment tile's review hover-buttons: a check ("up" — keep it, it
    joins the gallery) or a cross ("down" — reject it and teach the experimenter
    what to avoid). White line art on the buttons' own translucent chip, like the
    per-seed re-roll controls."""
    return QIcon(glyph_pixmap("check" if verdict == "up" else "cross",
                              _SIZE, _REROLL_GLYPH))


@lru_cache(maxsize=None)
def recovery_action_icon(action: str) -> QIcon:
    """A Trash-shelf tile's review hover-buttons: a circular arrow back
    ("restore" — the item and its files return to where they were) or a trash can
    ("purge" — end it now instead of waiting out its window). White line art on
    the buttons' own translucent chip, like the experiment verdict controls."""
    name = "undo_arrow" if action == "restore" else "trash"
    return QIcon(glyph_pixmap(name, _SIZE, _REROLL_GLYPH))


@lru_cache(maxsize=None)
def media_type_badge(media_type: str) -> QPixmap:
    """A small corner badge marking a Recents tile as an image or a video.

    A white glyph — a play triangle for a video, a framed photo for an image — on
    a translucent dark chip, so it reads over a thumbnail of any color. Cached and
    pre-scaled to its on-screen size; the same two badges decorate every tile.
    """
    glyph = "play" if media_type == "video" else "photo"
    return _display_size(_render_chip(_BADGE_CHIP, glyph, _BADGE_GLYPH))


@lru_cache(maxsize=None)
def star_badge() -> QPixmap:
    """A corner badge marking a starred image or video.

    A filled green star on the translucent dark chip the media-type badges use,
    so a bookmarked item reads at a glance over a thumbnail of any color. Cached
    and pre-scaled — the one badge decorates every starred tile."""
    return _display_size(_render_chip(_BADGE_CHIP, "star", _STAR_GLYPH))


@lru_cache(maxsize=None)
def enhance_badge() -> QPixmap:
    """A corner badge marking an enhanced image: a yellow plus on the translucent
    chip the other badges use, so an upscaled/re-sampled result reads at a
    glance over a thumbnail of any color. Yellow because green is the star's
    (see :data:`_STAR_GLYPH`) and the two badges share a tile, and because blue
    belongs to genau across this family. Cached and pre-scaled — the one badge
    decorates every enhanced tile."""
    return _display_size(_render_chip(_BADGE_CHIP, "plus", AMBER))


def _display_size(pixmap: QPixmap) -> QPixmap:
    """A rendered chip scaled down to the size a tile shows it at."""
    return pixmap.scaled(
        _BADGE_DISPLAY, _BADGE_DISPLAY,
        Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
    )


@lru_cache(maxsize=None)
def reroll_seed_icon(media_type: str) -> QIcon:
    """A thumbnail hover-button glyph: a regenerate ring around a small play/photo
    mark — "re-roll this video" (its motion) or "this image" (its start frame).

    White line art; the button paints its own translucent chip behind it, so the
    glyph reads over a thumbnail of any color. The two differ by their inner mark,
    so a video seed control is never mistaken for an image seed one.
    """
    pixmap = QPixmap(_SIZE, _SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    # The media identity, drawn large so video vs image reads at a glance...
    draw_glyph(painter, "play" if media_type == "video" else "photo", _REROLL_GLYPH,
               size=_REROLL_MEDIA, x=_REROLL_MEDIA_AT, y=_REROLL_MEDIA_AT)
    _draw_regen_badge(painter)
    painter.end()
    return QIcon(pixmap)


def _draw_regen_badge(painter: QPainter):
    """A small circular arrow in the bottom-right — the 're-roll' modifier over
    the media glyph, so the control reads as 'regenerate this' not 'play this'."""
    pen = QPen(_REROLL_GLYPH)
    pen.setWidthF(3.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(QRectF(29, 29, 15, 15), 35 * 16, 250 * 16)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_REROLL_GLYPH)
    painter.drawPolygon(QPointF(45, 33), QPointF(39, 31), QPointF(41, 38))  # arrowhead


def tab_close_icon(widget=None) -> QIcon:
    """The close mark the live style paints on a closable tab, at rest.

    Borrowed rather than drawn, so every control that closes a tab wears one ✕ —
    the tabs' own, and the config pane's "All" beside them. A hand-drawn glyph, or
    the ✕ text character, is a second spelling of the same act.

    Built the way QTabBar builds its own close button — the widget's palette, and
    the auto-raise a flat little button paints with — but always in the resting
    state, never the selected one the platform style turns red. Not cached: it
    follows the style, which a theme change can swap under a running app.
    """
    style = (widget.style() if widget is not None else QApplication.style())
    size = style.pixelMetric(QStyle.PixelMetric.PM_TabCloseIndicatorWidth)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    option = QStyleOption()
    if widget is not None:
        option.initFrom(widget)
    option.rect = QRect(0, 0, size, size)
    option.state = QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_AutoRaise
    style.drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorTabClose, option, painter,
                        widget)
    painter.end()
    return QIcon(pixmap)


@lru_cache(maxsize=None)
def level_badge_icon(level: str) -> QIcon:
    """The chip marking a folder's place in the hierarchy (see LEVEL_LABELS).

    A lettered chip in its own color for the recipe levels; for the two media
    roots, the play / photo glyph their own items already wear, on a neutral
    chip — same shape and size as the letters, so the roots read as part of the
    same system, but plainly not a fifth step of a recipe.

    Cached: the same few chips decorate many tree rows and tiles, so they're
    rendered once and shared rather than re-drawn per folder.
    """
    icon = QIcon()
    glyph = {"video": "play", "image": "photo"}.get(level)
    if glyph is not None:
        icon.addPixmap(_render_chip(_MEDIA_LEVEL_CHIP, glyph, _BADGE_GLYPH))
        return icon
    letter, color = _LEVEL_BADGES[level]
    icon.addPixmap(_render_badge(letter, color))
    return icon


def _render_chip(chip, glyph: str, ink) -> QPixmap:
    """A rounded chip filled with *chip*, carrying *glyph* in *ink*."""
    return _chip_pixmap(chip, lambda painter: draw_glyph(
        painter, glyph, ink, size=_CHIP_GLYPH, x=_CHIP_INSET, y=_CHIP_INSET))


def _chip_pixmap(color, draw) -> QPixmap:
    """A rounded chip filled with ``color``, with ``draw`` painting its mark."""
    pixmap = QPixmap(_SIZE, _SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawRoundedRect(QRectF(3, 3, _SIZE - 6, _SIZE - 6), 12, 12)
    draw(painter)
    painter.end()
    return pixmap


def _render_badge(letter: str, color) -> QPixmap:
    """A chip with ``letter`` centered in readable contrast — dark on a light
    chip, light on a saturated one."""
    def draw(painter: QPainter):
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(30)
        painter.setFont(font)
        painter.setPen(_readable_on(color))
        painter.drawText(QRectF(0, 0, _SIZE, _SIZE),
                         Qt.AlignmentFlag.AlignCenter, letter)

    return _chip_pixmap(color, draw)


def _readable_on(color):
    """Near-black or the primary text color, whichever reads on ``color``."""
    luminance = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
    return BG_PRIMARY if luminance > 150 else TEXT_PRIMARY
