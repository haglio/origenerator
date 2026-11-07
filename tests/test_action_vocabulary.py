from __future__ import annotations

from origenerator.action_labels import Labels
from origenerator.action_vocabulary import Tile, tiles, vocabulary
from origenerator.media import MediaType

_IMAGES = {"image_actions": {
    "buttons": {"one": ["alpha"], "two": ["alpha", "beta"], "three": ["gamma"]},
    "grid": [["two", "one"], ["three"]],
    "checkboxes": ["first box", "second box"],
    "formerly": {"old two": {"actions": ["alpha", "beta"]},
                 "gone": {"actions": [], "checked": ["first box"]}},
    "drawn_as": {"two": "older two"},
}}


def test_the_buttons_come_from_the_overlay_in_its_order_each_with_the_actions_it_saves():
    named = vocabulary(MediaType.IMAGE, _IMAGES)

    assert named.buttons == {"one": ("alpha",), "two": ("alpha", "beta"),
                             "three": ("gamma",)}


def test_the_checkboxes_come_from_the_overlay_in_its_order():
    assert vocabulary(MediaType.IMAGE, _IMAGES).checkboxes == ("first box", "second box")


def test_images_and_videos_each_read_their_own_block():
    content = {**_IMAGES, "video_actions": {"buttons": {"four": ["delta"]},
                                           "checkboxes": ["third box"]}}

    named = vocabulary(MediaType.VIDEO, content)

    assert (named.buttons, named.checkboxes) == ({"four": ("delta",)}, ("third box",))


def test_an_overlay_without_the_block_offers_no_buttons_and_no_checkboxes():
    named = vocabulary(MediaType.VIDEO, {})

    assert (named.buttons, named.tiles, named.checkboxes) == ({}, (), ())


def test_a_bad_button_costs_that_button_and_no_more():
    content = {"image_actions": {"buttons": {"one": ["alpha", 7, "", " beta "],
                                             "": ["alpha"], "two": "alpha", " three ": []}}}

    assert vocabulary(MediaType.IMAGE, content).buttons == {"one": ("alpha", "beta"),
                                                            "three": ()}


def test_the_grid_is_the_rows_the_overlay_arranges_the_buttons_in():
    assert vocabulary(MediaType.IMAGE, _IMAGES).tiles == (
        Tile("two", 0, 0), Tile("one", 0, 1), Tile("three", 1, 0))


def test_a_name_a_button_used_to_have_reads_as_the_labels_it_now_means():
    named = vocabulary(MediaType.IMAGE, _IMAGES)

    assert named.read_as("old two") == Labels(("alpha", "beta"))
    assert named.read_as("gone") == Labels((), ("first box",))


def test_a_buttons_own_name_reads_as_the_actions_it_saves_whatever_its_case_and_spacing():
    named = vocabulary(MediaType.IMAGE, _IMAGES)

    assert named.read_as("  TWO ") == Labels(("alpha", "beta"))


def test_a_name_neither_a_button_nor_one_a_button_had_reads_as_nothing():
    assert vocabulary(MediaType.IMAGE, _IMAGES).read_as("never heard of") is None


def test_a_button_drawn_under_another_name_is_found_by_that_name():
    named = vocabulary(MediaType.IMAGE, _IMAGES)

    assert (named.drawing_name("two"), named.drawing_name("one")) == ("older two", "one")


def test_an_action_the_grid_leaves_out_still_gets_a_button():
    assert tiles(("one", "two", "three"), [["two", "one"]]) == (
        Tile("two", 0, 0), Tile("one", 0, 1), Tile("three", 1, 0))


def test_a_name_the_list_no_longer_carries_is_not_given_a_button():
    assert tiles(("one",), [["one", "renamed"]]) == (Tile("one", 0, 0),)


def test_an_action_the_grid_names_twice_is_drawn_once():
    assert tiles(("one", "two"), [["one", "two"], ["one"]]) == (
        Tile("one", 0, 0), Tile("two", 0, 1))


def test_a_grid_that_is_not_rows_leaves_every_action_to_the_row_after_it():
    assert tiles(("one", "two"), "one") == (Tile("one", 0, 0), Tile("two", 0, 1))


def test_a_cell_reaching_across_two_columns_is_one_tile_as_wide_as_both():
    assert tiles(("one", "two"), [[["one", 2], "two"]]) == (
        Tile("one", 0, 0, columns=2), Tile("two", 0, 2))


def test_an_empty_cell_is_a_hole_and_the_cell_after_it_keeps_its_column():
    assert tiles(("one", "two"), [["one", "", "two"]]) == (Tile("one", 0, 0), Tile("two", 0, 2))


def test_a_cell_reaching_down_the_rows_is_one_tile_as_tall_as_all_of_them():
    assert tiles(("one", "two"), [[["one", 1, 9]], ["two"]]) == (
        Tile("one", 0, 0, rows=9), Tile("two", 1, 0))
