from __future__ import annotations

from pathlib import Path

from PIL import Image
from PyQt6.QtGui import QColor

from origenerator.spin_arrows import arrow_paths

_GREEN = QColor(0, 200, 0)


def _alpha_rows(path: str) -> list[int]:
    image = Image.open(path).convert("RGBA")
    return [sum(1 for x in range(image.width) if image.getpixel((x, y))[3])
            for y in range(image.height)]


def test_the_arrows_are_png_files_named_with_forward_slashes(tmp_path):
    up, down = arrow_paths(_GREEN, tmp_path)

    assert "\\" not in up
    assert "\\" not in down
    assert Path(up).is_file()
    assert Path(down).is_file()


def test_the_up_arrow_narrows_toward_its_top_and_the_down_arrow_toward_its_bottom(tmp_path):
    up, down = arrow_paths(_GREEN, tmp_path)

    assert _alpha_rows(up) == [1, 3, 5, 7, 9]
    assert _alpha_rows(down) == [9, 7, 5, 3, 1]


def test_the_arrows_take_the_color_they_are_asked_for(tmp_path):
    up, _ = arrow_paths(_GREEN, tmp_path)

    assert Image.open(up).convert("RGBA").getpixel((4, 4)) == (0, 200, 0, 255)


def test_arrows_already_drawn_for_a_color_are_not_drawn_again(tmp_path):
    up, down = arrow_paths(_GREEN, tmp_path)
    Path(up).write_bytes(b"left alone")

    assert arrow_paths(_GREEN, tmp_path) == (up, down)
    assert Path(up).read_bytes() == b"left alone"


def test_a_color_gets_its_own_pair_of_files(tmp_path):
    assert set(arrow_paths(_GREEN, tmp_path)).isdisjoint(arrow_paths(QColor(200, 0, 0), tmp_path))


def test_arrows_that_cannot_be_written_come_back_as_none(tmp_path):
    in_the_way = tmp_path / "a-file-not-a-folder"
    in_the_way.write_bytes(b"")

    assert arrow_paths(_GREEN, in_the_way) is None
