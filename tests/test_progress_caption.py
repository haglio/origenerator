import pytest

from PyQt6.QtWidgets import QVBoxLayout, QWidget

from origenerator.gui.progress_caption import ProgressCaption
from origenerator.gui.stylesheet import build_stylesheet
from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()

from shared_ui.colors import BLUE


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


def test_a_caption_too_long_for_the_bar_elides_at_its_tail(qtbot):
    # Centered text in a narrow bar is otherwise clipped mid-letter at BOTH ends,
    # which loses the percentage as readily as the countdown.
    narrow = ProgressCaption()
    qtbot.addWidget(narrow)
    narrow.resize(40, 22)
    narrow.show_progress("100% · 12:30 elapsed · ~16:02 left", (10, 20))

    assert narrow.text() != narrow.caption()
    assert narrow.text().endswith("…")
    assert narrow.caption() == "100% · 12:30 elapsed · ~16:02 left"  # the whole line is kept


def test_the_fill_is_the_flat_blue_behind_the_writing(styled_bar):
    # Not a translucent wash over the caption: a fill that passes under the
    # letters tints them, and legibility is the one thing this bar owes.
    styled_bar.show_progress("50%", (1, 1))  # filled end to end
    image = styled_bar.grab().toImage()

    assert image.pixelColor(4, styled_bar.height() // 2) == BLUE
