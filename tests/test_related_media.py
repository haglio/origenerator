"""What else in the library a shown generation is tied to.

Two links stacked under a config tab's settings form — the item this row was
built from, and the videos an image was animated into — fed one row at a time.
They were two attributes and two methods on the config panel, which has a dozen
other things to be about; here they are one widget answering one question.
"""
from __future__ import annotations

import logging

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QMouseEvent, QPixmap

from origenerator.generation_state import GenerationSource
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


def _trim_row(prompt_id="cut1", trimmed_from="vid1", input_image="sdxl_t2i_img1.png"):
    """One cycle cut out of a clip. It carries the clip's params, start frame
    and all — which is what makes the order of the links matter."""
    return {
        "prompt_id": prompt_id, "workflow_name": "wan22_i2v",
        "created_at": "2026-01-02 03:06:07",
        "params_json": f'{{"input_image": "{input_image}"}}',
        "output_files": '[{"filename": "wan22_i2v_vid1_cycle.mp4",'
                        ' "subfolder": "video", "type": "output"}]',
        "thumbnail_path": "cut1_thumb.jpg",
        "trimmed_from": trimmed_from,
    }


def _combined_row(prompt_id="made1", source_video="vid0"):
    return {**_video_row(prompt_id), "source_video": source_video}


@pytest.fixture
def make_related(qtbot):
    """Build a RelatedMedia over a given set of the library's videos, counting
    every time it asks for them."""
    def _make(*videos, held=()):
        by_id = {video["prompt_id"]: video for video in videos}
        widget = RelatedMedia(video_rows=lambda: (asks.append(True), videos)[1],
                              row_of=lambda prompt_id: (looked_up.append(prompt_id),
                                                        by_id.get(prompt_id))[1],
                              held_rows=lambda: list(held),
                              name_of={"img1": "3FA9C0D2 004", "vid0": "77B2E1A0 012"}.get)
        asks: list = []
        looked_up: list = []
        widget.asks = asks
        widget.looked_up = looked_up
        qtbot.addWidget(widget)
        return widget

    return _make


@pytest.fixture
def related(make_related):
    return make_related()


def test_a_row_tied_to_nothing_shows_no_links(related):
    assert related._source_section.isHidden()
    assert related._source_tile.isHidden()
    assert related._animated_strip.isHidden()


def test_a_video_points_back_at_the_image_that_seeded_its_start_frame(related):
    image = _image_row()

    related.show_row(_video_row(), [image])

    assert not related._source_tile.isHidden()
    assert related._source_tile._prompt_id == "img1"
    assert related._animated_strip.isHidden()   # a video is animated into nothing


def test_the_start_image_is_called_by_its_name_not_its_file(related):
    related.show_row(_video_row(), [_image_row()])

    assert related._source_tile._name.text() == "3FA9C0D2 004"


def _hidden_frame():
    return {**_image_row("frame1", "frame1.jpg"), "source": GenerationSource.STARTING_FRAME}


def test_a_video_another_source_made_from_words_alone_points_at_no_source(related):
    video = {**_video_row(input_image="frame1.jpg"), "source": GenerationSource.OUTSIDE}

    related.show_row(video, [_hidden_frame()])

    assert related._source_section.isHidden()


def test_a_video_made_here_from_a_hidden_starting_frame_points_back_at_the_frame(related):
    related.show_row(_video_row(input_image="frame1.jpg"), [_hidden_frame()])

    assert related._source_tile._prompt_id == "frame1"


def test_a_video_combine_made_points_at_the_video_whose_settings_it_followed(make_related):
    related = make_related(_video_row("vid0"))

    related.show_row(_combined_row(), [_image_row()])

    assert related._source_tile._prompt_id == "img1"
    assert not related._source_video_tile.isHidden()
    assert related._source_video_tile._prompt_id == "vid0"
    assert related._source_video_tile._heading.text() == "From source video"
    assert related._source_video_tile._badge.media_type == "video"
    assert related._source_video_tile._name.text() == "77B2E1A0 012"


def test_an_image_lists_the_videos_it_was_animated_into(make_related):
    image = _image_row()
    related = make_related(_video_row())

    related.show_row(image, [image])

    assert not related._animated_strip.isHidden()
    assert len(related._animated_strip.findChildren(_VideoTile)) == 1
    assert related._source_tile.isHidden()      # an image has no start frame


def test_a_hidden_starting_frame_lists_only_the_videos_made_from_it_here(make_related):
    frame = _hidden_frame()
    taken_out_of = {**_video_row("vid1", input_image="frame1.jpg"),
                    "source": GenerationSource.OUTSIDE}
    related = make_related(taken_out_of, _video_row("vid2", input_image="frame1.jpg"))

    related.show_row(frame, [frame])

    assert [tile._prompt_id for tile in related._animated_strip.findChildren(_VideoTile)] == [
        "vid2"]


def test_a_requested_row_points_at_the_item_it_was_asked_about(related):
    # A requested image has no start frame and a requested video's is the one it
    # already had, so the same tile carries the same relation under its own word.
    image = _image_row()

    related.show_row(_image_row("img2", "sdxl_t2i_img2.png"), [],
                     request={"source_row": image})

    assert not related._source_tile.isHidden()
    assert related._source_tile._prompt_id == "img1"


def test_a_click_on_an_animation_names_the_video_that_was_clicked(make_related):
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


def test_a_cut_points_back_at_the_clip_it_was_cut_out_of(make_related):
    clip = _video_row()
    related = make_related(clip)

    related.show_row(_trim_row(), [_image_row()])

    assert not related._source_tile.isHidden()
    assert related._source_tile._prompt_id == "vid1"
    assert related._source_tile._heading.text() == "Trimmed from"
    # The first source that is a video, so the badge has to follow what it shows.
    assert related._source_tile._badge.media_type == "video"


def test_a_cut_does_not_point_past_its_clip_at_that_clip_s_start_frame(make_related):
    # A cut carries its source's params, start frame included. Asking for a start
    # frame first would answer with the image the ORIGINAL was animated from and
    # quietly send the link past the clip the user is actually looking for.
    clip = _video_row()
    related = make_related(clip)

    related.show_row(_trim_row(), [_image_row()])

    assert related._source_tile._prompt_id == "vid1"


def test_a_cut_whose_clip_is_gone_falls_back_to_the_start_frame(make_related):
    # The clip was deleted out from under it. The relation it can still show is
    # the one its copied params carry, rather than an empty slot.
    related = make_related()

    related.show_row(_trim_row(trimmed_from="deleted"), [_image_row()])

    assert related._source_tile._prompt_id == "img1"
    assert related._source_tile._badge.media_type == "image"


def test_a_cut_whose_clip_is_in_the_trash_still_points_back_at_the_clip(make_related):
    related = make_related(held=[_video_row()])

    related.show_row(_trim_row(), [_image_row()])

    assert related._source_tile._prompt_id == "vid1"
    assert related._source_tile._heading.text() == "Trimmed from"


def test_a_video_whose_start_image_is_in_the_trash_still_points_back_at_it(make_related):
    related = make_related(held=[_image_row()])

    related.show_row(_video_row(), [])

    assert not related._source_tile.isHidden()
    assert related._source_tile._prompt_id == "img1"
    assert related._source_tile._heading.text() == "From source image"


def test_a_click_on_the_source_tile_names_the_item_it_points_at(related):
    image = _image_row()
    related.show_row(_video_row(), [image])
    named = []
    related.source_activated.connect(named.append)

    related._source_tile.activated.emit("img1")

    assert named == ["img1"]


def test_the_source_links_sit_in_a_section_headed_source(make_related):
    related = make_related(_video_row("vid0"))

    related.show_row(_combined_row(), [_image_row()])

    section = related._source_section
    assert section._title == "Source"
    assert not section.isHidden()
    assert section.isAncestorOf(related._source_tile)
    assert section.isAncestorOf(related._source_video_tile)


def test_a_row_built_from_nothing_shows_no_source_section(make_related):
    related = make_related(_video_row("vid0"))
    related.show_row(_combined_row(), [_image_row()])

    related.show_row(_image_row(), [_image_row()])

    assert related._source_section.isHidden()


def test_clearing_takes_the_source_section_down(make_related):
    related = make_related(_video_row("vid0"))
    related.show_row(_combined_row(), [_image_row()])

    related.clear()

    assert related._source_section.isHidden()


def test_the_source_video_sits_beside_the_source_image(make_related, qtbot):
    related = make_related(_video_row("vid0"))
    related.show_row(_combined_row(), [_image_row()])
    related.show()
    qtbot.waitExposed(related)

    image, video = related._source_tile.geometry(), related._source_video_tile.geometry()
    assert video.top() == image.top()
    assert video.left() > image.right()


def test_the_source_video_is_drained_of_color_being_only_the_settings(make_related, tmp_path):
    red = QPixmap(16, 16)
    red.fill(QColor("red"))
    red.save(str(tmp_path / "vid0_thumb.png"))
    related = make_related({**_video_row("vid0"), "thumbnail_path": str(tmp_path / "vid0_thumb.png")})

    related.show_row(_combined_row(), [_image_row()])

    shown = related._source_video_tile._thumb.pixmap().toImage().pixelColor(8, 8)
    assert shown.red() == shown.green() == shown.blue()


def test_a_click_on_the_source_video_names_that_video(make_related):
    related = make_related(_video_row("vid0"))
    related.show_row(_combined_row(), [_image_row()])
    named = []
    related.source_activated.connect(named.append)

    related._source_video_tile.activated.emit("vid0")

    assert named == ["vid0"]


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


def test_clearing_puts_the_source_video_down_too(make_related):
    related = make_related(_video_row("vid0"))
    related.show_row(_combined_row(), [_image_row()])

    related.clear()

    assert related._source_video_tile.isHidden()


def test_the_next_row_with_no_source_video_takes_that_link_away(make_related):
    related = make_related(_video_row("vid0"))
    related.show_row(_combined_row(), [_image_row()])

    related.show_row(_video_row(), [_image_row()])

    assert related._source_video_tile.isHidden()


def test_a_source_video_deleted_for_good_leaves_no_link_to_it(related):
    related.show_row(_combined_row(source_video="deleted"), [_image_row()])

    assert related._source_video_tile.isHidden()
    assert related._source_tile._prompt_id == "img1"


def test_a_source_video_in_the_trash_keeps_its_link(make_related):
    related = make_related(held=[_video_row("vid0")])

    related.show_row(_combined_row(), [_image_row()])

    assert not related._source_video_tile.isHidden()
    assert related._source_video_tile._prompt_id == "vid0"


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


def test_a_row_with_no_source_video_looks_none_up(related):
    related.show_row(_video_row(), [_image_row()])

    assert related.looked_up == []


def test_an_image_asks_for_them_once(make_related):
    image = _image_row()
    related = make_related(_video_row())

    related.show_row(image, [image])

    assert len(related.asks) == 1
