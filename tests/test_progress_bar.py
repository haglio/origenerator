from __future__ import annotations

import pytest
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from shared_ui.colors import BG_PRIMARY, BLUE, BLUE_LIGHT

from origenerator.gui import progress_bar
from origenerator.gui.progress_bar import ProgressBar
from origenerator.gui.stylesheet import build_stylesheet


@pytest.fixture
def bar(qtbot):
    b = ProgressBar()
    qtbot.addWidget(b)
    b.resize(220, 22)
    return b


@pytest.fixture
def styled_bar(qtbot):
    host = QWidget()
    host.setStyleSheet(build_stylesheet())
    layout = QVBoxLayout(host)
    b = ProgressBar()
    b.setFixedHeight(22)
    layout.addWidget(b)
    qtbot.addWidget(host)
    host.resize(240, 60)
    with qtbot.waitExposed(host):
        host.show()
    return b


def test_a_caption_reads_on_the_bar_rather_than_beside_it(bar):
    bar.show_progress("50% · 1:30 elapsed · ~6:02 left", (10, 20))
    assert bar.isTextVisible()
    assert bar.caption() == "50% · 1:30 elapsed · ~6:02 left"


def test_the_fill_measures_the_steps_it_was_given(bar):
    bar.show_progress("50%", (10, 20))
    assert (bar.value(), bar.maximum()) == (10, 20)


def test_no_step_counts_leaves_it_sweeping_rather_than_stuck_at_zero(bar):
    bar.show_progress("", None)
    assert bar.maximum() == 0

    bar.show_progress("", (0, 0))
    assert bar.maximum() == 0


def test_the_caption_still_shows_on_a_bar_with_nothing_to_count(bar):
    bar.show_progress("Waiting on 2 jobs from another app", None)
    assert bar.text()


def test_a_caption_too_long_for_the_bar_scrolls_past_instead_of_being_cut(qtbot):
    narrow = ProgressBar()
    qtbot.addWidget(narrow)
    narrow.resize(40, 22)
    narrow.show_progress("First pass · 100% · 12:30 elapsed · ~16:02 left", (10, 20))

    assert narrow.scrolling()
    assert narrow.text() == narrow.caption()
    assert "…" not in narrow.text()


def test_a_caption_that_fits_does_not_move(qtbot):
    wide = ProgressBar()
    qtbot.addWidget(wide)
    wide.resize(400, 22)
    wide.show_progress("50%", (10, 20))

    assert not wide.scrolling()
    assert wide.scrolled() == 0


def test_the_scroll_holds_at_the_top_of_a_lap_then_sets_off(qtbot):
    narrow = ProgressBar()
    qtbot.addWidget(narrow)
    narrow.resize(40, 22)
    narrow.show()
    narrow.show_progress("First pass · 100% · 12:30 elapsed · ~16:02 left", (10, 20))

    for _ in range(progress_bar._HOLD_TICKS):
        narrow._advance()
    assert narrow.scrolled() == 0

    narrow._advance()
    assert narrow.scrolled() > 0


def test_the_scroll_carries_on_when_only_the_clock_in_it_changed(qtbot):
    narrow = ProgressBar()
    qtbot.addWidget(narrow)
    narrow.resize(40, 22)
    narrow.show()
    narrow.show_progress("First pass · 40% · 12:30 elapsed · ~16:02 left", (10, 20))
    for _ in range(progress_bar._HOLD_TICKS + 5):
        narrow._advance()
    travelled = narrow.scrolled()

    narrow.show_progress("First pass · 40% · 12:31 elapsed · ~16:01 left", (10, 20))

    assert narrow.scrolled() == travelled


def test_a_bar_nobody_can_see_stops_scrolling(qtbot):
    narrow = ProgressBar()
    qtbot.addWidget(narrow)
    narrow.resize(40, 22)
    narrow.show()
    narrow.show_progress("First pass · 100% · 12:30 elapsed · ~16:02 left", (10, 20))
    assert narrow._scroll.isActive()

    narrow.hide()

    assert not narrow._scroll.isActive()


def test_the_fill_is_the_flat_blue_behind_the_writing(styled_bar):
    styled_bar.show_progress("50%", (1, 1))
    image = styled_bar.grab().toImage()

    assert image.pixelColor(4, styled_bar.height() // 2) == BLUE


def _foot(bar) -> int:
    return bar.height() - 4


def test_the_pass_being_taken_reads_as_a_band_along_the_foot(styled_bar):
    styled_bar.show_progress("83%", (50, 60), (1, 20))
    image = styled_bar.grab().toImage()
    middle = styled_bar.width() // 2

    assert image.pixelColor(middle, styled_bar.height() // 2) == BLUE
    assert image.pixelColor(middle, _foot(styled_bar)) == BG_PRIMARY


def test_the_band_fills_with_the_pass_it_measures(styled_bar):
    styled_bar.show_progress("83%", (50, 60), (18, 20))
    image = styled_bar.grab().toImage()
    foot = _foot(styled_bar)

    assert image.pixelColor(8, foot) == BLUE_LIGHT
    assert image.pixelColor(styled_bar.width() - 9, foot) == BG_PRIMARY


def test_a_single_pass_run_keeps_the_whole_bar(styled_bar):
    styled_bar.show_progress("50%", (1, 1))
    image = styled_bar.grab().toImage()

    assert styled_bar.pass_progress() is None
    assert image.pixelColor(8, _foot(styled_bar)) == BLUE


def test_the_caption_is_written_over_the_band_not_under_it(styled_bar):
    # Qt offscreen has no real fonts, so glyphs are squares; the size is raised until one reaches the band.
    font = QFont(styled_bar.font())
    font.setPointSize(16)
    styled_bar.setFont(font)
    styled_bar.setFixedHeight(26)
    styled_bar.parent().layout().activate()
    styled_bar.show_progress("50%", (30, 60), (20, 20))
    image = styled_bar.grab().toImage()

    substep = range(styled_bar.height() - 7, styled_bar.height() - 1)
    middle = range(styled_bar.width() // 3, styled_bar.width() * 2 // 3)
    written = [(x, y) for y in substep for x in middle
               if image.pixelColor(x, y) not in (BLUE_LIGHT, BG_PRIMARY)]
    assert written


def test_a_sweeping_bar_grows_no_band(styled_bar):
    styled_bar.show_progress("Waiting on 2 jobs from another app", None, (3, 20))
    image = styled_bar.grab().toImage()

    assert image.pixelColor(8, _foot(styled_bar)) != BLUE_LIGHT
