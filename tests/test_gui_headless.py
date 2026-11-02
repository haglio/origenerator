from __future__ import annotations


def test_gui_suite_renders_offscreen(qapp):
    assert qapp.platformName() == "offscreen"
