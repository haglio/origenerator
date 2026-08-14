import pytest

from origenerator.gui.generate_button import GenerateButton


@pytest.fixture
def button(qtbot):
    b = GenerateButton()
    qtbot.addWidget(b)
    return b


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
