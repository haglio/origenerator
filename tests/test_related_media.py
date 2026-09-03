"""What else in the library a shown generation is tied to.

Two links stacked under a config tab's settings form — the item this row was
built from, and the videos an image was animated into — fed one row at a time.
They were two attributes and two methods on the config panel, which has a dozen
other things to be about; here they are one widget answering one question.
"""

import logging

import pytest

from origenerator.gui.animated_strip import _VideoTile
from origenerator.gui.related_media import RelatedMedia


def _image_row(prompt_id="img1", filename="sdxl_t2i_img1.png"):
    return {
        "prompt_id": prompt_id, "workflow_name": "sdxl_t2i",
        "created_at": "2026-01-02 03:04:05",
        "params_json": "{}",
        "output_files": f'[{{"filename": "{filename}", "subfolder": "image",'
                        f' "type": "output"}}]',
    }


def _video_row(prompt_id="vid1", input_image="sdxl_t2i_img1.png"):
    return {
        "prompt_id": prompt_id, "workflow_name": "wan22_i2v",
        "created_at": "2026-01-02 03:05:06",
        "params_json": f'{{"input_image": "{input_image}"}}',
        "output_files": '[{"filename": "wan22_i2v_vid1.mp4",'
                        ' "subfolder": "video", "type": "output"}]',
        "thumbnail_path": "vid1_thumb.jpg",
    }


@pytest.fixture
def make_related(qtbot):
    """Build a RelatedMedia over a given set of the library's videos, counting
    every time it asks for them."""
    def _make(*videos):
        widget = RelatedMedia(video_rows=lambda: (asks.append(True), videos)[1])
        asks: list = []
        widget.asks = asks
        qtbot.addWidget(widget)
        return widget

    return _make


@pytest.fixture
def related(make_related):
    return make_related()


def test_a_row_tied_to_nothing_shows_no_links(related):
    assert related._source_tile.isHidden()
    assert related._animated_strip.isHidden()


def test_a_video_points_back_at_the_image_that_seeded_its_start_frame(related):
    image = _image_row()

    related.show_row(_video_row(), [image])

    assert not related._source_tile.isHidden()
    assert related._source_tile._prompt_id == "img1"
    assert related._animated_strip.isHidden()   # a video is animated into nothing


def test_an_image_lists_the_videos_it_was_animated_into(make_related):
    image = _image_row()
    related = make_related(_video_row())

    related.show_row(image, [image])

    assert not related._animated_strip.isHidden()
    assert len(related._animated_strip.findChildren(_VideoTile)) == 1
    assert related._source_tile.isHidden()      # an image has no start frame


def test_a_requested_row_points_at_the_item_it_was_asked_about(related):
    # A requested image has no start frame and a requested video's is the one it
    # already had, so the same tile carries the same relation under its own word.
    image = _image_row()

    related.show_row(_image_row("img2", "sdxl_t2i_img2.png"), [],
                     request={"source_row": image})

    assert not related._source_tile.isHidden()
    assert related._source_tile._prompt_id == "img1"


def test_a_click_on_an_animation_names_the_video_that_was_clicked(make_related):
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtGui import QMouseEvent

    image = _image_row()
    related = make_related(_video_row())
    related.show_row(image, [image])
    named = []
    related.animated_activated.connect(named.append)

    tile, = related._animated_strip.findChildren(_VideoTile)
    tile.mousePressEvent(QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPoint(1, 1).toPointF(),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier))

    assert named == ["vid1"]


def test_a_click_on_the_source_tile_names_the_item_it_points_at(related):
    image = _image_row()
    related.show_row(_video_row(), [image])
    named = []
    related.source_activated.connect(named.append)

    related._source_tile.activated.emit("img1")

    assert named == ["img1"]


def test_showing_the_next_row_takes_the_last_one_s_answers_away(related):
    image = _image_row()
    related.show_row(_video_row(), [image])
    assert not related._source_tile.isHidden()

    related.show_row(image, [image])

    assert related._source_tile.isHidden()


def test_clearing_puts_both_links_down(make_related):
    image = _image_row()
    related = make_related(_video_row())
    related.show_row(image, [image])

    related.clear()

    assert related._source_tile.isHidden()
    assert related._animated_strip.isHidden()


def test_a_long_list_of_animations_is_capped_and_says_so(make_related, caplog):
    # A prolific image can have dozens; the strip shows a readable few and the
    # log says how many there were, rather than the tab quietly showing a
    # different number from the folder.
    image = _image_row()
    videos = [_video_row(f"vid{n}") for n in range(20)]
    related = make_related(*videos)

    with caplog.at_level(logging.INFO):
        related.show_row(image, [image])

    tiles = related._animated_strip.findChildren(_VideoTile)
    assert 0 < len(tiles) < 20
    assert f"{len(videos)} animations" in caplog.text


def test_a_video_costs_no_read_of_the_library_s_videos(related):
    # The pool is a whole-table read and a parse per row. Only a row that could
    # have animations is worth paying it for, so it is asked for past that test
    # rather than before it — a video shown must not pay to be told it has none.
    related.show_row(_video_row(), [_image_row()])

    assert related.asks == []


def test_an_image_asks_for_them_once(make_related):
    image = _image_row()
    related = make_related(_video_row())

    related.show_row(image, [image])

    assert len(related.asks) == 1
