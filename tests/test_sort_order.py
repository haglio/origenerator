from __future__ import annotations

import json

from origenerator import gallery
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


def test_longest_first_drops_the_date_headings_and_sorts_every_item_by_length():
    rows = _rows(("new short", 2), ("new long", 9), ("old short", 1), ("old long", 5))
    assert _ordered(rows, ["Today", None, "Yesterday", None], sort_order.LONGEST) == (
        ["new long", "old long", "new short", "old short"], [None, None, None, None])


def test_shortest_first_counts_an_image_as_no_seconds_and_keeps_newest_first_among_equals():
    rows = _rows(("video", 3), ("new image", None), ("old image", None))
    assert _ordered(rows, ["Today", None, "Yesterday"], sort_order.SHORTEST) == (
        ["new image", "old image", "video"], [None, None, None])


def _item(filename):
    return {"prompt_id": filename, "output_files": json.dumps([{"filename": filename}])}


def test_a_listing_with_a_video_offers_both_dates_and_both_durations():
    assert sort_order.offered([_item("image one.png"), _item("video one.mp4")]) == (
        sort_order.LATEST, sort_order.OLDEST, sort_order.LONGEST, sort_order.SHORTEST)


def test_a_listing_of_images_offers_only_the_two_dates():
    assert sort_order.offered([_item("image one.png")]) == (sort_order.LATEST, sort_order.OLDEST)


def _folder(name, *stamps):
    return gallery.SettingsGroup(key=name, label=name, rows=[
        {"prompt_id": f"{name}{n}", "created_at": stamp} for n, stamp in enumerate(stamps)])


def test_folders_go_in_order_of_the_newest_item_each_holds():
    folders = [_folder("alpha", "2026-01-01 10:00:00"),
               _folder("beta", "2026-03-01 10:00:00", "2025-01-01 10:00:00"),
               _folder("gamma", "2026-02-01 10:00:00")]
    assert ([f.key for f in sort_order.folders_in_order(folders, sort_order.LATEST)],
            [f.key for f in sort_order.folders_in_order(folders, sort_order.OLDEST)]) == (
        ["beta", "gamma", "alpha"], ["alpha", "gamma", "beta"])
