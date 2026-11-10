from __future__ import annotations


def test_gui_suite_renders_offscreen(qapp):
    assert qapp.platformName() == "offscreen", (
        "agents run this suite on every commit, so it must draw offscreen and flash no Qt "
        "window onto the screen; this guards the platform setting against being removed or set "
        "too late, after the QApplication is made")
