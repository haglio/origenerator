from __future__ import annotations

import json

from origenerator.gallery import sort_order
from origenerator.gui.sort_by import SortBy


def _item(filename):
    return {"prompt_id": filename, "output_files": json.dumps([{"filename": filename}])}


_VIDEOS = [_item("video one.mp4")]
_IMAGES = [_item("image one.png")]


def _offered(sort_by) -> list[str]:
    dropdown = sort_by.dropdown
    return [dropdown.itemText(index) for index in range(dropdown.count())]


def test_a_listing_with_videos_offers_both_dates_and_both_durations(qapp):
    sort_by = SortBy()
    assert sort_by.for_listing(_VIDEOS) == sort_order.NEWEST
    assert _offered(sort_by) == ["Date (newest first)", "Date (oldest first)",
                                 "Duration (longest first)", "Duration (shortest first)"]


def test_a_pick_is_announced_and_kept_for_the_next_listing(qapp):
    sort_by = SortBy()
    sort_by.for_listing(_VIDEOS)
    heard = []
    sort_by.changed.connect(lambda: heard.append(True))
    sort_by.dropdown.setCurrentIndex(2)
    assert heard == [True]
    assert sort_by.for_listing(_VIDEOS) == sort_order.LONGEST
    assert sort_by.dropdown.currentText() == "Duration (longest first)"


def test_an_images_listing_offers_only_the_dates_and_keeps_a_duration_pick_for_videos(qapp):
    sort_by = SortBy()
    sort_by.choose(sort_order.SHORTEST)
    assert sort_by.for_listing(_IMAGES) == sort_order.NEWEST
    assert _offered(sort_by) == ["Date (newest first)", "Date (oldest first)"]
    assert sort_by.chosen() == sort_order.SHORTEST
    assert sort_by.for_listing(_VIDEOS) == sort_order.SHORTEST


def test_filling_the_dropdown_for_a_listing_announces_nothing(qapp):
    sort_by = SortBy()
    heard = []
    sort_by.changed.connect(lambda: heard.append(True))
    sort_by.choose(sort_order.OLDEST)
    sort_by.for_listing(_VIDEOS)
    sort_by.for_listing(_IMAGES)
    assert heard == []


def test_a_saved_choice_nobody_offers_any_more_reads_as_newest_first(qapp):
    sort_by = SortBy()
    sort_by.choose("by color")
    assert sort_by.chosen() == sort_order.NEWEST


def test_it_shows_for_a_listing_of_items_and_hides_where_there_is_none(qapp):
    sort_by = SortBy()
    sort_by.for_listing(_IMAGES)
    assert not sort_by.isHidden()
    sort_by.no_listing()
    assert sort_by.isHidden()
