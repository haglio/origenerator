"""The stills either side of a slideshow's current item: which still, and where."""

from PIL import Image
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QWidget

from origenerator.gui.neighbor_previews import NeighborPreviews, side_x, still_for

_HOST_WIDTH = 1000


def _png(path, size=(40, 40)):
    Image.new("RGB", size, (20, 80, 160)).save(path, "PNG")
    return str(path)


def test_still_prefers_the_stored_thumbnail():
    item = ("clip.mp4", "video", "id-v", "thumb.png")
    assert still_for(item) == "thumb.png"


def test_a_thumbnail_less_image_stands_in_for_itself():
    assert still_for(("frame.png", "image", "id-i")) == "frame.png"


def test_a_thumbnail_less_video_has_no_still():
    # Nothing to draw small without opening the clip, so that side shows nothing.
    assert still_for(("clip.mp4", "video", "id-v")) is None
    assert still_for(None) is None


def test_a_still_sits_in_the_surround_beside_a_narrow_image():
    # A portrait image centered in a wide screen leaves 300px either side.
    media = QRect(300, 0, 400, 800)
    assert side_x("left", _HOST_WIDTH, media, 100) == 100    # centered in the gutter
    assert side_x("right", _HOST_WIDTH, media, 100) == 800   # and in the other one


def test_a_still_lies_over_a_full_width_image_rather_than_shrinking_it():
    # No surround to sit in: the still insets from the screen edge, on top of the
    # media, because the media never gives up width to make room.
    media = QRect(0, 200, _HOST_WIDTH, 400)
    assert side_x("left", _HOST_WIDTH, media, 100) == 12
    assert side_x("right", _HOST_WIDTH, media, 100) == _HOST_WIDTH - 112


def test_a_gutter_too_tight_for_the_still_overlays_too():
    media = QRect(110, 0, 780, 800)  # 110px of surround, a 100px still + margins
    assert side_x("left", _HOST_WIDTH, media, 100) == 12


def test_both_sides_draw_and_a_missing_one_hides(qtbot, tmp_path):
    host = QWidget()
    host.resize(_HOST_WIDTH, 800)
    qtbot.addWidget(host)
    neighbors = NeighborPreviews(host)

    neighbors.set_neighbors(_png(tmp_path / "prev.png"), None,
                            media_rect=QRect(300, 0, 400, 800))

    left, right = neighbors._labels
    assert left.isVisibleTo(host) and not left.pixmap().isNull()
    assert right.isHidden()  # nothing to show on that side


def test_a_still_is_never_blown_up_past_its_own_size(qtbot, tmp_path):
    host = QWidget()
    host.resize(_HOST_WIDTH, 800)
    qtbot.addWidget(host)
    neighbors = NeighborPreviews(host)

    neighbors.set_neighbors(_png(tmp_path / "small.png", size=(24, 24)), None)

    # The box would be 120x400 at this size; a 24px thumbnail stays 24px.
    assert neighbors._labels[0].pixmap().size().width() == 24
