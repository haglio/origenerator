from __future__ import annotations

import json
from pathlib import Path

from origenerator.genau_flicks import (
    AS_GENAU_STARTS,
    NO_FILTER,
    Flick,
    GenauFilters,
    GenauLeft,
    flicks_of,
    restored,
    saved,
)
from tests.genau_support import FlicksLibrary as _Library
from tests.genau_support import looping_row as _row


def _ids(flicks: list[Flick]) -> list[str]:
    return [flick.prompt_id for flick in flicks]


def test_genau_lists_every_looping_video_made_here_newest_first_and_nothing_else():
    library = _Library([_row("new"), _row("a still", workflow="sdxl_t2i"),
                        _row("made elsewhere", source="outside"), _row("old")])

    assert _ids(flicks_of(library, NO_FILTER)) == ["new", "old"]


def test_each_flick_is_the_file_its_item_plays():
    (flick,) = flicks_of(_Library([_row("one")]), NO_FILTER)

    assert flick.path == Path("C:/made/up/one.mp4")


def test_favorites_keeps_the_favorites_alone():
    library = _Library([_row("liked", favorite=True), _row("plain")])

    assert _ids(flicks_of(library, GenauFilters(favorites=True))) == ["liked"]


def test_enhanced_keeps_the_enhanced_alone():
    library = _Library([_row("better"), _row("plain")], enhanced=frozenset({"better"}))

    assert _ids(flicks_of(library, GenauFilters(enhanced=True))) == ["better"]


def test_each_shape_left_out_takes_its_flicks_with_it():
    library = _Library([_row("tall"), _row("wide", shape="landscape")])

    assert (_ids(flicks_of(library, GenauFilters(shapes=(True, False)))),
            _ids(flicks_of(library, GenauFilters(shapes=(False, True))))) == (
        ["tall"], ["wide"])


def test_a_flick_flipped_on_its_item_says_so():
    library = _Library([_row("turned", flipped=True), _row("plain")])

    assert [flick.flipped for flick in flicks_of(library, NO_FILTER)] == [True, False]


def test_the_files_of_every_flick_are_asked_for_in_one_go():
    library = _Library([_row(f"g{n}") for n in range(5)])

    flicks_of(library, NO_FILTER)

    assert library.slides_asked == 1


def test_where_genau_was_left_comes_back_as_it_was_saved():
    left = GenauLeft(filters=GenauFilters(favorites=True, enhanced=True, shapes=(False, True)),
                     showing=True, latest=True, locked=False, seconds=9, flick="v7")

    assert restored(json.loads(json.dumps(saved(left)))) == left


def test_nothing_saved_comes_back_as_genau_starts():
    assert restored(None) == AS_GENAU_STARTS == GenauLeft()


def test_each_thing_saved_wrong_comes_back_as_genau_starts_it():
    wrong = {"favorites": "yes", "enhanced": 1, "shapes": [1, 2, 3], "showing": "no",
             "latest": None, "locked": "locked", "seconds": "nine", "flick": 7}

    assert restored(wrong) == AS_GENAU_STARTS
