from __future__ import annotations

from origenerator.folder_arrivals import arrivals_in


def _item(number: int, *, starred: bool = False, status: str = "completed") -> dict:
    return {"id": number, "prompt_id": f"p{number}", "starred": 1 if starred else 0,
            "status": status, "output_files": "[]" if status != "completed"
            else f'["item_{number}.png"]'}


def _starred_from(mark: int | None) -> dict:
    return {"starred": True, "favorite_after_id": mark, "enhance_after_id": None}


def _enhancing_from(mark: int | None) -> dict:
    return {"starred": False, "favorite_after_id": None, "enhance_after_id": mark}


def _every_one(_key, _row) -> bool:
    return True


def test_an_item_that_arrives_in_a_starred_folder_is_starred_and_the_mark_moves_past_it():
    found = arrivals_in({"leaf": [_item(3), _item(5)]}, {"leaf": _starred_from(4)},
                        would_enhance=_every_one)

    assert found.to_star == ["p5"]
    assert found.marks == {"leaf": (5, None)}


def test_an_item_waiting_to_be_made_is_starred_as_it_arrives():
    found = arrivals_in({"leaf": [_item(5, status="pending")]}, {"leaf": _starred_from(4)},
                        would_enhance=_every_one)

    assert found.to_star == ["p5"]


def test_an_item_unstarred_after_its_folder_starred_it_is_left_unstarred():
    found = arrivals_in({"leaf": [_item(3), _item(4)]}, {"leaf": _starred_from(4)},
                        would_enhance=_every_one)

    assert found == arrivals_in({}, {}, would_enhance=_every_one)


def test_an_arrival_that_already_has_its_star_only_moves_the_mark():
    found = arrivals_in({"leaf": [_item(5, starred=True)]}, {"leaf": _starred_from(4)},
                        would_enhance=_every_one)

    assert (found.to_star, found.marks) == ([], {"leaf": (5, None)})


def test_a_folder_starred_before_folders_starred_their_items_stars_nothing_on_its_own():
    found = arrivals_in({"leaf": [_item(5)]}, {"leaf": _starred_from(None)},
                        would_enhance=_every_one)

    assert (found.to_star, found.marks) == ([], {})


def test_a_finished_image_that_arrives_where_enhance_is_on_is_enhanced():
    found = arrivals_in({"leaf": [_item(3), _item(5)]}, {"leaf": _enhancing_from(4)},
                        would_enhance=_every_one)

    assert [row["prompt_id"] for row in found.to_enhance["leaf"]] == ["p5"]
    assert found.marks == {"leaf": (None, 5)}


def test_enhance_passes_over_what_it_would_not_enhance():
    found = arrivals_in({"leaf": [_item(5)]}, {"leaf": _enhancing_from(4)},
                        would_enhance=lambda _key, _row: False)

    assert (found.to_enhance, found.marks) == ({}, {"leaf": (None, 5)})


def test_enhance_waits_on_an_item_still_being_made_and_comes_back_to_it():
    leaves = {"leaf": [_item(5, status="pending"), _item(6)]}

    found = arrivals_in(leaves, {"leaf": _enhancing_from(4)}, would_enhance=_every_one)
    assert ([row["prompt_id"] for row in found.to_enhance["leaf"]], found.marks) == (["p6"], {})

    leaves["leaf"][0] = _item(5)
    found = arrivals_in(leaves, {"leaf": _enhancing_from(4)}, would_enhance=_every_one)
    assert [row["prompt_id"] for row in found.to_enhance["leaf"]] == ["p5", "p6"]
    assert found.marks == {"leaf": (None, 6)}


def test_a_folder_with_both_switches_on_moves_both_marks():
    found = arrivals_in({"leaf": [_item(5)]},
                        {"leaf": {"starred": True, "favorite_after_id": 4,
                                  "enhance_after_id": 2}},
                        would_enhance=_every_one)

    assert found.marks == {"leaf": (5, 5)}


def test_a_folder_with_its_switches_off_is_left_alone():
    found = arrivals_in({"leaf": [_item(5)]},
                        {"leaf": {"starred": False, "favorite_after_id": None,
                                  "enhance_after_id": None}},
                        would_enhance=_every_one)

    assert found == arrivals_in({}, {}, would_enhance=_every_one)


def test_a_folder_starred_before_folders_starred_their_items_stars_them_all_once_taken_up():
    leaves = {"leaf": [_item(3), _item(5, starred=True), _item(4)]}

    found = arrivals_in(leaves, {"leaf": _starred_from(None)}, would_enhance=_every_one,
                        older_stars=True)

    assert (sorted(found.to_star), found.marks) == (["p3", "p4"], {"leaf": (5, None)})
