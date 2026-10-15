from __future__ import annotations

from origenerator.picture_states import state_grid, state_names


def test_the_states_come_from_the_overlay_in_the_order_it_lists_them():
    content = {"picture_states": ["state two", "state one", "state three"]}

    assert state_names(content) == ("state two", "state one", "state three")


def test_an_overlay_that_predates_the_states_offers_none():
    assert state_names({}) == ()


def test_a_bad_line_in_the_overlay_costs_that_line_and_no_more():
    content = {"picture_states": ["state one", 7, "", "  ", None, "state one", " state two "]}

    assert state_names(content) == ("state one", "state two")


def test_states_that_are_not_a_list_are_no_states():
    assert state_names({"picture_states": "state one"}) == ()


def test_the_grid_is_the_rows_the_overlay_arranges_the_buttons_in():
    content = {"picture_states": ["one", "two", "three"],
               "picture_state_grid": [["two", "one"], ["three"]]}

    assert state_grid(content) == (("two", "one"), ("three",))


def test_an_action_the_grid_leaves_out_still_gets_a_button():
    content = {"picture_states": ["one", "two", "three"],
               "picture_state_grid": [["two", "one"]]}

    assert state_grid(content) == (("two", "one"), ("three",))


def test_a_name_the_list_no_longer_carries_is_not_given_a_button():
    content = {"picture_states": ["one"], "picture_state_grid": [["one", "renamed"]]}

    assert state_grid(content) == (("one",),)


def test_an_action_the_grid_names_twice_is_drawn_once():
    content = {"picture_states": ["one", "two"],
               "picture_state_grid": [["one", "two"], ["one"]]}

    assert state_grid(content) == (("one", "two"),)


def test_a_grid_that_is_not_rows_leaves_every_action_to_the_row_after_it():
    content = {"picture_states": ["one", "two"], "picture_state_grid": "one"}

    assert state_grid(content) == (("one", "two"),)
