from __future__ import annotations

from shared_ui.colors import BORDER_PANEL

from origenerator.gui.dashed_edge import dashed_pen


def test_a_dashed_edge_alternates_ten_pixels_drawn_and_ten_left_at_any_width():
    assert [[step * width for step in dashed_pen(BORDER_PANEL, width).dashPattern()]
            for width in (1, 2)] == [[10, 10], [10, 10]]
