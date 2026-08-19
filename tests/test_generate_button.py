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
    """The button's color well right of its edge — its resting face."""
    image = button.grab().toImage()
    return image.pixelColor(button.width() - 4, button.height() // 2)


def test_idle_reads_generate(button):
    assert button.text() == "Generate"


def test_a_run_in_flight_leaves_the_button_pressable(button):
    # ComfyUI takes a queue, so a second press while one run is in flight is a
    # second job asked for, not a relaunch over the first.
    assert button.isEnabled()
    assert button.text() == "Generate"


def test_the_button_keeps_the_primary_blue_with_a_run_in_flight(styled_button):
    # It used to step back to a neutral face and fill with the run's progress,
    # which put a third account of one run on screen beside the queue's and the
    # in-flight card's. Submitting is all it does now, so it never changes face.
    assert _face(styled_button) == BLUE


def test_the_button_tracks_no_run(button):
    # Nothing here to feed a run's progress into: the strip's queue and the
    # browser pane's card are the two places a run in flight is watched.
    assert not hasattr(button, "set_progress")
    assert not hasattr(button, "start")
    assert not hasattr(button, "finish")


def test_flash_guard_shows_the_message_on_the_button(button):
    button.flash_guard("Select an input image")
    assert button.text() == "Select an input image"


def test_the_caption_is_what_a_flashed_guard_comes_back_to(button):
    # The resting caption says what a press will do — "Generate with Random seed"
    # where the settings would otherwise re-create a past generation — so a guard
    # that has had its moment hands that caption back, not "Generate".
    button.set_caption("Generate with Random seed")
    assert button.text() == "Generate with Random seed"

    button.flash_guard("Select an input image")
    button._guard_timer.timeout.emit()

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
