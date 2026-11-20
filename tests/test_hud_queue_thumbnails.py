from __future__ import annotations

import io
import os

import pytest
from PIL import Image, ImageDraw

from origenerator.gui import hud_queue_thumbnails
from origenerator.gui.hud_queue_thumbnails import empty_thumbnail, fitted_frame, fitted_thumbnail


def _long_after_any_write() -> int:
    return 2**62


@pytest.fixture(autouse=True)
def _thumbnails_held_afresh(monkeypatch):
    monkeypatch.setattr(hud_queue_thumbnails, "_FITTED",
                        hud_queue_thumbnails._held_thumbnails(1024, now_ns=_long_after_any_write))


def _png_bytes(size=(40, 20), color=(200, 40, 40)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def test_an_empty_thumbnail_says_how_wide_it_drew():
    image = Image.new("RGBA", (16, 16), (0, 0, 0, 0))

    assert empty_thumbnail(ImageDraw.Draw(image), 2, 2, 8) == 8
    assert image.getpixel((5, 5))[3] > 0, (
        "a faint square reads as waiting for its thumbnail, not as failing to draw one")
    assert image.getpixel((12, 12))[3] == 0


def test_no_path_has_no_thumbnail():
    assert fitted_thumbnail(None, 16) is None


def test_a_file_that_is_no_image_has_no_thumbnail(tmp_path):
    (tmp_path / "scene one.png").write_bytes(b"not an image")

    assert fitted_thumbnail(tmp_path / "scene one.png", 16) is None


def test_a_missing_file_has_no_thumbnail(tmp_path):
    assert fitted_thumbnail(tmp_path / "scene two.png", 16) is None


def test_a_thumbnail_is_centered_in_a_square_of_the_side_asked_for(tmp_path):
    (tmp_path / "wide.png").write_bytes(_png_bytes())

    fitted = fitted_thumbnail(tmp_path / "wide.png", 16)

    assert fitted.size == (16, 16)
    assert fitted.getpixel((8, 8))[3] == 255
    assert fitted.getpixel((8, 0))[3] == 0


def test_a_gray_thumbnail_has_no_color(tmp_path):
    (tmp_path / "red.png").write_bytes(_png_bytes())

    red, green, blue, _alpha = fitted_thumbnail(tmp_path / "red.png", 16, gray=True).getpixel((8, 8))

    assert red == green == blue


def test_a_file_written_again_is_read_again(tmp_path):
    path = tmp_path / "changing.png"
    path.write_bytes(_png_bytes(color=(200, 40, 40)))
    first = fitted_thumbnail(path, 16)
    assert fitted_thumbnail(path, 16) is first, (
        "the HUD's Job Queue is drawn again on every beat of the HUD from full-size images on "
        "disk, so a thumbnail fitted once is kept rather than read off disk again")

    path.write_bytes(_png_bytes(color=(40, 200, 40)))
    os.utime(path, ns=(1, 1))

    assert fitted_thumbnail(path, 16) is not first


def test_the_thumbnails_held_stop_at_a_bound_letting_go_of_the_longest_unused(
        tmp_path, monkeypatch):
    monkeypatch.setattr(hud_queue_thumbnails, "_FITTED",
                        hud_queue_thumbnails._held_thumbnails(2, now_ns=_long_after_any_write))
    a, b, c = (tmp_path / f"{name}.png" for name in "abc")
    for path in (a, b, c):
        path.write_bytes(_png_bytes())
    for path in (a, b, a, c):
        fitted_thumbnail(path, 16)

    reads = []
    monkeypatch.setattr(hud_queue_thumbnails, "_opened_and_fitted",
                        lambda *args: reads.append(args[0]))
    for path in (a, c, b):
        fitted_thumbnail(path, 16)

    assert reads == [str(b)], (
        "the HUD's Job Queue fits a thumbnail for every image each job makes, which over an "
        "evening is thousands, so the ones not asked for lately are let go")


def test_no_bytes_have_no_frame():
    assert fitted_frame(None, 16) is None


def test_bytes_that_are_no_image_have_no_frame():
    assert fitted_frame(b"not an image", 16) is None


def test_a_frame_is_centered_in_a_square_of_the_side_asked_for():
    fitted = fitted_frame(_png_bytes(), 16)

    assert fitted.size == (16, 16)
    assert fitted.getpixel((8, 8))[3] == 255
    assert fitted.getpixel((8, 0))[3] == 0
