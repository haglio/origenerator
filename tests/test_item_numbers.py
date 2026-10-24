"""An item is named by its folder's code and its number in that folder.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

from origenerator.gallery.item_numbers import (
    ItemNumber,
    item_name,
    number_items,
    widest_item_name,
)
from origenerator.gallery.keys import folder_id

FOLDER = "image/sdxl_t2i/0123456789ab"
OTHER_FOLDER = "image/sdxl_t2i/ba9876543210"


def test_an_item_is_named_by_its_folders_code_and_its_number_in_three_digits():
    assert item_name(ItemNumber(FOLDER, 7)) == f"{folder_id(FOLDER)} 007"


def test_an_item_numbered_past_999_is_named_999():
    assert item_name(ItemNumber(FOLDER, 1234)) == f"{folder_id(FOLDER)} 999"


def test_the_widest_name_an_item_can_wear_is_made_of_the_widest_characters():
    widths = {"D": 3, "8": 2}

    assert widest_item_name(lambda text: sum(widths.get(c, 1) for c in text)) == "DDDDDDDD 888"


def test_a_folders_items_are_numbered_from_000_in_the_order_they_were_made():
    numbering = number_items({FOLDER: ["first", "second", "third"]}, {})

    assert numbering == {
        "first": ItemNumber(FOLDER, 0),
        "second": ItemNumber(FOLDER, 1),
        "third": ItemNumber(FOLDER, 2),
    }


def test_an_item_keeps_its_number_when_an_older_one_is_gone():
    recorded = {"first": (FOLDER, 0), "second": (FOLDER, 1), "third": (FOLDER, 2)}

    numbering = number_items({FOLDER: ["first", "third"]}, recorded)

    assert numbering["third"] == ItemNumber(FOLDER, 2)


def test_a_new_item_never_takes_the_number_of_one_gone_for_good():
    recorded = {"first": (FOLDER, 0), "deleted for good": (FOLDER, 1)}

    numbering = number_items({FOLDER: ["first", "newcomer"]}, recorded)

    assert numbering["newcomer"] == ItemNumber(FOLDER, 2)


def test_an_item_that_moved_folders_keeps_its_number_and_the_count_goes_on_from_it():
    recorded = {"moved": (OTHER_FOLDER, 4)}

    numbering = number_items({FOLDER: ["moved", "newcomer"]}, recorded)

    assert numbering == {"moved": ItemNumber(FOLDER, 4), "newcomer": ItemNumber(FOLDER, 5)}


def test_two_items_claiming_one_number_leave_it_to_the_one_made_first():
    recorded = {"older": (FOLDER, 0), "moved": (OTHER_FOLDER, 0)}

    numbering = number_items({FOLDER: ["older", "moved"]}, recorded)

    assert numbering == {"older": ItemNumber(FOLDER, 0), "moved": ItemNumber(FOLDER, 1)}
