from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from shared_ui.colors import BLUE

from origenerator.gui.generate_button import GenerateButton
from origenerator.gui.stylesheet import build_stylesheet


@pytest.fixture
def button(qtbot):
    b = GenerateButton()
    qtbot.addWidget(b)
    return b


@pytest.fixture
def styled_button(qtbot):
    host = QWidget()
    host.setStyleSheet(build_stylesheet())
    layout = QVBoxLayout(host)
    b = GenerateButton()
    layout.addWidget(b)
    qtbot.addWidget(host)
    host.resize(320, 60)
    with qtbot.waitExposed(host):
        host.show()
    yield b


def _face(button):
    image = button.grab().toImage()
    return image.pixelColor(button.width() - 4, button.height() // 2)


def test_idle_reads_generate(button):
    assert button.text() == "Generate"


def test_the_button_keeps_the_primary_blue_with_a_run_in_flight(styled_button):
    assert _face(styled_button) == BLUE


def test_the_button_tracks_no_run(button):
    assert not hasattr(button, "set_progress")
    assert not hasattr(button, "start")
    assert not hasattr(button, "finish")


def test_flash_guard_shows_the_message_on_the_button(button):
    button.flash_guard("Rewrite the prompt first")
    assert button.text() == "Rewrite the prompt first"


def test_the_caption_is_what_a_flashed_guard_comes_back_to(button):
    button.set_caption("Generate with Random seed")
    assert button.text() == "Generate with Random seed"

    button.flash_guard("Rewrite the prompt first")
    button._guard_timer.timeout.emit()

    assert button.text() == "Generate with Random seed"


def test_a_new_caption_waits_for_the_guard_message_to_clear(button):
    button.flash_guard("Rewrite the prompt first")

    button.set_caption("Generate with Random seed")

    assert button.text() == "Rewrite the prompt first"
    button._clear_guard()
    assert button.text() == "Generate with Random seed"
