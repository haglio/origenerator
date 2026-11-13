from __future__ import annotations

import io

import pytest

from origenerator import crash_notes
from origenerator.gui.viewport import Viewport


@pytest.fixture
def crash_log(monkeypatch):
    log = io.StringIO()
    monkeypatch.setattr(crash_notes, "_crash_log", [log])
    return log


def test_a_note_says_nothing_before_the_crash_log_is_armed(monkeypatch):
    monkeypatch.setattr(crash_notes, "_crash_log", [])
    crash_notes.note("a viewer shows the video of item item-one")


def test_a_note_into_a_closed_crash_log_is_dropped(crash_log):
    crash_log.close()
    crash_notes.note("a viewer shows the video of item item-one")


def test_a_video_with_no_item_is_noted_as_one(qtbot, crash_log, tmp_path):
    viewer = Viewport()
    qtbot.addWidget(viewer)
    viewer.show_video(tmp_path / "video one.mp4")
    assert "a viewer shows a video that is no item" in crash_log.getvalue()
