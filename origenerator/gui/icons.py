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

:func:`recent_mark_icon` is the dot at the start of the row of a folder lately
worked in, drawn here because it is a color saying one thing, not a mark anyone
reads.

The corner controls (:func:`corner_star_icon`, :func:`corner_trash_icon`,
:func:`corner_enhance_icon`) are the marks a generation's picture wears in its
own corners, wherever it is shown.  Each is drawn twice -- at rest, and armed
with the cursor on it -- because each is a badge and a button at once: the mark
says which state the item is in, and pressing it is what changes that state.

:func:`tab_close_icon` is the one mark that is neither drawn nor shared: it is
borrowed from the live style, so a button that closes tabs wears the very ✕ the
tabs themselves do.
"""
from __future__ import annotations

from functools import cache

from PyQt6.QtCore import QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QApplication, QStyle, QStyleOption
from shared_ui.colors import (
    AMBER,
    BG_PRIMARY,
    BLUE,
    GREEN,
    MAGENTA,
    RED,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)
from shared_ui.icon_geometry import shapes_of
from shared_ui.icons import CANVAS, draw_glyph, glyph_icon, glyph_pixmap

from origenerator.gallery.collection import (
    COLLECTION_LABELS,
    EXPERIMENTS_KEY,
    FAVORITES_KEY,
    RECENTS_KEY,
    REQUESTS_KEY,
    TRASH_KEY,
)
from origenerator.gallery.groups import MediaGroup, SettingsGroup, folder_level, rows_under
from origenerator.gallery.labels import MEDIA_LABELS
from origenerator.gallery.output import media_type_of_row
from origenerator.gallery.sides import BOTH, LANDSCAPE, PORTRAIT
from origenerator.media import MediaType

_SIZE = int(CANVAS)  # drawn at the shared canvas, then scaled down on the button

# Hierarchy level badges. Every gallery folder above a settings leaf sits at one
# of these levels, and a small lettered chip in the level's own color names
# which, so a tree row or a browser tile is self-describing without the reader
# counting indentation.
LEVEL_LABELS = {
    "workflow": "Workflow", "model": "Model", "lora": "LoRA",
    "source_image": "Source Image",
}
_LEVEL_BADGES = {
    "workflow": ("W", BLUE), "model": ("M", MAGENTA), "lora": ("L", AMBER),
    "source_image": ("I", GREEN),
}

# The Recents collection mixes images and videos in one flow, so each tile wears a
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

# A favorited item's star, in the green Fun Time paints its favorite ★ with: one
# color means "bookmarked" across both apps, so a star learned in one reads in
# the other. Worn by every star that says something IS favorited — the tile's
# corner badge and a favorited folder's row alike. The plus marking an enhanced
# tile is yellow (AMBER, this palette's yellow): green is spoken for and the two
# badges can sit on one tile, and blue is genau's across this family.
_STAR_GLYPH = GREEN
_REROLL_GLYPH = QColor(255, 255, 255)

# The re-roll glyph is a composite: the media mark up and to the left, leaving
# the lower-right corner free for the small regenerate arrow that modifies it.
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
    return glyph_icon("bolt", size=_SIZE)


def shield_icon() -> QIcon:
    return glyph_icon("shield", size=_SIZE)


def slideshow_icon() -> QIcon:
    """A play triangle in a frame — play this folder as a fullscreen slideshow."""
    return glyph_icon("slideshow", size=_SIZE)


def enhance_icon() -> QIcon:
    """A bold plus — enhance (upscale + re-sample) images.

    Yellow, the very plus a picture wears in its enhance corner once it holds one
    (:func:`corner_enhance_icon`), so the button and the mark it leaves are
    one symbol in one color — and so it can't be read as a star, which is what
    green means across this family (:data:`_STAR_GLYPH`)."""
    return glyph_icon("plus", color=AMBER, size=_SIZE)


def mic_icon() -> QIcon:
    """A microphone — speak a prompt edit.

    The family's one microphone: Fun Time's dashboard paints this same drawing
    into its voice panel, so the two apps side by side show one control rather
    than two marks that merely mean the same thing."""
    return glyph_icon("mic", size=_SIZE)


def audio_icon() -> QIcon:
    """A speaker sounding off — the audio bed's on/off switch."""
    return glyph_icon("speaker", size=_SIZE)


def trash_icon(*, color=None) -> QIcon:
    """A trash can — the Trash collection's mark, and the Delete button that fills
    it. One glyph for both ends of a deletion, so the collection reads as where that
    button's items go."""
    return glyph_icon("trash", color=color, size=_SIZE)


def delete_icon() -> QIcon:
    """The button-bank trash can, in red — the one control in the bank that
    takes something away, and the only one worth stopping on before clicking."""
    return trash_icon(color=RED)


def star_icon(*, filled: bool) -> QIcon:
    """A five-pointed star — solid when the folder is favorited, an outline when
    not, so the hover control shows the state it will toggle.

    A favorited one is green (:data:`_STAR_GLYPH`), the color the corner badge and
    Fun Time's favorite ★ both wear; the outline stays the chrome's own gray,
    because it is an offer to favorite rather than a thing that is favorited. The
    button bank's Favorite wears the filled one, so the control and the mark it
    leaves on a tile are one symbol in one color."""
    if filled:
        icon = glyph_icon("star", color=_STAR_GLYPH, size=_SIZE)
        icon.addPixmap(_painted(_ringed_star), QIcon.Mode.Selected)
        return icon
    return glyph_icon("star_outline", size=_SIZE)


_RING_WIDTH = 3.0


def _ringed_star(painter: QPainter):
    (star,) = shapes_of("star")
    pen = QPen(TEXT_PRIMARY)
    pen.setWidthF(2 * _RING_WIDTH)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(TEXT_PRIMARY)
    painter.drawPolygon(*(QPointF(x, y) for x, y in star.points))
    draw_glyph(painter, "star", _STAR_GLYPH, size=_SIZE)


@cache
def thumbs_up_icon() -> QIcon:
    canvas = QPixmap(_SIZE, _SIZE)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(_SIZE / 24, _SIZE / 24)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(TEXT_PRIMARY)
    painter.drawRoundedRect(QRectF(1.5, 10, 4, 12), 0.8, 0.8)
    painter.drawPath(_thumb_and_fist())
    painter.end()
    return QIcon(canvas)


def _thumb_and_fist() -> QPainterPath:
    hand = QPainterPath(QPointF(7, 11))
    hand.lineTo(11.2, 3.2)
    hand.quadTo(12.2, 1.6, 13.6, 2.4)
    hand.quadTo(15, 3.4, 14.5, 5.5)
    hand.lineTo(13.4, 9.5)
    hand.lineTo(20, 9.5)
    hand.quadTo(22.4, 9.6, 22.2, 12)
    hand.lineTo(20.6, 19.8)
    hand.quadTo(20.1, 22, 17.8, 22)
    hand.lineTo(9, 22)
    hand.quadTo(7, 22, 7, 20)
    hand.closeSubpath()
    return hand


@cache
def unmarked_icon() -> QIcon:
    canvas = QPixmap(_SIZE, _SIZE)
    canvas.fill(Qt.GlobalColor.transparent)
    return QIcon(canvas)


def latest_icon() -> QIcon:
    return glyph_icon("latest", size=_SIZE)


def flask_icon() -> QIcon:
    return glyph_icon("flask", size=_SIZE)


@cache
def collection_icon(collection: str) -> QIcon:
    return {
        RECENTS_KEY: latest_icon, FAVORITES_KEY: lambda: star_icon(filled=True),
        EXPERIMENTS_KEY: flask_icon, REQUESTS_KEY: mic_icon, TRASH_KEY: trash_icon,
    }[collection]()


def collection_badge(collection: str) -> tuple[QIcon, str]:
    return collection_icon(collection), COLLECTION_LABELS[collection]


def all_icon() -> QIcon:
    return glyph_icon("database", size=_SIZE)


def custom_folder_icon() -> QIcon:
    """A folder — the mark on a folder the user composed, and the toolbar button
    that composes one out of the picked folders."""
    return glyph_icon("folder", size=_SIZE)


# How far the lately-worked-in dot sits inside its canvas, so the soft edge it is
# scaled down to has somewhere to fall rather than being clipped at the border.
_MARK_INSET = 3.0


@cache
def recent_mark_icon() -> QIcon:
    """A filled dot — worn at the start of the row of a folder lately worked in.

    A dot rather than a glyph, in the family's one accent color: it says a
    folder is one of the few you were last in and nothing else, and a mark that
    says one thing should not look like something you can read. Drawn at the
    shared canvas and scaled down where it is painted, so it stays a smooth disc
    at whatever size the row gives it; inset a little so that scaling has the
    room its soft edge needs.
    """
    icon = QIcon(_painted(_disc(BLUE)))
    icon.addPixmap(_painted(_disc(TEXT_PRIMARY)), QIcon.Mode.Selected)
    return icon


def _disc(color):
    def draw(painter: QPainter):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QRectF(_MARK_INSET, _MARK_INSET,
                                   _SIZE - 2 * _MARK_INSET, _SIZE - 2 * _MARK_INSET))

    return draw


@cache
def experiment_verdict_icon(verdict: str) -> QIcon:
    """An experiment tile's review hover-buttons: a check ("up" — keep it, it
    joins the gallery) or a cross ("down" — reject it and teach the experimenter
    what to avoid). White line art on the buttons' own translucent chip, like the
    per-seed re-roll controls."""
    return QIcon(glyph_pixmap("check" if verdict == "up" else "cross",
                              _SIZE, _REROLL_GLYPH))


@cache
def recovery_action_icon(action: str) -> QIcon:
    """A Trash-collection tile's review hover-buttons: a circular arrow back
    ("restore" — the item and its files return to where they were) or a trash can
    ("purge" — end it for good; nothing else empties the bin). White line art on
    the buttons' own translucent chip, like the experiment verdict controls."""
    name = "undo_arrow" if action == "restore" else "trash"
    return QIcon(glyph_pixmap(name, _SIZE, _REROLL_GLYPH))


@cache
def media_type_badge(media_type: str) -> QPixmap:
    """A small corner badge marking a Recents tile as an image or a video.

    A white glyph — a play triangle for a video, a framed photo for an image — on
    a translucent dark chip, so it reads over a thumbnail of any color. Cached and
    pre-scaled to its on-screen size; the same two badges decorate every tile.
    """
    glyph = "play" if media_type == MediaType.VIDEO else "photo"
    return _display_size(_render_chip(_BADGE_CHIP, glyph, _BADGE_GLYPH))


@cache
def media_type_icon(media_type: str) -> QIcon:
    """The same play/photo mark as :func:`media_type_badge`, bare.

    The badge sits over a thumbnail, so it needs its dark chip to read against
    any picture; this one sits in a row of text — a config tab's label, where it
    stands in for the thumbnail a tab has no result to show yet, or the row of a
    folder of images or videos — so the chip would be a black square among words.
    """
    return glyph_icon("play" if media_type == MediaType.VIDEO else "photo", size=_SIZE)


# --- the shape a side of the table of contents holds ------------------------

MARK_BESIDE_A_WORD = 15  # on-screen size, for a mark that sits level with a word
_SIDE_MARKS = {PORTRAIT: PORTRAIT, LANDSCAPE: LANDSCAPE, BOTH: "portrait_and_landscape"}


@cache
def side_mark(side: str, size: int = MARK_BESIDE_A_WORD) -> QPixmap:
    return glyph_pixmap(_SIDE_MARKS[side], size, TEXT_PRIMARY)


@cache
def separate_mark(size: int) -> QPixmap:
    return glyph_pixmap("portrait_beside_landscape", size, TEXT_PRIMARY)


# --- the controls a picture wears in its corners --------------------------

# What the plus in a picture's lower-right corner is saying. The three are the
# whole of what the enhancer can be up to about one image; a picture it cannot
# take at all (a video, or a run with no file) shows no plus.
ENHANCE_OPEN = "open"   # nothing made of it yet: the offer of a first one
ENHANCE_HELD = "held"   # it already holds the very version these settings make
ENHANCE_MORE = "more"   # it holds one, and these settings would make another

# A corner control at rest is there without shouting; under the cursor it goes
# the light gray that says "this is a button" — whatever it is filled with, so
# the arming and the state it reports stay two separate readings of one mark.
_CORNER_REST = TEXT_MUTED
_CORNER_ARMED = TEXT_SECONDARY
# The mark is drawn a little inside its cell rather than filling it, which is what
# leaves the enhance corner room to shift a second copy of itself down and right
# without running off the canvas. _ENHANCE_SHADOW is that shift: far enough to
# show as a shadow at the size a corner is drawn at, and no further, since past
# the margin it stops being under the mark and starts being beside it.
_CORNER_MARK = 40.0
_CORNER_MARK_AT = 4.0
_ENHANCE_SHADOW = 5.0


@cache
def corner_star_icon(*, favorite: bool, armed: bool) -> QIcon:
    """The star in a picture's top-left corner: bookmark it, or take the
    bookmark away.

    Filled and green once it is bookmarked — the green Fun Time paints its
    favorite ★ with, so one color means one thing across both apps — and a
    hollow outline while it is not. The mark is therefore the state and the
    button at once, which is why a favorited picture keeps it up with nothing
    hovering: there is no separate badge left to disagree with it.
    """
    return _corner_icon("star" if favorite else "star_outline",
                        _STAR_GLYPH if favorite else _CORNER_REST, armed)


@cache
def corner_trash_icon(*, armed: bool) -> QIcon:
    """The trash can in a picture's lower-left corner: delete this item.

    Red under the cursor rather than the other two's light gray — it is the one
    corner whose act takes something away, and it wears the very can, in the very
    red, that the button bank's Delete does."""
    return _corner_icon("trash", _CORNER_REST, armed, arm_color=RED)


@cache
def corner_enhance_icon(state: str, *, armed: bool) -> QIcon:
    """The plus in a picture's lower-right corner, reading ``state``.

    :data:`ENHANCE_OPEN` is a hollow plus — nothing has been made of this image
    and pressing would make the first. :data:`ENHANCE_HELD` is the solid yellow
    one: it already holds exactly the version the Enhance settings describe, so
    there is nothing here to press and the mark is a badge alone.

    :data:`ENHANCE_MORE` is both at once, which is the state that needs saying:
    the image holds an enhancement AND the settings on the panel would make a
    different one. So the solid yellow plus goes down first, shifted a little,
    and is then cleared back out under the hollow one — leaving the enhancement
    it has as a yellow shadow under the offer of another. The clear is safe here
    in the one way it is anywhere: this pixmap is ours and the only thing under
    the mark is the shadow just drawn, so what shows through the hollow is the
    chip the button paints under it.
    """
    if state == ENHANCE_HELD:
        return _corner_icon("plus", AMBER, armed=False)
    ink = _CORNER_ARMED if armed else _CORNER_REST
    shifted = _CORNER_MARK_AT + _ENHANCE_SHADOW

    def draw(painter: QPainter):
        if state == ENHANCE_MORE:
            draw_glyph(painter, "plus", AMBER, size=_CORNER_MARK, x=shifted, y=shifted)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            _mark(painter, "plus", AMBER)  # the color is spent: a clear ignores it
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        _mark(painter, "plus_outline", ink)

    return _same_when_dead(_painted(draw))


def _corner_icon(glyph: str, ink, armed: bool, *, arm_color=None) -> QIcon:
    """One corner control's mark, at rest or armed — bare line art, since the
    button paints the translucent chip under it that the badges draw into
    themselves."""
    color = (arm_color or _CORNER_ARMED) if armed else ink
    return _same_when_dead(_painted(lambda painter: _mark(painter, glyph, color)))


def _mark(painter: QPainter, glyph: str, ink):
    """Paint one corner control's glyph where every corner control's glyph goes."""
    draw_glyph(painter, glyph, ink, size=_CORNER_MARK,
               x=_CORNER_MARK_AT, y=_CORNER_MARK_AT)


def _painted(draw, size: int = _SIZE) -> QPixmap:
    """A transparent canvas with ``draw`` painting into it."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    draw(painter)
    painter.end()
    return pixmap


def _same_when_dead(pixmap: QPixmap) -> QIcon:
    """``pixmap`` as an icon that keeps its own look when the button is disabled.

    Qt fades a disabled button's icon by default, which is right for a control
    that is temporarily out of reach and wrong for the enhance corner's solid
    yellow plus: that one is disabled precisely because it is a finished
    statement — this image already holds the version you would be asking for — so
    a faded rendering of it would read as a fault rather than as an answer.
    """
    icon = QIcon()
    icon.addPixmap(pixmap, QIcon.Mode.Normal)
    icon.addPixmap(pixmap, QIcon.Mode.Disabled)
    return icon


def _display_size(pixmap: QPixmap, size: int = _BADGE_DISPLAY) -> QPixmap:
    """A rendered chip scaled down to the size a tile shows it at."""
    return pixmap.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
    )


@cache
def reroll_seed_icon(media_type: str) -> QIcon:
    """A thumbnail hover-button glyph: a regenerate ring around a small play/photo
    mark — "re-roll this video" (its motion) or "this image" (its start frame).

    White line art; the button paints its own translucent chip under it, so the
    glyph reads over a thumbnail of any color. The two differ by their inner mark,
    so a video seed control is never mistaken for an image seed one.
    """
    pixmap = QPixmap(_SIZE, _SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    # The media identity, drawn large so video vs image reads at a glance...
    draw_glyph(painter, "play" if media_type == MediaType.VIDEO else "photo", _REROLL_GLYPH,
               size=_REROLL_MEDIA, x=_REROLL_MEDIA_AT, y=_REROLL_MEDIA_AT)
    _draw_regen_badge(painter)
    painter.end()
    return QIcon(pixmap)


def _draw_regen_badge(painter: QPainter):
    """A small circular arrow in the lower-right — the 're-roll' modifier over
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


def folder_badge(group) -> tuple[QIcon, str] | None:
    level = folder_level(group)
    if level is not None:
        return level_badge_icon(level), LEVEL_LABELS[level]
    if isinstance(group, (MediaGroup, SettingsGroup)):
        media = media_type_of_row(rows_under(group)[0])
        return media_type_icon(media), MEDIA_LABELS[media]
    return None


@cache
def level_badge_icon(level: str) -> QIcon:
    """The chip marking a folder's place in the hierarchy (see LEVEL_LABELS).

    Its level's letter, in that level's own color.

    Cached: the same few chips decorate many tree rows and tiles, so they're
    rendered once and shared rather than re-drawn per folder.
    """
    icon = QIcon()
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
