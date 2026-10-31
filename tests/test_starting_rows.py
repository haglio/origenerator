"""The Job Queue's rows for work asked for that is not a job yet.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

from origenerator.gui.generation_job import JobState
from origenerator.gui.inflight import InFlightItem, RunReading
from origenerator.gui.starting_rows import StartingRows
from origenerator.media import MediaType


class FakeLine:
    """The Job Queue reduced to where it would put a job of each kind."""

    def __init__(self, **before):
        self._before = before

    def joins_before(self, media_type):
        return self._before.get(media_type)


def _job(key):
    return InFlightItem(key=key, caption="", reading=RunReading(status=JobState.QUEUED),
                        reveal=lambda: None)


def test_a_row_shown_stands_in_the_line_until_it_is_dropped(qtbot):
    rows = StartingRows()
    redraws = []
    rows.changed.connect(lambda: redraws.append(True))

    key = rows.show(caption="A video from Combine, still being started",
                    media_type=MediaType.VIDEO)

    (row,) = rows.rows()
    assert row.key == key
    assert row.starting is True
    assert row.reading.status == JobState.QUEUED
    assert row.cancel is None
    rows.drop(key)
    rows.drop(key)  # twice costs nothing
    assert rows.rows() == []
    assert len(redraws) == 2


def test_a_row_stands_where_the_line_would_take_its_job(qtbot):
    rows = StartingRows()
    image = rows.show(caption="An image from a Request, still being started",
                      media_type=MediaType.IMAGE)
    video = rows.show(caption="A video from Combine, still being started",
                      media_type=MediaType.VIDEO)

    line = rows.placed_among([_job("making"), _job("waiting")], FakeLine(image="waiting"))

    assert [item.key for item in line] == ["making", image, "waiting", video]
