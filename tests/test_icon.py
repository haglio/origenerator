"""The app icon must follow the suite's shared block-letter design system.

Every sibling app draws a single PINK letter (genau "G", evolver "E",
scripture "S", nau "N", ...) on a 5x5 grid that is inset 31px inside a 256px
canvas, where every stroke is exactly one grid unit -- i.e. 1/5 of the glyph
box -- thick, with near-square corners.

Origenerator's "O" must match: a 1/5-thick PINK square ring filling the same
194px box, not the oversized, thick, heavily-rounded glyph it shipped with
originally.  These suite invariants are hard-coded here on purpose -- the test
is the spec that pins the icon to the rest of the suite, independent of how the
icon happens to be generated.
"""

from PIL import Image

from origenerator.config import PROJECT_DIR
from origenerator.icon_design import render_icon
from shared_ui.colors import PINK

ICON_PATH = PROJECT_DIR / "icon.ico"

CANVAS = 256
SUITE_INSET = 31  # glyph box offset shared across the suite
SUITE_BOX = CANVAS - 2 * SUITE_INSET  # 194 -- glyph box size
SUITE_UNIT = SUITE_BOX / 5  # 38.8 -- one grid unit == stroke width ("1/5-based")
PINK_RGB = (PINK.red(), PINK.green(), PINK.blue())


def _master():
    """The 256px frame of the multi-resolution icon."""
    return Image.open(ICON_PATH)


def _rgba():
    return _master().convert("RGBA")


def _opaque(px, x, y):
    return px[x, y][3] > 128


def _glyph_bbox(img):
    """(left, upper, right, lower) of the opaque glyph; right/lower exclusive."""
    return img.getchannel("A").getbbox()


def test_master_frame_is_256():
    assert _master().size == (CANVAS, CANVAS)


def test_glyph_fills_the_suite_box():
    left, upper, right, lower = _glyph_bbox(_rgba())
    assert abs(left - SUITE_INSET) <= 2
    assert abs(upper - SUITE_INSET) <= 2
    assert abs((right - left) - SUITE_BOX) <= 4
    assert abs((lower - upper) - SUITE_BOX) <= 4


def test_stroke_is_one_fifth_of_the_glyph():
    img = _rgba()
    px = img.load()
    left, upper, right, lower = _glyph_bbox(img)
    midy = (upper + lower) // 2
    width = 0
    x = left
    while x < right and _opaque(px, x, midy):
        width += 1
        x += 1
    glyph_size = right - left
    assert abs(width - glyph_size / 5) <= 4
    assert abs(width - SUITE_UNIT) <= 4


def test_glyph_is_an_open_ring():
    px = _rgba().load()
    assert px[CANVAS // 2, CANVAS // 2][3] == 0


def test_corners_are_square_not_round():
    # The suite's corners are near-square (a ~3px softening); the old "O" was
    # heavily rounded (~16px).  Measure the radius as the number of rows from
    # the top before the left edge becomes solid, and require it to be small.
    img = _rgba()
    px = img.load()
    left, upper, _, _ = _glyph_bbox(img)
    radius = next(d for d in range(40) if _opaque(px, left, upper + d))
    assert radius <= 8


def test_uses_the_shared_pink():
    img = _rgba()
    px = img.load()
    left, upper, _, lower = _glyph_bbox(img)
    midy = (upper + lower) // 2
    pixel = px[left + 10, midy]
    assert pixel[3] == 255
    assert pixel[:3] == PINK_RGB


def test_background_is_transparent():
    px = _rgba().load()
    assert px[0, 0][3] == 0
    assert px[CANVAS - 1, CANVAS - 1][3] == 0


def test_committed_icon_matches_the_generator(qapp):
    # The shipped icon.ico must be exactly what icon_design renders, so the
    # asset can never silently drift from the design module that defines it.
    assert _rgba().tobytes() == render_icon(CANVAS).tobytes()
