from __future__ import annotations

from PIL import Image
from PyQt6.QtCore import QSize, Qt

from origenerator.gui.combination import Combination
from origenerator.gui.combination_view import CombinationView, combination_pixmap


def _image(path, size=(60, 40), color=(0, 0, 255)):
    Image.new("RGB", size, color).save(path)
    return str(path)


def test_the_pair_is_two_halves_with_the_operator_between_them(qtbot, tmp_path):
    pair = combination_pixmap(Combination(_image(tmp_path / "frame.png"),
                                          _image(tmp_path / "clip.png", color=(255, 0, 0))),
                              QSize(172, 160))

    assert pair.width() > pair.height()
    assert pair.width() <= 172


def test_a_lone_image_is_not_a_sum(qtbot, tmp_path):
    alone = combination_pixmap(Combination(_image(tmp_path / "frame.png")), QSize(172, 160))

    assert alone.width() == alone.height()


def test_a_run_made_from_nothing_draws_nothing(qtbot, tmp_path):
    assert combination_pixmap(Combination(), QSize(172, 160)) is None, (
        "a run made from nothing has no thumbnail to its name yet, and a stand-in would be a "
        "thumbnail of something with nothing to do with it")
    assert combination_pixmap(Combination(str(tmp_path / "gone.png")), QSize(172, 160)) is None


def test_the_clip_beside_the_frame_is_drained_of_color(qtbot, tmp_path):
    frame = _image(tmp_path / "frame.png", size=(80, 80), color=(0, 0, 255))
    video = _image(tmp_path / "clip.png", size=(80, 80), color=(255, 0, 0))
    image = combination_pixmap(Combination(frame, video), QSize(172, 160)).toImage()

    side = image.height()
    left = image.pixelColor(side // 2, side // 2)
    right = image.pixelColor(image.width() - side // 2, side // 2)
    assert left.blue() > left.red()
    assert right.red() == right.green() == right.blue(), (
        "gray because it is not what is being made, lending the settings and not the result: in "
        "full color beside the frame it reads as a second subject")


def _columns_of(image, color):
    middle = image.height() // 2
    return [x for x in range(image.width()) if image.pixelColor(x, middle) == color]


def _painted(image, left, right):
    return any(image.pixelColor(x, y).alpha() > 0
               for x in range(left, right) for y in range(image.height()))


def test_a_source_video_whose_prompt_was_edited_stands_in_parentheses(qtbot, tmp_path):
    frame = _image(tmp_path / "frame.png", size=(80, 80))
    video = _image(tmp_path / "clip.png", size=(80, 80), color=(255, 0, 0))
    size = QSize(400, 100)
    as_made = combination_pixmap(Combination(frame, video), size).toImage()
    edited = combination_pixmap(Combination(frame, video, prompt_edited=True),
                                size).toImage()
    gray_video = as_made.pixelColor(as_made.width() - 1, as_made.height() // 2)

    video_as_made, video_edited = _columns_of(as_made, gray_video), _columns_of(edited, gray_video)
    assert video_edited[0] > video_as_made[0]
    assert _painted(edited, video_as_made[0], video_edited[0])
    assert _painted(edited, video_edited[-1] + 1, edited.width())


def _view(qtbot, combination):
    view = CombinationView()
    qtbot.addWidget(view)
    view.resize(500, 200)
    view.show()
    view.show_pair(combination)
    return view


def test_a_click_on_the_pair_falls_through_to_the_pane(qtbot, tmp_path):
    view = _view(qtbot, Combination(_image(tmp_path / "frame.png")))

    for label in (view.image_label, view.plus_label, view.video_label):
        assert label.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents), (
            "the pane owns the double-click that opens a slideshow; there is nothing here to open, so "
            "nothing here takes a click")


def test_the_plus_shows_only_with_both_halves(qtbot, tmp_path):
    frame, clip = _image(tmp_path / "frame.png"), _image(tmp_path / "clip.png")

    both = _view(qtbot, Combination(frame, clip))
    alone = _view(qtbot, Combination(frame))

    assert not both.plus_label.isHidden()
    assert alone.plus_label.isHidden()


def test_the_parentheses_show_only_around_a_source_video_whose_prompt_was_edited(qtbot, tmp_path):
    frame, clip = _image(tmp_path / "frame.png"), _image(tmp_path / "clip.png")

    edited = _view(qtbot, Combination(frame, clip, prompt_edited=True))
    no_video = _view(qtbot, Combination(frame, prompt_edited=True))
    as_made = _view(qtbot, Combination(frame, clip))

    assert not edited.open_paren_label.isHidden()
    assert no_video.open_paren_label.isHidden()
    assert as_made.open_paren_label.isHidden()


def test_dragging_the_pane_bigger_keeps_the_looping_video_going(qtbot, tmp_path):
    view = _view(qtbot, Combination(_image(tmp_path / "frame.png"), _image(tmp_path / "clip.png")))
    playing = view._movie

    view.resize(800, 300)

    assert view._movie is playing


def test_showing_a_pair_with_no_video_leaves_no_last_frame_of_the_one_before(qtbot, tmp_path):
    frame, clip = _image(tmp_path / "frame.png"), _image(tmp_path / "clip.png")
    view = _view(qtbot, Combination(frame, clip))

    view.show_pair(Combination(frame))

    assert view.video_label.pixmap().isNull()


def test_a_frame_the_library_has_moved_leaves_the_source_video_alone(qtbot, tmp_path):
    moved = str(tmp_path / "moved.png")
    clip = _image(tmp_path / "clip.png")

    view = _view(qtbot, Combination(moved, clip))

    assert view.image_label.isHidden(), (
        "a frame the library has since moved is an ordinary absence, not an error")
    assert not view.video_label.isHidden()
