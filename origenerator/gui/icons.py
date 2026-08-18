"""Small vector icons the gallery draws with QPainter.

The toolbar-button icons each return a QIcon carrying a normal and a muted
"disabled" rendering (Qt swaps to the latter when a button is disabled), the same
two-mode approach the metadata panel's copy icon uses. The recipe-level badges
(:func:`level_badge_icon`) are lettered chips marking which of workflow/model/LoRA
a folder is; the media-type badges (:func:`media_type_badge`) are corner chips
marking a Recents tile as an image or a video. All are drawn rather than glyphs so
they render identically in any font and read clearly at a small size.

:func:`tab_close_icon` is the one mark not drawn here: it is borrowed from the
live style, so a button that closes tabs wears the very ✕ the tabs themselves do.
"""

import math
from functools import lru_cache

from PyQt6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor
from PyQt6.QtWidgets import QApplication, QStyle, QStyleOption
from PyQt6.QtCore import Qt, QRect, QRectF, QPointF

from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()

from shared_ui.colors import (
    TEXT_PRIMARY, TEXT_MUTED, BG_PRIMARY, BORDER_PANEL, BLUE, PINK, AMBER,
    GREEN, RED,
)

_SIZE = 48  # drawn large, then scaled down on the button, so edges stay crisp
# Every toolbar glyph is drawn to fill this box, inset a little from the canvas
# edge so a round cap or a fat arrowhead still has room. A mark that uses only
# the middle third of its canvas is a mark the eye can't find on the button: the
# icon is already scaled down to fit, so the empty margin is scaled down with it.

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

# A starred item's star, in the green Fun Time paints its favorite ★ with: one
# color means "bookmarked" across both apps, so a star learned in one reads in
# the other. Worn by every star that says something IS starred — the tile's
# corner badge and a starred folder's row alike. The plus marking an enhanced
# tile is yellow (AMBER, this palette's yellow): green is spoken for and the two
# badges can sit on one tile, and blue is genau's across this family.
_STAR_GLYPH = GREEN


def back_icon() -> QIcon:
    return _two_mode(lambda p, _color: _chevron(p, pointing_left=True))


def forward_icon() -> QIcon:
    return _two_mode(lambda p, _color: _chevron(p, pointing_left=False))


def undo_icon() -> QIcon:
    """A circular arrow curling back, its head to the left — undo."""
    return _two_mode(lambda p, color: _draw_history_arrow(p, color, forward=False))


def redo_icon() -> QIcon:
    """Undo's mirror image, head to the right — redo. The pair is a mirror on
    purpose: side by side in the bank, two arrowheads pointing opposite ways say
    which is which faster than any difference in the arc could."""
    return _two_mode(lambda p, color: _draw_history_arrow(p, color, forward=True))


def autoloop_icon() -> QIcon:
    """A die — auto-generate: re-roll this folder, and keep re-rolling it.

    Deliberately not another circular arrow. It sat one group away from undo
    wearing the same arc, and the two were near-indistinguishable at button
    size; a filled square of pips shares its silhouette with nothing else here.
    """
    return _two_mode(_draw_die)


def slideshow_icon() -> QIcon:
    """A play triangle in a frame — play this folder as a fullscreen slideshow."""
    return _two_mode(_draw_slideshow)


def enhance_icon() -> QIcon:
    """A bold plus — enhance (upscale + re-sample) images.

    Yellow, the very plus an enhanced tile wears in its corner
    (:func:`enhance_badge`), so the button and the mark it leaves behind are one
    symbol in one color — and so it can't be read as a star, which is what green
    means across this family (:data:`_STAR_GLYPH`)."""
    return _two_mode(_draw_plus, AMBER)


def mic_icon() -> QIcon:
    """A microphone — speak a prompt edit. Drawn to the bank's scale, so the
    button it is waiting for can be dropped into the app-doing-things group
    without the glyph arriving a size smaller than its neighbors."""
    return _two_mode(_draw_mic)


def stroke_icon() -> QIcon:
    """A sine wave — the one OSR2 switch. It wears the waveform whichever source
    is driving, because from the outside they are the same thing: motion the app
    is sending the device."""
    return _two_mode(_draw_stroke)


def audio_icon() -> QIcon:
    """A speaker sounding off — the audio bed's on/off switch."""
    return _two_mode(_draw_audio)


def trash_icon(*, color=None) -> QIcon:
    """A trash can — the Trash shelf's caret marker, and the Delete button that
    fills it. One glyph for both ends of a deletion, so the shelf reads as where
    that button's items go."""
    return _two_mode(lambda p, c: _draw_trash(p, c), color)


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
        return _two_mode(lambda p, c: _draw_star(p, c, True), _STAR_GLYPH)
    return _two_mode(lambda p, color: _draw_star(p, color, False))


def clock_icon() -> QIcon:
    """A clock face — the Recents shelf's caret marker, drawn to match the star."""
    return _two_mode(_draw_clock)


def flask_icon() -> QIcon:
    """An Erlenmeyer flask — the Experiments shelf's caret marker."""
    return _two_mode(_draw_flask)


def custom_folder_icon() -> QIcon:
    """A folder — the caret marker on a folder the user composed, and the toolbar
    button that composes one out of the picked folders."""
    return _two_mode(_draw_folder)


@lru_cache(maxsize=None)
def experiment_verdict_icon(verdict: str) -> QIcon:
    """An experiment tile's review hover-buttons: a check ("up" — keep it, it
    joins the gallery) or a cross ("down" — reject it and teach the experimenter
    what to avoid). White line art on the buttons' own translucent chip, like the
    per-seed re-roll controls."""
    return QIcon(_render(lambda p, _c: _draw_verdict(p, verdict), _REROLL_GLYPH))


@lru_cache(maxsize=None)
def recovery_action_icon(action: str) -> QIcon:
    """A Trash-shelf tile's review hover-buttons: a circular arrow back
    ("restore" — the item and its files return to where they were) or a trash can
    ("purge" — end it now instead of waiting out its window). White line art on
    the buttons' own translucent chip, like the experiment verdict controls."""
    draw = ((lambda p, c: _draw_history_arrow(p, c, forward=False))
            if action == "restore" else _draw_trash)
    return QIcon(_render(draw, _REROLL_GLYPH))


@lru_cache(maxsize=None)
def media_type_badge(media_type: str) -> QPixmap:
    """A small corner badge marking a Recents tile as an image or a video.

    A white glyph — a play triangle for a video, a framed photo for an image — on
    a translucent dark chip, so it reads over a thumbnail of any color. Cached and
    pre-scaled to its on-screen size; the same two badges decorate every tile.
    """
    draw = _draw_play if media_type == "video" else _draw_photo
    pixmap = QPixmap(_SIZE, _SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_BADGE_CHIP)
    painter.drawRoundedRect(QRectF(4, 4, _SIZE - 8, _SIZE - 8), 11, 11)
    draw(painter)
    painter.end()
    return pixmap.scaled(
        _BADGE_DISPLAY, _BADGE_DISPLAY,
        Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
    )


@lru_cache(maxsize=None)
def star_badge() -> QPixmap:
    """A corner badge marking a starred image or video.

    A filled green star on the translucent dark chip the media-type badges use,
    so a bookmarked item reads at a glance over a thumbnail of any color. Cached
    and pre-scaled — the one badge decorates every starred tile."""
    pixmap = QPixmap(_SIZE, _SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_BADGE_CHIP)
    painter.drawRoundedRect(QRectF(4, 4, _SIZE - 8, _SIZE - 8), 11, 11)
    _draw_star(painter, _STAR_GLYPH, filled=True)
    painter.end()
    return pixmap.scaled(
        _BADGE_DISPLAY, _BADGE_DISPLAY,
        Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
    )


@lru_cache(maxsize=None)
def enhance_badge() -> QPixmap:
    """A corner badge marking an enhanced image: a yellow plus on the translucent
    chip the other badges use, so an upscaled/re-sampled result reads at a
    glance over a thumbnail of any color. Yellow because green is the star's
    (see :data:`_STAR_GLYPH`) and the two badges share a tile, and because blue
    belongs to genau across this family. Cached and pre-scaled — the one badge
    decorates every enhanced tile."""
    pixmap = QPixmap(_SIZE, _SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_BADGE_CHIP)
    painter.drawRoundedRect(QRectF(4, 4, _SIZE - 8, _SIZE - 8), 11, 11)
    pen = QPen(QColor(AMBER))
    pen.setWidthF(6.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawLine(QPointF(24, 13), QPointF(24, 35))
    painter.drawLine(QPointF(13, 24), QPointF(35, 24))
    painter.end()
    return pixmap.scaled(
        _BADGE_DISPLAY, _BADGE_DISPLAY,
        Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
    )


_REROLL_GLYPH = QColor(255, 255, 255)


@lru_cache(maxsize=None)
def reroll_seed_icon(media_type: str) -> QIcon:
    """A thumbnail hover-button glyph: a regenerate ring around a small play/photo
    mark — "re-roll this video" (its motion) or "this image" (its start frame).

    White line art; the button paints its own translucent chip behind it, so the
    glyph reads over a thumbnail of any color. The two differ by their inner mark,
    so a video seed control is never mistaken for an image seed one.
    """
    return QIcon(_render(lambda p, _c: _draw_reroll_seed(p, media_type), _REROLL_GLYPH))


def _draw_reroll_seed(painter: QPainter, media_type: str):
    # The media identity, drawn large so video vs image reads at a glance...
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_REROLL_GLYPH)
    if media_type == "video":
        painter.drawPolygon(QPointF(11, 9), QPointF(11, 31), QPointF(29, 20))  # play triangle
    else:
        pen = QPen(_REROLL_GLYPH)
        pen.setWidthF(3.0)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(8, 11, 24, 19), 3, 3)                   # photo frame
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_REROLL_GLYPH)
        painter.drawEllipse(QPointF(15, 18), 2.6, 2.6)                         # the sun
        painter.drawPolygon(QPointF(10, 28), QPointF(18, 20), QPointF(31, 28))  # a mountain peak
    _draw_regen_badge(painter)


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
    glyph = {"video": _draw_play, "image": _draw_photo}.get(level)
    if glyph is not None:
        icon.addPixmap(_render_chip(_MEDIA_LEVEL_CHIP, glyph))
        return icon
    letter, color = _LEVEL_BADGES[level]
    icon.addPixmap(_render_badge(letter, color))
    return icon


def _render_chip(color, draw) -> QPixmap:
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

    return _render_chip(color, draw)


def _readable_on(color):
    """Near-black or the primary text color, whichever reads on ``color``."""
    luminance = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
    return BG_PRIMARY if luminance > 150 else TEXT_PRIMARY


def _two_mode(draw, color=None) -> QIcon:
    """An icon carrying its normal and disabled renderings.

    ``color`` tints the normal one — the bank's act-on-this-item trio is colored
    so star, enhance and delete say what they do before the tooltip does — and
    the disabled one stays the muted gray whatever the color, so a button with
    no target reads as dead rather than as a dimmer shade of red.
    """
    icon = QIcon()
    icon.addPixmap(_render(draw, color if color is not None else TEXT_PRIMARY),
                   QIcon.Mode.Normal)
    icon.addPixmap(_render(draw, TEXT_MUTED), QIcon.Mode.Disabled)
    return icon


def _render(draw, color) -> QPixmap:
    pixmap = QPixmap(_SIZE, _SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(color)
    pen.setWidthF(5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    draw(painter, color)
    painter.end()
    return pixmap


def _chevron(painter: QPainter, *, pointing_left: bool):
    """A ``‹`` or ``›`` chevron, drawn corner to corner of the canvas."""
    near, far, top, bottom = 15, 31, 9, 39
    if pointing_left:
        painter.drawPolyline(QPointF(far, top), QPointF(near, 24), QPointF(far, bottom))
    else:
        painter.drawPolyline(QPointF(near, top), QPointF(far, 24), QPointF(near, bottom))


# The undo/redo arc: a ring broken across one upper quadrant, the arrowhead
# filling that break. The two glyphs are one drawing mirrored about the canvas's
# vertical center line — hence the coordinate pairs below summing to 48 — so
# side by side in the bank they read as a direction each, not as two rings.
_HISTORY_RING = QRectF(11, 13, 26, 26)  # center (24, 26), radius 13


def _draw_history_arrow(painter: QPainter, color, *, forward: bool):
    """Undo (``forward=False``) or redo (``forward=True``).

    The head is deliberately huge — as tall as the ring's radius and a third of
    the canvas wide — and the arc stops short of it, so it stands in open space
    instead of merging into the stroke it caps. The small triangle this replaced
    sat on the ring as a nub: it left the two directions telling apart only by
    which end of a circle a few pixels were on, which at button size is no
    difference at all.
    """
    if forward:
        painter.drawArc(_HISTORY_RING, 80 * 16, 285 * 16)   # break at the upper right
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(QPointF(39, 14), QPointF(24, 5), QPointF(24, 23))
    else:
        painter.drawArc(_HISTORY_RING, 175 * 16, 285 * 16)  # break at the upper left
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(QPointF(9, 14), QPointF(24, 5), QPointF(24, 23))


def _draw_die(painter: QPainter, color):
    """A five-pip die face — 'roll this folder again, and again'."""
    painter.drawRoundedRect(QRectF(8, 8, 32, 32), 7, 7)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    for cx, cy in ((17, 17), (31, 17), (24, 24), (17, 31), (31, 31)):
        painter.drawEllipse(QPointF(cx, cy), 3.2, 3.2)


def _draw_slideshow(painter: QPainter, color):
    """A framed screen with a play triangle — 'play this folder fullscreen'."""
    painter.drawRoundedRect(QRectF(8, 11, 32, 26), 4, 4)                   # the screen
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPolygon(QPointF(20, 16), QPointF(20, 32), QPointF(33, 24))  # play triangle


def _draw_plus(painter: QPainter, color):
    """A bold plus filling the canvas — 'enhance'."""
    pen = QPen(color)
    pen.setWidthF(7)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawLine(QPointF(24, 9), QPointF(24, 39))
    painter.drawLine(QPointF(9, 24), QPointF(39, 24))


def _draw_stroke(painter: QPainter, color):
    """One cycle of a sine — the stroke this drives the device with."""
    pen = QPen(color)
    pen.setWidthF(5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(QRectF(6, 11, 18, 26), 0, 180 * 16)          # the crest
    painter.drawArc(QRectF(24, 11, 18, 26), 180 * 16, 180 * 16)  # the trough


def _draw_audio(painter: QPainter, color):
    """A speaker cone with two waves coming off it — sound is playing."""
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPolygon(QPointF(7, 18), QPointF(14, 18), QPointF(22, 9),
                        QPointF(22, 39), QPointF(14, 30), QPointF(7, 30))
    pen = QPen(color)
    pen.setWidthF(4.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(QRectF(23, 16, 12, 16), -70 * 16, 140 * 16)   # the near wave
    painter.drawArc(QRectF(25, 8, 18, 32), -70 * 16, 140 * 16)    # the far wave


def _draw_mic(painter: QPainter, color):
    """A microphone capsule in its cradle on a stand — push-to-talk."""
    painter.setBrush(color)
    painter.drawRoundedRect(QRectF(18, 6, 12, 21), 6, 6)          # the mic body
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(QRectF(11, 11, 26, 26), 200 * 16, 140 * 16)   # the cradle
    painter.drawLine(QPointF(24, 37), QPointF(24, 42))            # the stand
    painter.drawLine(QPointF(17, 42), QPointF(31, 42))            # the base


def _draw_trash(painter: QPainter, _color=None):
    """A trash can: lid with a small handle over a lightly tapered body."""
    painter.drawLine(QPointF(9, 15), QPointF(39, 15))                        # lid
    painter.drawPolyline(QPointF(18, 15), QPointF(18, 9),
                         QPointF(30, 9), QPointF(30, 15))                     # handle
    painter.drawPolyline(QPointF(13, 15), QPointF(16, 41),
                         QPointF(32, 41), QPointF(35, 15))                    # body
    painter.drawLine(QPointF(20, 21), QPointF(21, 36))                       # ridges
    painter.drawLine(QPointF(28, 21), QPointF(27, 36))


def _draw_star(painter: QPainter, color, filled: bool):
    cx, cy, outer, inner = 24, 25, 17, 7
    points = []
    for i in range(10):
        angle = -math.pi / 2 + i * math.pi / 5
        radius = outer if i % 2 == 0 else inner
        points.append(QPointF(cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    if filled:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
    else:
        pen = QPen(color)
        pen.setWidthF(3)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)  # a thinner outline than the default stroke
    painter.drawPolygon(*points)


def _draw_play(painter: QPainter):
    """A filled play triangle — the universal 'this is a video' mark."""
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_BADGE_GLYPH)
    painter.drawPolygon(QPointF(20, 16), QPointF(20, 32), QPointF(34, 24))


def _draw_photo(painter: QPainter):
    """A framed photo — a sun over a mountain — the 'this is an image' mark."""
    pen = QPen(_BADGE_GLYPH)
    pen.setWidthF(2.6)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(14, 16, 20, 16), 3, 3)   # the picture frame
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_BADGE_GLYPH)
    painter.drawEllipse(QPointF(20, 21), 2.3, 2.3)          # the sun, upper-left
    painter.drawPolygon(QPointF(16, 31), QPointF(24, 23),   # a single mountain peak
                        QPointF(33, 31))


def _draw_clock(painter: QPainter, _color):
    """A round clock face with two hands (at 12 and 3) — the "recent" marker."""
    painter.drawEllipse(QRectF(9, 9, 30, 30))
    painter.drawLine(QPointF(24, 24), QPointF(24, 13))   # hour hand, pointing up
    painter.drawLine(QPointF(24, 24), QPointF(33, 24))   # minute hand, to the right


def _draw_flask(painter: QPainter, color):
    """An Erlenmeyer flask with liquid — the "experiments" marker."""
    # Neck and conical body, one outline.
    painter.drawPolyline(
        QPointF(19, 8), QPointF(19, 18), QPointF(9, 38),
        QPointF(39, 38), QPointF(29, 18), QPointF(29, 8),
    )
    painter.drawLine(QPointF(16, 8), QPointF(32, 8))     # the lip
    # The liquid: a filled band across the cone's lower half.
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPolygon(QPointF(14, 29), QPointF(34, 29),
                        QPointF(38, 36), QPointF(10, 36))


def _draw_folder(painter: QPainter, _color):
    """A tabbed folder outline — the "a folder you made" marker."""
    painter.drawPolyline(
        QPointF(8, 39), QPointF(8, 12), QPointF(20, 12), QPointF(24, 18),
        QPointF(40, 18), QPointF(40, 39), QPointF(8, 39),
    )


def _draw_verdict(painter: QPainter, verdict: str):
    """A check ("up") or a cross ("down"), matching the reroll glyphs' weight."""
    pen = QPen(_REROLL_GLYPH)
    pen.setWidthF(5.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if verdict == "up":
        painter.drawPolyline(QPointF(11, 25), QPointF(20, 34), QPointF(37, 14))
    else:
        painter.drawLine(QPointF(14, 14), QPointF(34, 34))
        painter.drawLine(QPointF(34, 14), QPointF(14, 34))
