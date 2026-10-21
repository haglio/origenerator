"""Every drag the app starts reaches every place a drop can land, start and end."""
from __future__ import annotations

import pytest

from origenerator.gui.drags import carry
from origenerator.gui.generation_drag import generation_mime
from tests.heard_drags import HeardDrags


class _Drag:
    def __init__(self, fails=False):
        self.fails = fails
        self.ran = None

    def exec(self, action):
        self.ran = action
        if self.fails:
            raise RuntimeError("the drag loop failed")


def test_a_carried_drag_is_announced_with_its_payload_and_source_then_its_end(qtbot):
    heard = HeardDrags()
    mime, source, drag = generation_mime("p1"), object(), _Drag()

    carry(drag, mime, source, "copy")

    assert heard.started == [(mime, source)]
    assert heard.ended == 1
    assert drag.ran == "copy"


def test_a_drag_whose_loop_fails_still_announces_its_end(qtbot):
    heard = HeardDrags()

    with pytest.raises(RuntimeError):
        carry(_Drag(fails=True), generation_mime("p1"), None, "copy")

    assert heard.ended == 1
