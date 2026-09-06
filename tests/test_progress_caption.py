import pytest
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from origenerator.gui import progress_caption
from origenerator.gui.progress_caption import ProgressCaption
from origenerator.gui.stylesheet import build_stylesheet
from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()

from shared_ui.colors import BG_PRIMARY, BLUE, BLUE_LIGHT


@pytest.fixture
def bar(qtbot):
    b = ProgressCaption()
    qtbot.addWidget(b)
    b.resize(220, 22)
    return b


@pytest.fixture
def styled_bar(qtbot):
    """A bar wearing the app's stylesheet, for the looks the sheet decides.
    Styled through a parent, as the running app does."""
    host = QWidget()
    host.setStyleSheet(build_stylesheet())
    layout = QVBoxLayout(host)
    b = ProgressCaption()
    b.setFixedHeight(22)
    layout.addWidget(b)
    qtbot.addWidget(host)
    host.resize(240, 60)
    host.show()
    qtbot.waitExposed(host)
    yield b  # yield, so the host stays referenced: collected, it takes the bar


def test_a_caption_reads_on_the_bar_rather_than_beside_it(bar):
    bar.show_progress("50% · 1:30 elapsed · ~6:02 left", (10, 20))
    assert bar.isTextVisible()
    assert bar.caption() == "50% · 1:30 elapsed · ~6:02 left"


def test_the_fill_measures_the_steps_it_was_given(bar):
    bar.show_progress("50%", (10, 20))
    assert (bar.value(), bar.maximum()) == (10, 20)


def test_no_step_counts_leaves_it_sweeping_rather_than_stuck_at_zero(bar):
    # A job ComfyUI hasn't started, or one before its first step: a determinate
    # bar parked at 0% says "started and going nowhere", which is the opposite of
    # what is happening.
    bar.show_progress("", None)
    assert bar.maximum() == 0

    bar.show_progress("", (0, 0))  # a tracked job with nothing measured yet
    assert bar.maximum() == 0


def test_the_caption_still_shows_on_a_bar_with_nothing_to_count(bar):
    # Qt's own text() goes empty on an indeterminate bar, which would drop the
    # caption exactly when it is the only thing the surface has to say.
    bar.show_progress("Waiting behind 2 jobs from another app", None)
    assert bar.text()


def test_a_caption_too_long_for_the_bar_scrolls_past_instead_of_being_cut(qtbot):
    # It used to elide, which on these lines means losing whichever readings the
    # bar has no room for — the stage on a wide bar, the countdown on a tile.
    # Slid past, all of it is read in turn.
    narrow = ProgressCaption()
    qtbot.addWidget(narrow)
    narrow.resize(40, 22)
    narrow.show_progress("High noise · 100% · 12:30 elapsed · ~16:02 left", (10, 20))

    assert narrow.scrolling()
    assert narrow.text() == narrow.caption()          # nothing is cut off it
    assert "…" not in narrow.text()


def test_a_caption_that_fits_does_not_move(qtbot):
    # A line crawling across a bar it already fits in reads as a fault.
    wide = ProgressCaption()
    qtbot.addWidget(wide)
    wide.resize(400, 22)
    wide.show_progress("50%", (10, 20))

    assert not wide.scrolling()
    assert wide.scrolled() == 0


def test_the_scroll_holds_at_the_top_of_a_lap_then_sets_off(qtbot):
    # The line leads with the stage the run is at, so a scroll that swept
    # straight past would show that word only in motion.
    narrow = ProgressCaption()
    qtbot.addWidget(narrow)
    narrow.resize(40, 22)
    narrow.show()
    narrow.show_progress("High noise · 100% · 12:30 elapsed · ~16:02 left", (10, 20))

    for _ in range(progress_caption._HOLD_TICKS):
        narrow._advance()
    assert narrow.scrolled() == 0        # still held at the start of the line

    narrow._advance()
    assert narrow.scrolled() > 0         # and away


def test_the_scroll_carries_on_when_only_the_clock_in_it_changed(qtbot):
    # The elapsed count ticks every second, so a scroll that started over on
    # every caption would never leave the first few words.
    narrow = ProgressCaption()
    qtbot.addWidget(narrow)
    narrow.resize(40, 22)
    narrow.show()
    narrow.show_progress("High noise · 40% · 12:30 elapsed · ~16:02 left", (10, 20))
    for _ in range(progress_caption._HOLD_TICKS + 5):
        narrow._advance()
    travelled = narrow.scrolled()

    narrow.show_progress("High noise · 40% · 12:31 elapsed · ~16:01 left", (10, 20))

    assert narrow.scrolled() == travelled


def test_a_bar_nobody_can_see_stops_scrolling(qtbot):
    # One of these per queue row, per shelf card and per tile: a repaint every
    # tick for bars that are not on screen is a cost with nothing bought by it.
    narrow = ProgressCaption()
    qtbot.addWidget(narrow)
    narrow.resize(40, 22)
    narrow.show()
    narrow.show_progress("High noise · 100% · 12:30 elapsed · ~16:02 left", (10, 20))
    assert narrow._scroll.isActive()

    narrow.hide()

    assert not narrow._scroll.isActive()


def test_the_fill_is_the_flat_blue_behind_the_writing(styled_bar):
    # Not a translucent wash over the caption: a fill that passes under the
    # letters tints them, and legibility is the one thing this bar owes.
    styled_bar.show_progress("50%", (1, 1))  # filled end to end
    image = styled_bar.grab().toImage()

    assert image.pixelColor(4, styled_bar.height() // 2) == BLUE


def _foot(bar) -> int:
    """A row inside the band along the bar's foot, clear of the caption."""
    return bar.height() - 4


def test_the_pass_being_taken_reads_as_a_band_along_the_foot(styled_bar):
    # The whole point of the split: the run's own reading is nearly full while
    # the fix in hand has barely started, and one bar cannot say both.
    styled_bar.show_progress("83%", (50, 60), (1, 20))
    image = styled_bar.grab().toImage()
    middle = styled_bar.width() // 2

    assert image.pixelColor(middle, styled_bar.height() // 2) == BLUE  # the run, most of the way
    assert image.pixelColor(middle, _foot(styled_bar)) == BG_PRIMARY   # the fix, barely begun


def test_the_band_fills_with_the_pass_it_measures(styled_bar):
    styled_bar.show_progress("83%", (50, 60), (18, 20))
    image = styled_bar.grab().toImage()
    foot = _foot(styled_bar)

    assert image.pixelColor(8, foot) == BLUE_LIGHT
    # Its own count, not the bar's: nearly through this fix, and the far end of
    # the band is the little that is left of it.
    assert image.pixelColor(styled_bar.width() - 9, foot) == BG_PRIMARY


def test_a_single_pass_run_keeps_the_whole_bar(styled_bar):
    # Nothing to split: a band tracking the same steps as the fill above it
    # would spend a sixth of the bar's height saying it twice.
    styled_bar.show_progress("50%", (1, 1))
    image = styled_bar.grab().toImage()

    assert styled_bar.pass_progress() is None
    assert image.pixelColor(8, _foot(styled_bar)) == BLUE


def test_the_caption_is_written_over_the_band_not_under_it(styled_bar):
    # The band lies along the foot of the bar, which is where a line of text
    # keeps the bottom third of its letters. Painted last it strikes them out —
    # which is what it did, until the caption was moved to the top layer.
    #
    # Offscreen has no real fonts, so the glyphs come out as boxes; the point
    # size is raised until a box reaches into the band, which is what a
    # descender does at the app's own size on a real display. Only the middle of
    # the band is read: the rounded ends carry border pixels of their own, which
    # would answer "something other than the band is here" whatever happened to
    # the caption.
    font = QFont(styled_bar.font())
    font.setPointSize(16)
    styled_bar.setFont(font)
    styled_bar.setFixedHeight(26)  # the height every surface gives one of these
    styled_bar.parent().layout().activate()
    styled_bar.show_progress("50%", (30, 60), (20, 20))  # band filled end to end
    image = styled_bar.grab().toImage()

    band = range(styled_bar.height() - 7, styled_bar.height() - 1)
    middle = range(styled_bar.width() // 3, styled_bar.width() * 2 // 3)
    written = [(x, y) for y in band for x in middle
               if image.pixelColor(x, y) not in (BLUE_LIGHT, BG_PRIMARY)]
    assert written


def test_a_sweeping_bar_grows_no_band(styled_bar):
    # A job ComfyUI hasn't started has no run to measure, so there is nothing
    # for a band under it to be a part of.
    styled_bar.show_progress("Waiting behind 2 jobs from another app", None, (3, 20))
    image = styled_bar.grab().toImage()

    assert image.pixelColor(8, _foot(styled_bar)) != BLUE_LIGHT
