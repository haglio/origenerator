from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtWidgets import QApplication, QWidget

from origenerator.gui.stylesheet import build_stylesheet


def drawn_under_the_app_stylesheet(qtbot, build: Callable[[], tuple[QWidget, QWidget]]):
    """Builds ``(tile, shown)`` under the app's stylesheet, shows ``shown`` and returns the tile with its grab."""
    app = QApplication.instance()
    prior = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    try:
        tile, shown = build()
        qtbot.addWidget(shown)
        with qtbot.waitExposed(shown):
            shown.show()
        return tile, shown.grab().toImage()
    finally:
        app.setStyleSheet(prior)
