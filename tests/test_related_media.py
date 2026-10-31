"""What else in the library a shown generation is tied to: the links under a
config tab's settings form, fed one row at a time."""
from __future__ import annotations

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QMouseEvent, QPixmap
from PyQt6.QtWidgets import QApplication

from origenerator.generation_state import GenerationSource
from origenerator.gui.animated_strip import _VideoTile
from origenerator.gui.related_media import RelatedMedia
from origenerator.gui.source_tile import SourceTile


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
    """One cycle cut out of a video. It carries the video's params, start frame
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


def _request(prompt_id, source_prompt_id, asked=""):
    """The record a request leaves, with its words, or a folder's Modify, with none."""
    return {"prompt_id": prompt_id, "source_prompt_id": source_prompt_id,
            "heard": "", "asked": asked}


def _links(section):
    """(heading, prompt id) for each link a section shows, in its order."""
    return [(tile._heading.text(), tile._prompt_id)
            for tile in section.findChildren(SourceTile) if not tile.isHidden()]


@pytest.fixture
def make_related(qtbot):
    """Build a RelatedMedia over a given set of the library's videos, any other
    rows, the items the Trash holds and the request records it can look up,
    counting every time it asks for the videos."""
    def _make(*videos, rows=(), held=(), requests=()):
        by_id = {row["prompt_id"]: row for row in (*videos, *rows)}
        by_made = {record["prompt_id"]: record for record in requests}
        widget = RelatedMedia(video_rows=lambda: (asks.append(True), videos)[1],
                              row_of=lambda prompt_id: (looked_up.append(prompt_id),
                                                        by_id.get(prompt_id))[1],
                              held_rows=lambda: list(held),
                              name_of={"img1": "3FA9C0D2 004", "vid0": "77B2E1A0 012"}.get,
                              request_of=by_made.get,
                              requests_about=lambda prompt_id: [
                                  record for record in requests
                                  if record["source_prompt_id"] == prompt_id])
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


def _taken_out_of(prompt_id="vid1"):
    return {**_video_row(prompt_id, input_image="frame1.jpg"), "source": GenerationSource.OUTSIDE}


def test_a_video_lists_what_its_starting_frame_was_animated_into(make_related):
    video = _taken_out_of()
    related = make_related(video, _video_row("vid2", input_image="frame1.jpg"))

    related.show_row(video, [_hidden_frame()])

    assert _animated(related) == ["vid2"]
    assert related._animated_strip._heading.text() == "Starting frame animated in"


def test_a_video_animated_from_another_videos_starting_frame_points_at_that_video(make_related):
    made_here = _video_row("vid2", input_image="frame1.jpg")
    related = make_related(_taken_out_of(), made_here)

    related.show_row(made_here, [_hidden_frame()])

    tile = related._source_tile
    assert (tile._prompt_id, tile._heading.text(), tile._item_type_icon.media_type) == (
        "vid1", "From starting frame of", "video")


def test_two_videos_animated_from_one_starting_frame_are_not_listed_on_each_other(make_related):
    made_here = _video_row("vid2", input_image="frame1.jpg")
    related = make_related(_taken_out_of(), made_here, _video_row("vid3", input_image="frame1.jpg"))

    related.show_row(made_here, [_hidden_frame()])

    assert related._animations_section.isHidden()


def test_an_image_keeps_its_own_heading_after_a_videos_starting_frame_was_shown(make_related):
    video, image = _taken_out_of(), _image_row()
    related = make_related(video, _video_row("vid2", input_image="frame1.jpg"), _video_row("vid3"))
    related.show_row(video, [_hidden_frame(), image])

    related.show_row(image, [_hidden_frame(), image])

    assert related._animated_strip._heading.text() == "Animated in"


def test_a_video_points_at_each_video_combine_made_with_its_settings_under_combine(make_related):
    related = make_related(_combined_row("made1"), _combined_row("made2"))

    related.show_row(_video_row("vid0"), [_image_row()])

    section = related._combine_section
    assert section._title == "Combine"
    assert _links(section) == [("Source video for", "made1"), ("Source video for", "made2")]


def test_a_video_combine_made_points_at_the_video_whose_settings_it_followed(make_related):
    related = make_related(_video_row("vid0"))

    related.show_row(_combined_row(), [_image_row()])

    assert related._source_tile._prompt_id == "img1"
    assert not related._source_video_tile.isHidden()
    assert related._source_video_tile._prompt_id == "vid0"
    assert related._source_video_tile._heading.text() == "From source video"
    assert related._source_video_tile._item_type_icon.media_type == "video"
    assert related._source_video_tile._name.text() == "77B2E1A0 012"


def test_an_image_lists_the_videos_it_was_animated_into(make_related):
    image = _image_row()
    related = make_related(_video_row())

    related.show_row(image, [image])

    assert not related._animated_strip.isHidden()
    assert len(related._animated_strip.findChildren(_VideoTile)) == 1
    assert related._source_tile.isHidden()      # an image has no start frame


def _animated(related):
    """The prompt id of each video in the image's Animated in strip, in its order."""
    return [tile._prompt_id for tile in related._animated_strip._host.findChildren(_VideoTile)]


def _drawn_links(related, row, image_rows):
    """(made from, made into) for each link the pane draws on *row*."""
    related.show_row(row, image_rows)
    QApplication.processEvents()
    shown = row["prompt_id"]
    drawn = {(tile._prompt_id, shown) for tile in (related._source_tile,
                                                   related._source_video_tile)
             if not tile.isHidden()}
    drawn |= {(shown, video) for video in _animated(related)}
    for section in (related._requests_section, related._modifications_section,
                    related._combine_section, related._trims_section):
        drawn |= {(other, shown) if heading.endswith(" from") else (shown, other)
                  for heading, other in _links(section)}
    return drawn


def test_every_link_is_drawn_on_both_of_the_items_it_ties(make_related):
    image, twin = _image_row("img1"), _image_row("twin")
    kept, trashed = _video_row("vid1"), _video_row("vid2")
    cut = _trim_row("cut1", trimmed_from="vid1")
    combined, combined_in_trash = _combined_row("made1", "vid1"), _combined_row("made2", "vid2")
    requested = _image_row("img2", "sdxl_t2i_img2.png")
    modified = _image_row("img3", "sdxl_t2i_img3.png")
    asked_of_trash = _image_row("img4", "sdxl_t2i_img4.png")
    taken_out_of = _taken_out_of("vid3")
    from_its_frame = _video_row("vid4", input_image="frame1.jpg")
    related = make_related(kept, cut, combined, taken_out_of, from_its_frame,
                           rows=[image, twin, requested, asked_of_trash],
                           held=[trashed, combined_in_trash, modified],
                           requests=[_request("img2", "img1", asked="two dogs"),
                                     _request("img3", "img1"),
                                     _request("img4", "img3", asked="two cats")])
    items = [image, twin, kept, trashed, cut, combined, combined_in_trash, requested,
             modified, asked_of_trash, taken_out_of, from_its_frame]
    image_rows = [image, twin, requested, asked_of_trash, _hidden_frame()]

    drawn = {item["prompt_id"]: _drawn_links(related, item, image_rows) for item in items}

    one_ended = [(made_from, made_into) for shown, links in drawn.items()
                 for made_from, made_into in links
                 if (made_from, made_into) not in drawn[made_into if made_from == shown
                                                          else made_from]]
    assert one_ended == []
    assert sum(map(len, drawn.values())) == 2 * 11


def test_an_image_lists_the_videos_in_the_trash_it_was_animated_into(make_related):
    image = _image_row()
    related = make_related(held=[_video_row()])

    related.show_row(image, [image])

    assert _animated(related) == ["vid1"]


def test_a_cut_is_not_among_the_animations_of_the_image_its_clip_was_made_from(make_related):
    # The cut's own link goes to its clip, so the image has no link to give back.
    image = _image_row()
    related = make_related(_video_row(), _trim_row())

    related.show_row(image, [image])

    assert _animated(related) == ["vid1"]


def test_of_two_images_listing_one_file_only_the_one_the_video_names_lists_it(make_related):
    first, twin = _image_row("img1"), _image_row("img2")
    related = make_related(_video_row())

    related.show_row(_video_row(), [first, twin])
    assert related._source_tile._prompt_id == "img1"
    related.show_row(twin, [first, twin])

    assert related._animations_section.isHidden()


def test_a_hidden_starting_frame_lists_only_the_videos_made_from_it_here(make_related):
    frame = _hidden_frame()
    taken_out_of = {**_video_row("vid1", input_image="frame1.jpg"),
                    "source": GenerationSource.OUTSIDE}
    related = make_related(taken_out_of, _video_row("vid2", input_image="frame1.jpg"))

    related.show_row(frame, [frame])

    assert _animated(related) == ["vid2"]


def test_a_requested_row_points_at_the_item_it_was_asked_about_under_requests(make_related):
    related = make_related(rows=[_image_row()],
                           requests=[_request("img2", "img1", asked="two dogs")])

    related.show_row(_image_row("img2", "sdxl_t2i_img2.png"), [])

    section = related._requests_section
    assert section._title == "Requests"
    assert not section.isHidden()
    assert _links(section) == [("Requested from", "img1")]
    assert related._source_section.isHidden()


def test_an_image_points_at_what_was_requested_of_it_under_requests(make_related):
    related = make_related(
        rows=[_image_row("img2", "sdxl_t2i_img2.png"), _image_row("img3", "sdxl_t2i_img3.png")],
        requests=[_request("img3", "img1", asked="two cats"),
                  _request("img2", "img1", asked="two dogs")])

    related.show_row(_image_row(), [])

    assert not related._requests_section.isHidden()
    assert _links(related._requests_section) == [
        ("Requested into", "img3"), ("Requested into", "img2")]


def test_an_image_points_at_what_a_folders_modify_made_of_it_under_modifications(make_related):
    related = make_related(rows=[_image_row("img2", "sdxl_t2i_img2.png")],
                           requests=[_request("img2", "img1")])

    related.show_row(_image_row(), [])

    assert _links(related._modifications_section) == [("Modified into", "img2")]
    assert related._requests_section.isHidden()


def test_a_requested_row_points_at_the_item_it_was_asked_about_in_the_trash(make_related):
    related = make_related(held=[_image_row()],
                           requests=[_request("img2", "img1", asked="two dogs")])

    related.show_row(_image_row("img2", "sdxl_t2i_img2.png"), [])

    assert _links(related._requests_section) == [("Requested from", "img1")]


def test_an_image_points_at_what_was_requested_of_it_from_the_trash_too(make_related):
    related = make_related(held=[_image_row("img2", "sdxl_t2i_img2.png")],
                           requests=[_request("img2", "img1", asked="two dogs")])

    related.show_row(_image_row(), [])

    assert _links(related._requests_section) == [("Requested into", "img2")]


def test_a_request_whose_image_is_gone_leaves_no_link_to_it(make_related):
    related = make_related(requests=[_request("gone", "img1", asked="two dogs")])

    related.show_row(_image_row(), [])

    assert related._requests_section.isHidden()


def _left_press():
    return QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPoint(1, 1).toPointF(),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier)


def test_a_click_on_a_requested_into_link_names_that_image(make_related):
    related = make_related(rows=[_image_row("img2", "sdxl_t2i_img2.png")],
                           requests=[_request("img2", "img1", asked="two dogs")])
    related.show_row(_image_row(), [])
    named = []
    related.link_clicked.connect(named.append)

    tile, = related._requests_section.findChildren(SourceTile)
    tile.mousePressEvent(_left_press())

    assert named == ["img2"]


def test_a_click_that_shows_the_image_it_names_outlives_its_own_link(make_related, qtbot):
    # Following the link shows that image, whose links replace the one clicked
    # while its click is still being handled.
    made = _image_row("img2", "sdxl_t2i_img2.png")
    related = make_related(rows=[_image_row(), made],
                           requests=[_request("img2", "img1", asked="two dogs")])
    related.show_row(_image_row(), [])
    related.link_clicked.connect(lambda _prompt_id: related.show_row(made, []))

    tile, = related._requests_section.findChildren(SourceTile)
    tile.mousePressEvent(_left_press())
    qtbot.wait(1)

    assert _links(related._requests_section) == [("Requested from", "img1")]


def test_an_image_a_folders_modify_made_points_at_the_one_it_was_modified_from(make_related):
    related = make_related(rows=[_image_row()], requests=[_request("img2", "img1")])

    related.show_row(_image_row("img2", "sdxl_t2i_img2.png"), [])

    section = related._modifications_section
    assert section._title == "Modifications"
    assert not section.isHidden()
    assert _links(section) == [("Modified from", "img1")]
    assert related._source_section.isHidden()
    assert related._requests_section.isHidden()


def test_the_animations_sit_in_a_section_headed_animations(make_related):
    image = _image_row()
    related = make_related(_video_row())

    related.show_row(image, [image])

    section = related._animations_section
    assert section._title == "Animations"
    assert not section.isHidden()
    assert section.isAncestorOf(related._animated_strip)


def test_a_row_animated_into_nothing_shows_no_animations_section(make_related):
    image = _image_row()
    related = make_related(_video_row())
    related.show_row(image, [image])

    related.show_row(_video_row(), [image])

    assert related._animations_section.isHidden()


def test_a_click_on_an_animation_names_the_video_that_was_clicked(make_related):
    image = _image_row()
    related = make_related(_video_row())
    related.show_row(image, [image])
    named = []
    related.link_clicked.connect(named.append)

    tile, = related._animated_strip.findChildren(_VideoTile)
    tile.mousePressEvent(QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPoint(1, 1).toPointF(),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier))

    assert named == ["vid1"]


def test_a_cut_points_back_at_the_clip_it_was_cut_out_of(make_related):
    video = _video_row()
    related = make_related(video)

    related.show_row(_trim_row(), [_image_row()])

    assert not related._source_tile.isHidden()
    assert related._source_tile._prompt_id == "vid1"
    assert related._source_tile._heading.text() == "Trimmed from"
    # The first source that is a video, so the badge has to follow what it shows.
    assert related._source_tile._item_type_icon.media_type == "video"


def test_a_clip_points_at_each_cut_out_of_it_under_trims(make_related):
    related = make_related(_trim_row("cut1"), _trim_row("cut2"))

    related.show_row(_video_row(), [_image_row()])

    section = related._trims_section
    assert section._title == "Trims"
    assert _links(section) == [("Trimmed into", "cut1"), ("Trimmed into", "cut2")]


def test_a_cut_does_not_point_past_its_clip_at_that_clip_s_start_frame(make_related):
    # A cut carries its source's params, start frame included. Asking for a start
    # frame first would answer with the image the ORIGINAL was animated from and
    # quietly send the link past the video the user is actually looking for.
    video = _video_row()
    related = make_related(video)

    related.show_row(_trim_row(), [_image_row()])

    assert related._source_tile._prompt_id == "vid1"


def test_a_cut_whose_clip_is_gone_falls_back_to_the_start_frame(make_related):
    # The video was deleted out from under it. The relation it can still show is
    # the one its copied params carry, rather than an empty slot.
    related = make_related()

    related.show_row(_trim_row(trimmed_from="deleted"), [_image_row()])

    assert related._source_tile._prompt_id == "img1"
    assert related._source_tile._item_type_icon.media_type == "image"


def test_a_cut_whose_video_is_in_the_trash_still_points_back_at_the_video(make_related):
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
    related.link_clicked.connect(named.append)

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
    with qtbot.waitExposed(related):
        related.show()

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
    related.link_clicked.connect(named.append)

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
    assert related._animations_section.isHidden()


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


def test_an_image_lists_every_video_it_was_animated_into_however_many(make_related):
    # Each of them links back to the image, so each is linked from it.
    image = _image_row()
    videos = [_video_row(f"vid{n}") for n in range(20)]
    related = make_related(*videos)

    related.show_row(image, [image])

    assert _animated(related) == [f"vid{n}" for n in range(20)]


def test_a_row_with_no_source_video_looks_none_up(related):
    related.show_row(_video_row(), [_image_row()])

    assert related.looked_up == []


@pytest.mark.parametrize("shown", [_image_row(), _video_row()], ids=["image", "video"])
def test_a_showing_asks_for_the_library_s_videos_once(make_related, shown):
    related = make_related(_video_row())

    related.show_row(shown, [_image_row()])

    assert len(related.asks) == 1
