from PyQt6.QtCore import QSize

from origenerator.gui.combination_view import combination_pixmap


def _picture(path, size=(60, 40), color=(0, 0, 255)):
    """A file standing in for a start frame or a recipe clip's thumbnail."""
    from PIL import Image

    Image.new("RGB", size, color).save(path)
    return str(path)


def test_the_pair_is_two_pictures_with_the_operator_between_them(qtbot, tmp_path):
    # The look every surface showing a waiting run stands: what is being
    # animated, plus the clip whose settings came with it.
    pair = combination_pixmap(_picture(tmp_path / "frame.png"),
                              _picture(tmp_path / "clip.png", color=(255, 0, 0)),
                              QSize(172, 160))

    assert pair.width() > pair.height()   # two of them across, not one
    assert pair.width() <= 172            # …and inside the plate it was given


def test_a_lone_picture_is_not_a_sum(qtbot, tmp_path):
    # Nothing came with it, so there is nothing to add it to and no operator to
    # draw: the frame takes the plate on its own.
    alone = combination_pixmap(_picture(tmp_path / "frame.png"), None, QSize(172, 160))

    assert alone.width() == alone.height()


def test_a_run_made_from_nothing_draws_nothing(qtbot, tmp_path):
    # A text-to-video has no picture to its name yet, and a stand-in would be a
    # picture of something with nothing to do with it.
    assert combination_pixmap(None, None, QSize(172, 160)) is None
    assert combination_pixmap(str(tmp_path / "gone.png"), None, QSize(172, 160)) is None


def test_the_clip_beside_the_frame_is_drained_of_color(qtbot, tmp_path):
    # Gray because it is not what is being made: in full color beside the frame
    # it reads as a second subject.
    frame = _picture(tmp_path / "frame.png", size=(80, 80), color=(0, 0, 255))
    clip = _picture(tmp_path / "clip.png", size=(80, 80), color=(255, 0, 0))
    image = combination_pixmap(frame, clip, QSize(172, 160)).toImage()

    side = image.height()
    left = image.pixelColor(side // 2, side // 2)
    right = image.pixelColor(image.width() - side // 2, side // 2)
    assert left.blue() > left.red()                      # the frame keeps its color
    assert right.red() == right.green() == right.blue()  # the clip has lost its
