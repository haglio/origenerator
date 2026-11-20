from __future__ import annotations

from origenerator.row_readings import RowReadings


def _counted(asked):
    return lambda row: asked.append(row["prompt_id"]) or row["prompt_id"].upper()


def test_a_row_read_before_is_not_worked_out_again():
    asked, row = [], {"prompt_id": "pic-1"}
    before = RowReadings()
    before.of("name", _counted(asked))(row)

    read = RowReadings(before).of("name", _counted(asked))

    assert read(row) == "PIC-1"
    assert asked == ["pic-1"]


def test_a_reading_one_look_at_the_library_never_asked_for_is_kept_for_the_next():
    asked, row = [], {"prompt_id": "pic-1"}
    first = RowReadings()
    first.of("name", _counted(asked))(row)

    RowReadings(RowReadings(first)).of("name", _counted(asked))(row)

    assert asked == ["pic-1"]


def test_an_equal_row_that_is_another_row_is_worked_out_again():
    asked = []
    before = RowReadings()
    before.of("name", _counted(asked))({"prompt_id": "pic-1"})

    RowReadings(before).of("name", _counted(asked))({"prompt_id": "pic-1"})

    assert asked == ["pic-1", "pic-1"]


def test_a_reading_that_depends_on_something_else_is_worked_out_again_when_that_changes():
    asked, row = [], {"prompt_id": "pic-1"}
    before = RowReadings()
    before.of("name", _counted(asked), depends_on={"frames": 1})(row)

    RowReadings(before).of("name", _counted(asked), depends_on={"frames": 1})(row)

    assert asked == ["pic-1", "pic-1"]


def _looked_up(asked):
    return lambda row, index: asked.append(row["prompt_id"]) or index.get(row["frame"])


def _read_against(before_index, after_index, row):
    asked = []
    before = RowReadings()
    before.looking_up("source", _looked_up(asked), before_index)(row)
    found = RowReadings(before).looking_up("source", _looked_up(asked), after_index)(row)
    return found, asked


def test_a_reading_that_looks_up_an_index_is_kept_while_what_it_looked_up_is_unchanged():
    found, asked = _read_against({"a.png": "img-1"}, {"a.png": "img-1", "b.png": "img-2"},
                                 {"prompt_id": "vid-1", "frame": "a.png"})

    assert (found, asked) == ("img-1", ["vid-1"]), (
        "an image landing adds its frames to the index, and only the rows that look one of "
        "them up read differently")


def test_a_reading_is_worked_out_again_when_an_entry_it_looked_up_changed():
    found, asked = _read_against({"a.png": "img-1"}, {"a.png": "img-9"},
                                 {"prompt_id": "vid-1", "frame": "a.png"})

    assert (found, asked) == ("img-9", ["vid-1", "vid-1"])


def test_a_reading_is_worked_out_again_when_an_entry_it_found_missing_arrived():
    found, asked = _read_against({}, {"b.png": "img-2"}, {"prompt_id": "vid-1", "frame": "b.png"})

    assert (found, asked) == ("img-2", ["vid-1", "vid-1"])


def test_a_reading_that_asked_whether_the_index_is_empty_is_worked_out_again_when_that_changed():
    asked, row = [], {"prompt_id": "vid-1"}

    def empty_or_not(row, index):
        asked.append(row["prompt_id"])
        return bool(index)
    before = RowReadings()
    before.looking_up("any", empty_or_not, {})(row)

    assert RowReadings(before).looking_up("any", empty_or_not, {"a.png": 1})(row) is True
    assert asked == ["vid-1", "vid-1"]
