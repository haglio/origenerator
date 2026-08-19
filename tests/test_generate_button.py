import pytest

from PyQt6.QtWidgets import QVBoxLayout, QWidget

from origenerator.gui.generate_button import GenerateButton
from origenerator.gui.stylesheet import build_stylesheet
from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()

from shared_ui.colors import BLUE


@pytest.fixture
def button(qtbot):
    b = GenerateButton()
    qtbot.addWidget(b)
    return b


@pytest.fixture
def styled_button(qtbot):
    """A button wearing the app's stylesheet, for the looks the sheet decides.
    Styled through a parent, as the running app does — a self-styled widget
    measures and paints slightly differently."""
    host = QWidget()
    host.setStyleSheet(build_stylesheet())
    layout = QVBoxLayout(host)
    b = GenerateButton()
    layout.addWidget(b)
    qtbot.addWidget(host)
    host.resize(320, 60)
    host.show()
    qtbot.waitExposed(host)
    yield b  # yield, so the host stays referenced: collected, it takes the button


def _face(button):
    """The button's colour well right of any fill — its resting face."""
    image = button.grab().toImage()
    return image.pixelColor(button.width() - 4, button.height() // 2)


def test_idle_reads_generate_with_no_fill(button):
    assert button.text() == "Generate"
    assert button._fraction is None


def test_start_enters_progress_mode(button):
    button.start()
    assert button._fraction == 0.0


def test_a_run_in_flight_leaves_the_button_pressable(button):
    # ComfyUI takes a queue now, so a second press while one run is in flight is
    # a second job asked for, not a relaunch over the first — and the face keeps
    # saying so rather than greying out under a "Generating…" label.
    button.start()
    assert button.isEnabled()
    assert button.text() == "Generate"


def test_progress_mode_drops_the_primary_blue_so_the_fill_can_read(styled_button):
    # Reported: a blue progress edge crawling across a button that was already
    # fully blue. The fill is a translucent blue wash, so the face under it steps
    # back to neutral for the run — it can't grey out via :disabled any more, since
    # the button stays pressable to queue another.
    assert _face(styled_button) == BLUE          # idle: the primary blue

    styled_button.start()

    running = _face(styled_button)
    assert running != BLUE                       # a face the wash can be seen on
    styled_button.set_progress(1, 1)
    assert _face(styled_button) != running       # and it is: the fill shows there


def test_progress_mode_gives_the_primary_blue_back_when_the_run_ends(styled_button):
    styled_button.start()
    styled_button.finish(enabled=True)
    assert _face(styled_button) == BLUE


def test_set_progress_sets_the_fill_fraction(button):
    button.start()
    button.set_progress(3, 12)
    assert button._fraction == 0.25


def test_set_progress_survives_a_zero_maximum(button):
    button.start()
    button.set_progress(0, 0)       # ComfyUI can send max=0 before steps start
    assert button._fraction == 0.0


def test_finish_returns_to_the_idle_button(button):
    button.start()
    button.finish(enabled=True)
    assert button.text() == "Generate"
    assert button._fraction is None
    assert button.isEnabled()


def test_finish_can_leave_it_disabled(button):
    button.start()
    button.finish(enabled=False)    # a read-only gallery with no client
    assert not button.isEnabled()


def test_flash_guard_shows_the_message_on_the_button(button):
    button.flash_guard("Select an input image")
    assert button.text() == "Select an input image"


def test_the_caption_is_what_a_finished_run_comes_back_to(button):
    # The resting caption says what a press will do — "Generate with Random seed"
    # where the settings would otherwise re-create a past generation — so the run
    # that fills the button hands that caption back when it ends, not "Generate".
    button.set_caption("Generate with Random seed")
    assert button.text() == "Generate with Random seed"

    button.start()
    button.finish(enabled=True)

    assert button.text() == "Generate with Random seed"


def test_a_new_caption_waits_for_the_guard_message_to_clear(button):
    # The caption is recomputed on every form edit, which is exactly what the user
    # is doing while a guard says what the form still needs — so a caption arriving
    # mid-guard waits its turn rather than wiping the message being read.
    button.flash_guard("Select an input image")

    button.set_caption("Generate with Random seed")

    assert button.text() == "Select an input image"
    button._clear_guard()
    assert button.text() == "Generate with Random seed"
