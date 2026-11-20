from __future__ import annotations

import json

from origenerator.gallery import sort_order


def _rows(*names_and_seconds):
    return [{"prompt_id": name, "video_seconds": seconds} for name, seconds in names_and_seconds]


def _ordered(rows, headings, sort):
    ordered, ordered_headings = sort_order.in_order(rows, headings, sort)
    return [row["prompt_id"] for row in ordered], ordered_headings


def test_oldest_first_puts_the_oldest_section_on_top_and_its_oldest_row_first():
    rows = _rows(("new two", 1), ("new one", 1), ("old two", 1), ("old one", 1))
    assert _ordered(rows, ["Today", None, "Yesterday", None], sort_order.OLDEST) == (
        ["old one", "old two", "new one", "new two"], ["Yesterday", None, "Today", None])


def test_longest_first_keeps_the_date_sections_and_sorts_each_by_length():
    rows = _rows(("new short", 2), ("new long", 9), ("old short", 1), ("old long", 5))
    assert _ordered(rows, ["Today", None, "Yesterday", None], sort_order.LONGEST) == (
        ["new long", "new short", "old long", "old short"], ["Today", None, "Yesterday", None])


def test_shortest_first_counts_an_image_as_no_seconds_and_keeps_newest_first_among_equals():
    rows = _rows(("video", 3), ("new image", None), ("old image", None))
    assert _ordered(rows, ["Today", None, None], sort_order.SHORTEST) == (
        ["new image", "old image", "video"], ["Today", None, None])


def _item(filename):
    return {"prompt_id": filename, "output_files": json.dumps([{"filename": filename}])}


def test_a_listing_with_a_video_offers_both_dates_and_both_durations():
    assert sort_order.offered([_item("image one.png"), _item("video one.mp4")]) == (
        sort_order.NEWEST, sort_order.OLDEST, sort_order.LONGEST, sort_order.SHORTEST)


def test_a_listing_of_images_offers_only_the_two_dates():
    assert sort_order.offered([_item("image one.png")]) == (sort_order.NEWEST, sort_order.OLDEST)
