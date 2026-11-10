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
