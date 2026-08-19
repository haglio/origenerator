"""The picture stood behind a run that hasn't drawn anything yet."""

from PIL import Image
from PyQt6.QtCore import QSize

from origenerator.gui.blurred import blurred_backdrop


def _picture(path, size=(64, 48)):
    # A hard checkerboard, so "did this get blurred" is answerable by looking at
    # two neighboring pixels rather than by eye.
    image = Image.new("RGB", size, (255, 255, 255))
    for x in range(size[0]):
        for y in range(size[1]):
            if (x // 4 + y // 4) % 2:
                image.putpixel((x, y), (0, 0, 0))
    image.save(path)
    return str(path)


def test_the_backdrop_fills_the_space_it_is_given(qtbot, tmp_path):
    backdrop = blurred_backdrop(_picture(tmp_path / "src.png"), QSize(172, 160))

    # Cover-cropped, not letterboxed: a plate with bars down its sides reads as a
    # picture that failed rather than as a backdrop.
    assert (backdrop.width(), backdrop.height()) == (172, 160)


def test_nothing_to_stand_there_is_not_an_error(qtbot, tmp_path):
    # A library file that has since moved is an ordinary case; the caller keeps
    # its plain plate.
    assert blurred_backdrop(str(tmp_path / "gone.png"), QSize(172, 160)) is None
    assert blurred_backdrop(None, QSize(172, 160)) is None
    assert blurred_backdrop(_picture(tmp_path / "s.png"), QSize(0, 0)) is None


def test_the_backdrop_is_soft_and_dim_rather_than_the_picture_itself(qtbot, tmp_path):
    backdrop = blurred_backdrop(_picture(tmp_path / "src.png"), QSize(172, 160))
    image = backdrop.toImage()

    # Blurred: the checkerboard's hard black/white edges are gone, so no pixel is
    # anywhere near white and neighbors differ only slightly.
    levels = [image.pixelColor(x, 80).lightness() for x in range(0, 172, 4)]
    assert max(levels) < 200            # dimmed, so nothing is still paper-white
    assert max(levels) - min(levels) < 120  # softened, so no hard edge survives


def test_the_same_picture_at_the_same_size_is_only_rendered_once(qtbot, tmp_path):
    # The shelves rebuild on every poll, and this reads a full-size render off
    # disk — so a second ask hands back the very same pixmap.
    path = _picture(tmp_path / "src.png")

    first = blurred_backdrop(path, QSize(172, 160))
    second = blurred_backdrop(path, QSize(172, 160))

    assert first is second
