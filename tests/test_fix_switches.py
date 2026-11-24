from __future__ import annotations

from origenerator.fix_switches import (
    FIXES_KEY,
    KEPT_KEY,
    LEFT_OUT_KEY,
    OFF_KEY,
    drawn_as,
    left_out_of_a_re_enhance,
    marked,
    switched,
    switches_of,
)

BOX = [100, 100, 300, 300]


def fix(part: str, *over: str, box=BOX) -> dict:
    return {"part": part, "box": box, "over": list(over)}


def enhanced(*fixes, off=(), bad=()) -> dict:
    entry = {"filename": "enhanced.png", KEPT_KEY: "run-1", FIXES_KEY: list(fixes)}
    if off:
        entry[OFF_KEY] = list(off)
    if bad:
        entry[LEFT_OUT_KEY] = list(bad)
    return entry


def held(entry: dict) -> dict:
    return {switch.part: switch.held_by for switch in switches_of(entry)}


def can_be_switched(entry: dict) -> dict:
    return {switch.part: switch.can_be_switched for switch in switches_of(entry)}


def test_an_enhancement_made_before_fixes_were_kept_has_no_switches():
    assert switches_of({"filename": "enhanced.png"}) == []


def test_every_fix_starts_on_unmarked_and_free_where_none_was_drawn_over_another():
    entry = enhanced(fix("faces"), fix("hands"))

    assert [(s.part, s.on, s.bad) for s in switches_of(entry)] == [
        ("faces", True, False), ("hands", True, False)]
    assert can_be_switched(entry) == {"faces": True, "hands": True}


def test_a_fix_is_held_on_by_a_fix_drawn_over_part_of_it():
    entry = enhanced(fix("faces"), fix("hands"), fix("eyes", "faces"))

    assert held(entry) == {"faces": ("eyes",), "hands": (), "eyes": ()}
    assert can_be_switched(entry) == {"faces": False, "hands": True, "eyes": True}


def test_a_fix_is_free_once_the_fix_drawn_over_it_is_off():
    entry = enhanced(fix("faces"), fix("eyes", "faces"), off=["eyes"])

    assert held(entry) == {"faces": (), "eyes": ()}


def test_a_fix_that_is_off_is_held_off_by_the_off_fix_it_was_drawn_over():
    entry = enhanced(fix("faces"), fix("eyes", "faces"), off=["eyes", "faces"])

    assert held(entry) == {"faces": (), "eyes": ("faces",)}
    assert can_be_switched(entry) == {"faces": True, "eyes": False}


def test_a_fix_that_redrew_nothing_can_be_neither_switched_nor_marked():
    entry = enhanced(fix("teeth", box=None))
    (switch,) = switches_of(entry)

    assert (switch.redrew_something, switch.can_be_switched) == (False, False)
    assert marked(entry, "teeth", True) is None


def test_taking_a_fix_off_writes_it_down_and_putting_it_on_takes_that_back():
    entry = enhanced(fix("faces"), fix("hands"))

    off = switched(entry, "hands", False)

    assert off[OFF_KEY] == ["hands"]
    assert switched(off, "hands", True) == entry


def test_a_fix_marked_bad_is_written_down_and_still_shows_on_the_image():
    entry = enhanced(fix("faces"), fix("hands"))

    bad = marked(entry, "hands", True)

    assert (bad[LEFT_OUT_KEY], OFF_KEY in bad) == (["hands"], False)
    assert [(s.part, s.on, s.bad) for s in switches_of(bad)] == [
        ("faces", True, False), ("hands", True, True)]
    assert marked(bad, "hands", False) == entry


def test_a_fix_held_on_can_still_be_marked_bad():
    entry = enhanced(fix("faces"), fix("eyes", "faces"))

    assert marked(entry, "faces", True)[LEFT_OUT_KEY] == ["faces"]


def test_a_fix_keeps_its_bad_mark_while_it_is_switched_off_and_on():
    bad = enhanced(fix("faces"), bad=["faces"])

    off = switched(bad, "faces", False)

    assert (off[OFF_KEY], off[LEFT_OUT_KEY]) == (["faces"], ["faces"])
    assert switched(off, "faces", True) == bad


def test_a_re_enhance_leaves_out_every_fix_that_is_off_or_marked_bad():
    entry = enhanced(fix("faces"), fix("hands"), fix("eyes"), off=["eyes"], bad=["faces"])

    assert left_out_of_a_re_enhance(entry) == ["faces", "eyes"]
    assert left_out_of_a_re_enhance(enhanced(fix("faces"))) == []


def test_a_held_fix_is_not_taken_off():
    entry = enhanced(fix("faces"), fix("eyes", "faces"))

    assert switched(entry, "faces", False) is None


def test_switching_or_marking_a_fix_to_what_it_already_is_changes_nothing():
    entry = enhanced(fix("faces"))

    assert (switched(entry, "faces", True), marked(entry, "faces", False)) == (None, None)


def test_a_fix_is_found_by_the_order_it_was_drawn_in_and_where_it_drew():
    entry = enhanced(fix("faces"), fix("hands", box=[1, 2, 3, 4]))

    assert drawn_as(entry, "hands") == (1, [1, 2, 3, 4])
