"""The generation queue as a block of the one panel a show wears."""
from __future__ import annotations

import numpy as np
from PIL import Image
from shared_ui.palette import RED

from origenerator.gui.hud_queue import queue_section
from origenerator.gui.inflight import InFlightItem, RunReading


def _item(key="j1", caption="Alpha Workflow › a paper kite", status="queued", **kw):
    reading = {name: kw.pop(name) for name in list(kw)
               if name in ("frame", "progress", "pass_progress", "stage",
                           "started_at", "typical_seconds")}
    return InFlightItem(key=key, caption=caption,
                        reading=RunReading(status=status, **reading),
                        reveal=kw.pop("reveal", lambda: None), **kw)


def test_nothing_in_flight_is_no_block_at_all():
    """A show with an idle queue wears the panel it always wore."""
    assert queue_section([], 0) is None


def test_every_job_in_flight_is_a_row_of_its_own():
    section = queue_section([_item("running-one", status="running", job_kind="Image",
                                   typical_seconds=30),
                             _item("waiting-one", job_kind="Video", typical_seconds=600)], 0)

    assert [line.key for line in section.lines] == ["running-one", "waiting-one"]
    assert section.lines[1].lead == "~10 min · Video"


def test_the_job_being_made_leads_the_block_with_its_frame_and_its_clock():
    """The live half of the lower strip, on the panel: what is being made, and
    how far along it is."""
    section = queue_section([_item("running-one", status="running", frame=b"jpeg",
                                   started_at=0.0, typical_seconds=30,
                                   progress=(5, 20))], 0)

    assert section.leader.key == "running-one"
    assert section.leader.frame == b"jpeg"
    assert section.leader.progress == (5, 20)
    assert "%" in section.leader.caption


def test_a_line_whose_head_is_held_has_no_job_being_made():
    """A video the queue is holding for the show is not on the GPU, so the head
    of the block says what the hold is instead of drawing an empty bar."""
    section = queue_section([_item("held-one", held=True, job_kind="Video")], 0)

    assert section.leader is None
    assert section.idle_note == "1 video held until the slideshow closes"


def _painted(section, width=400):
    """The block on a panel-sized canvas, with what it drew there."""
    image = Image.new("RGBA", (width + 20, section.size()[1] + 20), (0, 0, 0, 0))
    return image, section.paint(image, 10, 10, width, None)


def _posted(targets) -> list[str]:
    return [button.command for _rect, button in targets]


def test_a_row_carries_the_button_that_throws_its_job_away():
    section = queue_section([_item("j1", cancel=lambda: None),
                             _item("j2", cancel=lambda: None, auto_generating=True)], 0)

    _image, targets = _painted(section)

    assert "queue_cancel|j1" in _posted(targets)
    assert [button.glyph for _rect, button in targets
            if button.command == "queue_cancel|j2"] == ["Next seed"]


def test_a_row_is_a_way_into_the_folder_its_job_will_land_in():
    section = queue_section([_item("j1")], 0)

    _image, targets = _painted(section)

    assert "queue_open|j1" in _posted(targets)


def _reds(image) -> int:
    """How many pixels of the block are within a hair of the panel's red."""
    pixels = np.asarray(image).reshape(-1, 4).astype(int)
    near = np.all(np.abs(pixels[:, :3] - np.array(RED[:3])) < 24, axis=1)
    return int(np.count_nonzero(near & (pixels[:, 3] > 0)))


def test_the_word_that_throws_a_job_away_is_drawn_in_the_panel_own_ink():
    """The strip under the window draws Cancel in the panel's ordinary gray,
    and the panel's own copy of that queue reads the same: red here is the
    color the players keep for a live recording."""
    section = queue_section([_item("j1", cancel=lambda: None)], 0)

    image, _targets = _painted(section)

    assert _reds(image) == 0
