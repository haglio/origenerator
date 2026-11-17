from __future__ import annotations

from origenerator.fix_switches import FIXES_KEY, KEPT_KEY, OFF_KEY, drawn_as, switched, switches_of

BOX = [100, 100, 300, 300]


def fix(part: str, *over: str, box=BOX) -> dict:
    return {"part": part, "box": box, "over": list(over)}


def enhanced(*fixes, off=()) -> dict:
    entry = {"filename": "enhanced.png", KEPT_KEY: "run-1", FIXES_KEY: list(fixes)}
    return {**entry, OFF_KEY: list(off)} if off else entry


def held(entry: dict) -> dict:
    return {switch.part: switch.held_by for switch in switches_of(entry)}


def test_an_enhancement_made_before_fixes_were_kept_has_no_switches():
    assert switches_of({"filename": "enhanced.png"}) == []


def test_every_fix_starts_on_and_free_where_none_was_drawn_over_another():
    entry = enhanced(fix("faces"), fix("hands"))

    assert [(s.part, s.on, s.can_be_switched) for s in switches_of(entry)] == [
        ("faces", True, True), ("hands", True, True)]


def test_a_fix_is_held_on_by_a_fix_drawn_over_part_of_it():
    entry = enhanced(fix("faces"), fix("hands"), fix("eyes", "faces"))

    assert held(entry) == {"faces": ("eyes",), "hands": (), "eyes": ()}


def test_a_fix_is_free_once_the_fix_drawn_over_it_is_off():
    entry = enhanced(fix("faces"), fix("eyes", "faces"), off=["eyes"])

    assert held(entry) == {"faces": (), "eyes": ()}


def test_a_fix_that_is_off_is_held_off_by_the_off_fix_it_was_drawn_over():
    entry = enhanced(fix("faces"), fix("eyes", "faces"), off=["eyes", "faces"])

    assert held(entry) == {"faces": (), "eyes": ("faces",)}


def test_a_fix_that_redrew_nothing_cannot_be_switched():
    (switch,) = switches_of(enhanced(fix("teeth", box=None)))

    assert (switch.redrew_something, switch.can_be_switched) == (False, False)


def test_switching_a_fix_off_writes_it_down_and_on_again_takes_it_back():
    entry = enhanced(fix("faces"), fix("hands"))

    off = switched(entry, "hands", False)

    assert off[OFF_KEY] == ["hands"]
    assert switched(off, "hands", True) == entry


def test_a_held_fix_is_not_switched():
    entry = enhanced(fix("faces"), fix("eyes", "faces"))

    assert switched(entry, "faces", False) is None


def test_switching_a_fix_to_where_it_already_is_changes_nothing():
    assert switched(enhanced(fix("faces")), "faces", True) is None


def test_a_fix_is_found_by_the_order_it_was_drawn_in_and_where_it_drew():
    entry = enhanced(fix("faces"), fix("hands", box=[1, 2, 3, 4]))

    assert drawn_as(entry, "hands") == (1, [1, 2, 3, 4])
