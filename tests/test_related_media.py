from __future__ import annotations

import pytest
from PIL import Image
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QHelpEvent, QImage, QMouseEvent
from PySide6.QtWidgets import QApplication, QToolTip
from shared_ui.spacing import GAP_DIALOG
from shared_ui.testing import appending_to

from origenerator.generation_state import GenerationSource
from origenerator.gui.looping_preview import what_plays_in
from origenerator.gui.related_media import (
    ANIMATED_INTO,
    STARTING_FRAME_ANIMATED_INTO,
    RelatedLookups,
    RelatedMedia,
)
from origenerator.gui.source_tile import SourceTile
from origenerator.gui.trash_box import TrashBox
from tests.related_links import (
    POINTING_BACK,
    no_sources,
    settings_tile,
    settings_used_for,
    settings_used_for_tiles,
    source_tile,
)


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
    return {"prompt_id": prompt_id, "source_prompt_id": source_prompt_id,
            "heard": "", "asked": asked}


def _links(section):
    return [(tile.heading, tile._prompt_id)
            for tile in section.findChildren(SourceTile) if not tile.isHidden()]


@pytest.fixture
def make_related(qtbot):
    def _make(*videos, rows=(), held=(), requests=(), movies=None):
        by_id = {row["prompt_id"]: row for row in (*videos, *rows)}
        by_made = {record["prompt_id"]: record for record in requests}
        widget = RelatedMedia(RelatedLookups(
            video_rows=lambda: (asks.append(True), videos)[1],
            row_of=lambda prompt_id: (looked_up.append(prompt_id), by_id.get(prompt_id))[1],
            held_rows=lambda: list(held),
            animated_preview=lambda row: (movies or {}).get(row["prompt_id"]),
            name_of={"img1": "3FA9C0D2 004", "vid0": "77B2E1A0 012"}.get,
            request_of=by_made.get,
            requests_about=lambda prompt_id: [
                record for record in requests
                if record["source_prompt_id"] == prompt_id]))
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
    assert no_sources(related)
    assert source_tile(related).isHidden()
    assert _animated(related) == []


def test_a_video_points_back_at_the_image_that_seeded_its_start_frame(related):
    image = _image_row()

    related.show_row(_video_row(), [image])

    assert not source_tile(related).isHidden()
    assert source_tile(related)._prompt_id == "img1"
    assert _animated(related) == []


def test_the_start_image_is_called_by_its_name_not_its_file(related):
    related.show_row(_video_row(), [_image_row()])

    assert source_tile(related)._name.text() == "3FA9C0D2 004"


def _hidden_frame():
    return {**_image_row("frame1", "frame1.jpg"), "source": GenerationSource.STARTING_FRAME}


def test_a_video_another_source_made_from_words_alone_points_at_no_source(related):
    video = {**_video_row(input_image="frame1.jpg"), "source": GenerationSource.OUTSIDE}

    related.show_row(video, [_hidden_frame()])

    assert no_sources(related)


def test_a_video_made_here_from_a_hidden_starting_frame_points_back_at_the_frame(related):
    related.show_row(_video_row(input_image="frame1.jpg"), [_hidden_frame()])

    assert source_tile(related)._prompt_id == "frame1"


def _taken_out_of(prompt_id="vid1"):
    return {**_video_row(prompt_id, input_image="frame1.jpg"), "source": GenerationSource.OUTSIDE}


def test_a_video_lists_what_its_starting_frame_was_animated_into(make_related):
    video = _taken_out_of()
    related = make_related(video, _video_row("vid2", input_image="frame1.jpg"))

    related.show_row(video, [_hidden_frame()])

    assert _animated(related) == ["vid2"]
    assert _links(related._animations) == [("Starting frame animated into", "vid2")]


def test_a_video_animated_from_another_videos_starting_frame_points_at_that_video(make_related):
    made_here = _video_row("vid2", input_image="frame1.jpg")
    related = make_related(_taken_out_of(), made_here)

    related.show_row(made_here, [_hidden_frame()])

    tile = source_tile(related)
    assert (tile._prompt_id, tile.heading, tile._item_type_icon.media_type) == (
        "vid1", "Animated from starting frame of", "video")


def test_two_videos_animated_from_one_starting_frame_are_not_listed_on_each_other(make_related):
    made_here = _video_row("vid2", input_image="frame1.jpg")
    related = make_related(_taken_out_of(), made_here, _video_row("vid3", input_image="frame1.jpg"))

    related.show_row(made_here, [_hidden_frame()])

    assert _animated(related) == []


def test_an_image_s_links_drop_the_starting_frame_heading_a_video_shown_before_it_wore(
        make_related):
    video, image = _taken_out_of(), _image_row()
    related = make_related(video, _video_row("vid2", input_image="frame1.jpg"), _video_row("vid3"))
    related.show_row(video, [_hidden_frame(), image])

    related.show_row(image, [_hidden_frame(), image])

    assert "Starting frame animated into" not in {heading for heading, _ in _links(related)}


def test_a_video_points_at_each_video_combine_made_with_its_settings_under_combine(make_related):
    related = make_related(_combined_row("made1"), _combined_row("made2"))

    related.show_row(_video_row("vid0"), [_image_row()])

    assert settings_used_for(related) == [("Video settings used for animation of", "made1"), ("Video settings used for animation of", "made2")]


def test_a_video_combine_made_points_at_the_video_whose_settings_it_followed(make_related):
    related = make_related(_video_row("vid0"))

    related.show_row(_combined_row(), [_image_row()])

    assert source_tile(related)._prompt_id == "img1"
    assert not settings_tile(related).isHidden()
    assert settings_tile(related)._prompt_id == "vid0"
    assert settings_tile(related).heading == "Animated using video settings of"
    assert settings_tile(related)._item_type_icon.media_type == "video"
    assert settings_tile(related)._name.text() == "77B2E1A0 012"


def test_an_image_lists_the_videos_it_was_animated_into(make_related):
    image = _image_row()
    related = make_related(_video_row())

    related.show_row(image, [image])

    assert not related._animations.isHidden()
    assert len(related._animations.findChildren(SourceTile)) == 1
    assert source_tile(related).isHidden()


def _animated(related):
    return [tile._prompt_id for tile in related._animations.findChildren(SourceTile)
            if not tile.isHidden() and tile.heading in (ANIMATED_INTO,
                                                                 STARTING_FRAME_ANIMATED_INTO)]


def _drawn_links(related, row, image_rows):
    related.show_row(row, image_rows)
    QApplication.processEvents()
    shown = row["prompt_id"]
    drawn = set()
    for section in (related._requests, related._batch_modified,
                    related._animations, related._trims):
        drawn |= {(other, shown) if heading in POINTING_BACK else (shown, other)
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


def _trash_box_of(widget):
    while widget is not None and not isinstance(widget, TrashBox):
        widget = widget.parentWidget()
    return widget


def _boxed(tiles):
    return {tile._prompt_id: _trash_box_of(tile) is not None for tile in tiles
            if not tile.isHidden()}


def test_an_image_s_animations_in_the_trash_sit_together_in_a_box_labeled_trash(make_related):
    image = _image_row()
    related = make_related(_video_row("vid1"),
                           held=[_video_row("vid2"), _video_row("vid3")])

    related.show_row(image, [image])

    tiles = related._animations.findChildren(SourceTile)
    assert _boxed(tiles) == {"vid1": False, "vid2": True, "vid3": True}
    box, = {_trash_box_of(tile) for tile in tiles} - {None}
    assert box.label.text() == "in the Trash"


def test_linked_items_in_the_trash_sit_in_a_box_labeled_trash(make_related):
    related = make_related(_combined_row("made1"), held=[_combined_row("made2")])

    related.show_row(_video_row("vid0"), [_image_row()])

    assert _boxed(settings_used_for_tiles(related)) == {
        "made1": False, "made2": True}


def test_a_source_image_in_the_trash_sits_in_a_box_labeled_trash(make_related):
    trashed_image = _image_row()
    related = make_related(held=[trashed_image])

    related.show_row(_video_row(), [])

    assert _boxed([source_tile(related)]) == {"img1": True}


def test_a_source_image_put_back_from_the_trash_leaves_its_box(make_related):
    image = _image_row()
    related = make_related(held=[image])
    related.show_row(_video_row(), [])

    related._held_rows = list
    related.show_row(_video_row(), [image])

    assert _boxed([source_tile(related)]) == {"img1": False}


def _failed(row):
    return {**row, "status": "error", "output_files": None, "thumbnail_path": None}


def test_a_run_that_failed_to_make_its_video_is_not_among_the_animations(make_related):
    image = _image_row()
    related = make_related(_video_row("vid1"), _failed(_video_row("vid2")),
                           held=[_failed(_video_row("vid3"))])

    related.show_row(image, [image])

    assert _animated(related) == ["vid1"]


def test_a_run_that_failed_to_make_its_video_is_not_listed_under_combine(make_related):
    related = make_related(_combined_row("made1"), _failed(_combined_row("made2")))

    related.show_row(_video_row("vid0"), [_image_row()])

    assert settings_used_for(related) == [("Video settings used for animation of", "made1")]


def test_a_cut_is_not_among_the_animations_of_the_image_its_clip_was_made_from(make_related):
    image = _image_row()
    related = make_related(_video_row(), _trim_row())

    related.show_row(image, [image])

    assert _animated(related) == ["vid1"]


def test_of_two_images_listing_one_file_only_the_one_the_video_names_lists_it(make_related):
    first, twin = _image_row("img1"), _image_row("img2")
    related = make_related(_video_row())

    related.show_row(_video_row(), [first, twin])
    assert source_tile(related)._prompt_id == "img1"
    related.show_row(twin, [first, twin])

    assert _animated(related) == []


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

    section = related._requests
    assert not section.isHidden()
    assert _links(section) == [("Requested from", "img1")]
    assert no_sources(related)


def test_an_image_points_at_what_was_requested_of_it_under_requests(make_related):
    related = make_related(
        rows=[_image_row("img2", "sdxl_t2i_img2.png"), _image_row("img3", "sdxl_t2i_img3.png")],
        requests=[_request("img3", "img1", asked="two cats"),
                  _request("img2", "img1", asked="two dogs")])

    related.show_row(_image_row(), [])

    assert not related._requests.isHidden()
    assert _links(related._requests) == [
        ("Requested into", "img3"), ("Requested into", "img2")]


def test_an_image_points_at_what_a_folders_modify_batch_made_of_it_as_batch_modified_into(make_related):
    related = make_related(rows=[_image_row("img2", "sdxl_t2i_img2.png")],
                           requests=[_request("img2", "img1")])

    related.show_row(_image_row(), [])

    assert _links(related._batch_modified) == [("Batch-modified into", "img2")]
    assert related._requests.isHidden()


def test_a_requested_row_points_at_the_item_it_was_asked_about_in_the_trash(make_related):
    related = make_related(held=[_image_row()],
                           requests=[_request("img2", "img1", asked="two dogs")])

    related.show_row(_image_row("img2", "sdxl_t2i_img2.png"), [])

    assert _links(related._requests) == [("Requested from", "img1")]


def test_an_image_points_at_what_was_requested_of_it_from_the_trash_too(make_related):
    related = make_related(held=[_image_row("img2", "sdxl_t2i_img2.png")],
                           requests=[_request("img2", "img1", asked="two dogs")])

    related.show_row(_image_row(), [])

    assert _links(related._requests) == [("Requested into", "img2")]


def test_a_request_whose_image_is_gone_leaves_no_link_to_it(make_related):
    related = make_related(requests=[_request("gone", "img1", asked="two dogs")])

    related.show_row(_image_row(), [])

    assert related._requests.isHidden()


def _left_press():
    return QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPoint(1, 1).toPointF(), QPoint(1, 1).toPointF(),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier)


def test_a_click_on_a_requested_into_link_names_that_image(make_related):
    related = make_related(rows=[_image_row("img2", "sdxl_t2i_img2.png")],
                           requests=[_request("img2", "img1", asked="two dogs")])
    related.show_row(_image_row(), [])
    named = []
    related.link_clicked.connect(appending_to(named))

    tile, = related._requests.findChildren(SourceTile)
    tile.mousePressEvent(_left_press())

    assert named == ["img2"]


def test_a_click_that_shows_the_image_it_names_outlives_its_own_link(make_related, qtbot):
    made = _image_row("img2", "sdxl_t2i_img2.png")
    related = make_related(rows=[_image_row(), made],
                           requests=[_request("img2", "img1", asked="two dogs")])
    related.show_row(_image_row(), [])
    related.link_clicked.connect(lambda _prompt_id: related.show_row(made, []))

    tile, = related._requests.findChildren(SourceTile)
    tile.mousePressEvent(_left_press())
    qtbot.wait(1)

    assert _links(related._requests) == [("Requested from", "img1")]


def test_an_image_a_folders_modify_batch_made_points_at_the_one_it_was_batch_modified_from(make_related):
    related = make_related(rows=[_image_row()], requests=[_request("img2", "img1")])

    related.show_row(_image_row("img2", "sdxl_t2i_img2.png"), [])

    section = related._batch_modified
    assert not section.isHidden()
    assert _links(section) == [("Batch-modified from", "img1")]
    assert no_sources(related)
    assert related._requests.isHidden()


def _with_thumbnail(row, tmp_path):
    image = QImage(40, 20, QImage.Format.Format_RGB32)
    image.fill(QColor("gray"))
    path = tmp_path / f"{row['prompt_id']}.png"
    image.save(str(path))
    return {**row, "thumbnail_path": str(path)}


def _batch_modified(prompt_id, source_prompt_id):
    return {**_request(prompt_id, source_prompt_id),
            "old_positive": "a hat", "new_positive": "a cap",
            "old_negative": "", "new_negative": ""}


def _tip_of(section, prompt_id):
    return next(tile.toolTip() for tile in section.findChildren(SourceTile)
                if tile.prompt_id == prompt_id)


def test_hovering_batch_modified_from_shows_the_image_before_then_this_one_then_the_change(
        make_related, tmp_path):
    before = _with_thumbnail(_image_row(), tmp_path)
    after = _with_thumbnail(_image_row("img2", "sdxl_t2i_img2.png"), tmp_path)
    related = make_related(rows=[before, after], requests=[_batch_modified("img2", "img1")])

    related.show_row(after, [])

    tip = _tip_of(related._batch_modified, "img1")
    assert tip.index(before["thumbnail_path"]) < tip.index(after["thumbnail_path"]) < tip.index("cap")
    assert "hat" in tip


def test_hovering_batch_modified_into_shows_this_image_before_the_one_made_of_it(
        make_related, tmp_path):
    before = _with_thumbnail(_image_row(), tmp_path)
    after = _with_thumbnail(_image_row("img2", "sdxl_t2i_img2.png"), tmp_path)
    related = make_related(rows=[before, after], requests=[_batch_modified("img2", "img1")])

    related.show_row(before, [])

    tip = _tip_of(related._batch_modified, "img2")
    assert tip.index(before["thumbnail_path"]) < tip.index(after["thumbnail_path"]) < tip.index("cap")


def test_hovering_requested_from_and_into_shows_the_same_before_and_after(make_related, tmp_path):
    before = _with_thumbnail(_image_row(), tmp_path)
    after = _with_thumbnail(_image_row("img2", "sdxl_t2i_img2.png"), tmp_path)
    request = {**_batch_modified("img2", "img1"), "asked": "a cap instead"}
    related = make_related(rows=[before, after], requests=[request])

    related.show_row(after, [])
    from_tip = _tip_of(related._requests, "img1")
    related.show_row(before, [])
    into_tip = _tip_of(related._requests, "img2")

    for tip in (from_tip, into_tip):
        assert tip.index(before["thumbnail_path"]) < tip.index(after["thumbnail_path"]) < tip.index("cap")


def test_resting_the_mouse_on_a_batch_modified_thumbnail_opens_its_tooltip(make_related, tmp_path):
    before = _with_thumbnail(_image_row(), tmp_path)
    after = _with_thumbnail(_image_row("img2", "sdxl_t2i_img2.png"), tmp_path)
    related = make_related(rows=[before, after], requests=[_batch_modified("img2", "img1")])
    related.show()
    related.show_row(after, [])
    thumbnail = next(tile for tile in related._batch_modified.findChildren(SourceTile)
                     if tile.prompt_id == "img1")._thumb
    place = thumbnail.rect().center()

    QApplication.sendPostedEvents()
    QApplication.sendEvent(thumbnail, QHelpEvent(QEvent.Type.ToolTip, place,
                                                 thumbnail.mapToGlobal(place)))

    assert "cap" in QToolTip.text()


def test_every_kind_of_link_sits_in_the_one_section_headed_links(make_related):
    image = _image_row()
    related = make_related(_video_row())

    related.show_row(image, [image])

    section = related._section
    assert (section.title(), section.isHidden()) == ("Links", False)
    assert all(section.isAncestorOf(row) for row in (
        related._requests, related._batch_modified, related._animations, related._trims))


def test_a_row_animated_into_nothing_shows_no_animations(make_related):
    image = _image_row()
    related = make_related(_video_row())
    related.show_row(image, [image])

    related.show_row(_video_row(), [image])

    assert _animated(related) == []


def test_a_click_on_an_animation_names_the_video_that_was_clicked(make_related):
    image = _image_row()
    related = make_related(_video_row())
    related.show_row(image, [image])
    named = []
    related.link_clicked.connect(appending_to(named))

    tile, = related._animations.findChildren(SourceTile)
    tile.mousePressEvent(QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPoint(1, 1).toPointF(), QPoint(1, 1).toPointF(),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier))

    assert named == ["vid1"]


def test_a_cut_points_back_at_the_clip_it_was_cut_out_of(make_related):
    video = _video_row()
    related = make_related(video)

    related.show_row(_trim_row(), [_image_row()])

    assert not source_tile(related).isHidden()
    assert source_tile(related)._prompt_id == "vid1"
    assert source_tile(related).heading == "Trimmed from"
    assert source_tile(related)._item_type_icon.media_type == "video"


def test_a_clip_points_at_each_cut_out_of_it_under_trims(make_related):
    related = make_related(_trim_row("cut1"), _trim_row("cut2"))

    related.show_row(_video_row(), [_image_row()])

    section = related._trims
    assert _links(section) == [("Trimmed into", "cut1"), ("Trimmed into", "cut2")]


def test_a_cut_does_not_point_past_its_clip_at_that_clip_s_start_frame(make_related):
    video = _video_row()
    related = make_related(video)

    related.show_row(_trim_row(), [_image_row()])

    assert source_tile(related)._prompt_id == "vid1"


def test_a_cut_whose_clip_is_gone_falls_back_to_the_start_frame(make_related):
    related = make_related()

    related.show_row(_trim_row(trimmed_from="deleted"), [_image_row()])

    assert source_tile(related)._prompt_id == "img1"
    assert source_tile(related)._item_type_icon.media_type == "image"


def test_a_cut_whose_video_is_in_the_trash_still_points_back_at_the_video(make_related):
    related = make_related(held=[_video_row()])

    related.show_row(_trim_row(), [_image_row()])

    assert source_tile(related)._prompt_id == "vid1"
    assert source_tile(related).heading == "Trimmed from"


def test_a_video_whose_start_image_is_in_the_trash_still_points_back_at_it(make_related):
    related = make_related(held=[_image_row()])

    related.show_row(_video_row(), [])

    assert not source_tile(related).isHidden()
    assert source_tile(related)._prompt_id == "img1"
    assert source_tile(related).heading == "Animated from"


def test_a_click_on_the_source_tile_names_the_item_it_points_at(related):
    image = _image_row()
    related.show_row(_video_row(), [image])
    named = []
    related.link_clicked.connect(appending_to(named))

    source_tile(related).activated.emit("img1")

    assert named == ["img1"]


def test_a_row_built_from_nothing_shows_no_sources(make_related):
    related = make_related(_video_row("vid0"))
    related.show_row(_combined_row(), [_image_row()])

    related.show_row(_image_row(), [_image_row()])

    assert no_sources(related)


def test_clearing_takes_the_source_section_down(make_related):
    related = make_related(_video_row("vid0"))
    related.show_row(_combined_row(), [_image_row()])

    related.clear()

    assert no_sources(related)


def test_the_source_video_sits_beside_the_source_image(make_related, qtbot):
    related = make_related(_video_row("vid0"))
    related.show_row(_combined_row(), [_image_row()])
    related.resize(800, 600)
    with qtbot.waitExposed(related):
        related.show()

    image, video = source_tile(related).geometry(), settings_tile(related).geometry()
    assert video.top() == image.top()
    assert video.left() > image.right()


def test_a_click_on_the_source_video_names_that_video(make_related):
    related = make_related(_video_row("vid0"))
    related.show_row(_combined_row(), [_image_row()])
    named = []
    related.link_clicked.connect(appending_to(named))

    settings_tile(related).activated.emit("vid0")

    assert named == ["vid0"]


def test_showing_the_next_row_takes_the_last_one_s_answers_away(related):
    image = _image_row()
    related.show_row(_video_row(), [image])
    assert not source_tile(related).isHidden()

    related.show_row(image, [image])

    assert source_tile(related).isHidden()


def test_clearing_puts_both_links_down(make_related):
    image = _image_row()
    related = make_related(_video_row())
    related.show_row(image, [image])

    related.clear()

    assert source_tile(related).isHidden()
    assert _animated(related) == []


def test_clearing_puts_the_source_video_down_too(make_related):
    related = make_related(_video_row("vid0"))
    related.show_row(_combined_row(), [_image_row()])

    related.clear()

    assert settings_tile(related).isHidden()


def test_the_next_row_with_no_source_video_takes_that_link_away(make_related):
    related = make_related(_video_row("vid0"))
    related.show_row(_combined_row(), [_image_row()])

    related.show_row(_video_row(), [_image_row()])

    assert settings_tile(related).isHidden()


def test_a_source_video_deleted_for_good_leaves_no_link_to_it(related):
    related.show_row(_combined_row(source_video="deleted"), [_image_row()])

    assert settings_tile(related).isHidden()
    assert source_tile(related)._prompt_id == "img1"


def test_a_source_video_in_the_trash_keeps_its_link(make_related):
    related = make_related(held=[_video_row("vid0")])

    related.show_row(_combined_row(), [_image_row()])

    assert not settings_tile(related).isHidden()
    assert settings_tile(related)._prompt_id == "vid0"


def test_an_image_lists_every_video_it_was_animated_into_however_many(make_related):
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


def test_an_image_s_animations_read_animated_in(make_related):
    image = _image_row()
    related = make_related(_video_row())

    related.show_row(image, [image])

    assert _links(related._animations) == [("Animated into", "vid1")]


def _two_frames(path):
    frames = [Image.new("RGB", (16, 12), (i * 60, 0, 0)) for i in range(2)]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=80, loop=0)
    return str(path)


def test_a_linked_video_plays_its_animated_thumbnail(make_related, tmp_path):
    image = _image_row()
    related = make_related(_video_row(), movies={"vid1": _two_frames(tmp_path / "vid1.gif")})

    related.show_row(image, [image])

    (tile,) = related._animations.findChildren(SourceTile)
    assert tile._thumb.movie() is not None


def _red_frames(path):
    frames = [Image.new("RGB", (16, 12), (220, 20 + i * 10, 20)) for i in range(2)]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=80, loop=0)
    return str(path)


def _color_at_middle(tile):
    return tile._thumb.pixmap().toImage().pixelColor(8, 6)


def test_the_video_whose_settings_were_used_plays_drained_of_color(make_related, tmp_path):
    related = make_related(_video_row("vid0"), movies={"vid0": _red_frames(tmp_path / "vid0.gif")})

    related.show_row(_combined_row(), [_image_row()])

    shown = _color_at_middle(settings_tile(related))
    assert what_plays_in(settings_tile(related)._thumb) is not None
    assert shown.red() == shown.green() == shown.blue()


def test_a_video_made_with_this_ones_settings_plays_in_color(make_related, tmp_path):
    related = make_related(_combined_row(), movies={"made1": _red_frames(tmp_path / "made1.gif")})

    related.show_row(_video_row("vid0"), [_image_row()])

    (tile,) = settings_used_for_tiles(related)
    assert tile._thumb.movie() is not None


def test_the_tiles_in_a_row_stand_a_wide_gap_apart(make_related, qtbot):
    image = _image_row()
    related = make_related(_video_row("vid1"), _video_row("vid2"))
    related.resize(800, 400)
    with qtbot.waitExposed(related):
        related.show()
    related.show_row(image, [image])
    related._animations.layout().activate()

    left, right = sorted((tile.geometry() for tile in related._animations.findChildren(SourceTile)),
                         key=lambda box: box.x())
    assert right.x() - (left.x() + left.width()) == GAP_DIALOG
