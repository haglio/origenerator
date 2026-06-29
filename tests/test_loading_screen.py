from PyQt6.QtWidgets import QLabel, QProgressBar

from origenerator.gui.loading_screen import LoadingScreen


def test_progress_bar_is_indeterminate(qtbot):
    screen = LoadingScreen()
    qtbot.addWidget(screen)
    bars = screen.findChildren(QProgressBar)
    assert len(bars) == 1
    # range (0, 0) makes Qt render a busy sweep instead of a percentage.
    assert bars[0].minimum() == 0
    assert bars[0].maximum() == 0


def test_set_status_updates_visible_text(qtbot):
    screen = LoadingScreen()
    qtbot.addWidget(screen)
    screen.set_status("Starting ComfyUI server")
    shown = [label.text() for label in screen.findChildren(QLabel)]
    assert any("Starting ComfyUI server" in text for text in shown)


def test_window_title_identifies_app(qtbot):
    screen = LoadingScreen()
    qtbot.addWidget(screen)
    assert "Origenerator" in screen.windowTitle()
