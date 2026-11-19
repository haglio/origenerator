from __future__ import annotations

import pytest

from origenerator.numbers_given import NumbersGiven


def _read_the_lanes(read: list):
    def names_in_use():
        read.append(1)
        return ["alpha_t2i_00007_.png", "not numbered.png"]
    return names_in_use


def test_the_numbers_are_read_off_the_lanes_once_and_kept(tmp_path):
    read = []
    NumbersGiven(tmp_path / "numbers_given.json", _read_the_lanes(read))

    kept = NumbersGiven(tmp_path / "numbers_given.json", _read_the_lanes(read))

    assert (kept.highest("alpha_t2i"), len(read)) == (7, 1)


@pytest.mark.parametrize("held", ["not json at all", "[1, 2]"])
def test_a_record_that_cannot_be_read_is_made_again_from_the_lanes(tmp_path, held):
    (tmp_path / "numbers_given.json").write_text(held, encoding="utf-8")
    read = []

    kept = NumbersGiven(tmp_path / "numbers_given.json", _read_the_lanes(read))

    assert (kept.highest("alpha_t2i"), len(read)) == (7, 1)


def test_a_number_given_lower_than_the_highest_leaves_the_record_as_it_was(tmp_path):
    kept = NumbersGiven(tmp_path / "numbers_given.json", _read_the_lanes([]))

    kept.gave(["alpha_t2i_00003_.png"])

    assert NumbersGiven(tmp_path / "numbers_given.json", _read_the_lanes([])).highest("alpha_t2i") == 7
