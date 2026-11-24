from __future__ import annotations

from origenerator.fix_switches import (
    FIXES_KEY,
    KEPT_KEY,
    LEFT_OUT,
    LEFT_OUT_KEY,
    OFF,
    OFF_KEY,
    ON,
    chosen,
    drawn_as,
    left_out_of_a_re_enhance,
    switches_of,
)

BOX = [100, 100, 300, 300]


def fix(part: str, *over: str, box=BOX) -> dict:
    return {"part": part, "box": box, "over": list(over)}


def enhanced(*fixes, off=(), left_out=()) -> dict:
    entry = {"filename": "enhanced.png", KEPT_KEY: "run-1", FIXES_KEY: list(fixes)}
    if off:
        entry[OFF_KEY] = list(off)
    if left_out:
        entry[LEFT_OUT_KEY] = list(left_out)
    return entry


def held(entry: dict) -> dict:
    return {switch.part: switch.held_by for switch in switches_of(entry)}


def offered(entry: dict) -> dict:
    return {switch.part: [choice for choice in (ON, OFF, LEFT_OUT) if switch.can_be(choice)]
            for switch in switches_of(entry)}


def test_an_enhancement_made_before_fixes_were_kept_has_no_switches():
    assert switches_of({"filename": "enhanced.png"}) == []


def test_every_fix_starts_on_and_free_where_none_was_drawn_over_another():
    entry = enhanced(fix("faces"), fix("hands"))

    assert [(s.part, s.choice) for s in switches_of(entry)] == [("faces", ON), ("hands", ON)]
    assert offered(entry) == {"faces": [ON, OFF, LEFT_OUT], "hands": [ON, OFF, LEFT_OUT]}


def test_a_fix_is_held_on_by_a_fix_drawn_over_part_of_it():
    entry = enhanced(fix("faces"), fix("hands"), fix("eyes", "faces"))

    assert held(entry) == {"faces": ("eyes",), "hands": (), "eyes": ()}


def test_a_fix_held_on_can_still_be_left_out_of_a_re_enhance_but_not_taken_off_the_image():
    entry = enhanced(fix("faces"), fix("eyes", "faces"))

    assert offered(entry)["faces"] == [ON, LEFT_OUT]


def test_a_fix_is_free_once_the_fix_drawn_over_it_is_off():
    entry = enhanced(fix("faces"), fix("eyes", "faces"), off=["eyes"])

    assert held(entry) == {"faces": (), "eyes": ()}


def test_a_fix_that_is_off_is_held_off_by_the_off_fix_it_was_drawn_over():
    entry = enhanced(fix("faces"), fix("eyes", "faces"), off=["eyes", "faces"])

    assert held(entry) == {"faces": (), "eyes": ("faces",)}
    assert offered(entry)["eyes"] == [OFF]


def test_a_fix_that_redrew_nothing_offers_no_choice():
    (switch,) = switches_of(enhanced(fix("teeth", box=None)))

    assert (switch.redrew_something, offered(enhanced(fix("teeth", box=None)))) == (
        False, {"teeth": []})


def test_taking_a_fix_off_writes_it_down_and_putting_it_on_takes_that_back():
    entry = enhanced(fix("faces"), fix("hands"))

    off = chosen(entry, "hands", OFF)

    assert off[OFF_KEY] == ["hands"]
    assert chosen(off, "hands", ON) == entry


def test_a_fix_left_out_of_a_re_enhance_is_written_down_and_still_shows_on_the_image():
    entry = enhanced(fix("faces"), fix("hands"))

    marked = chosen(entry, "hands", LEFT_OUT)

    assert (marked[LEFT_OUT_KEY], OFF_KEY in marked) == (["hands"], False)
    assert [(s.part, s.on, s.choice) for s in switches_of(marked)] == [
        ("faces", True, ON), ("hands", True, LEFT_OUT)]
    assert chosen(marked, "hands", ON) == entry


def test_a_fix_taken_off_is_no_longer_marked_as_left_out():
    marked = enhanced(fix("faces"), left_out=["faces"])

    off = chosen(marked, "faces", OFF)

    assert (off[OFF_KEY], LEFT_OUT_KEY in off) == (["faces"], False)


def test_a_re_enhance_leaves_out_every_fix_that_is_off_or_marked():
    entry = enhanced(fix("faces"), fix("hands"), fix("eyes"), off=["eyes"], left_out=["faces"])

    assert left_out_of_a_re_enhance(entry) == ["faces", "eyes"]
    assert left_out_of_a_re_enhance(enhanced(fix("faces"))) == []


def test_a_held_fix_is_not_taken_off():
    entry = enhanced(fix("faces"), fix("eyes", "faces"))

    assert chosen(entry, "faces", OFF) is None


def test_choosing_what_a_fix_already_is_changes_nothing():
    assert chosen(enhanced(fix("faces")), "faces", ON) is None


def test_a_fix_is_found_by_the_order_it_was_drawn_in_and_where_it_drew():
    entry = enhanced(fix("faces"), fix("hands", box=[1, 2, 3, 4]))

    assert drawn_as(entry, "hands") == (1, [1, 2, 3, 4])
