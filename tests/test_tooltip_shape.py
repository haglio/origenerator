from __future__ import annotations

import html

from PyQt6.QtCore import QEvent, QPoint
from PyQt6.QtGui import QHelpEvent
from PyQt6.QtWidgets import QApplication, QLabel, QListWidget, QListWidgetItem, QToolTip
from shared_ui.colors import WHITE

from origenerator.gui.stylesheet import dress_application
from origenerator.gui.tooltip_shape import shaped

LONG = ("How strictly the model obeys the prompt. Too low drifts off it; too high burns "
        "contrast & flattens <detail>.")


def _hover(widget, at: QPoint) -> None:
    QApplication.sendEvent(widget, QHelpEvent(QEvent.Type.ToolTip, at, widget.mapToGlobal(at)))


def test_a_short_tooltip_stays_one_line():
    assert shaped("The output width in pixels.") == "The output width in pixels."


def test_a_long_tooltip_is_shown_as_a_block_of_lines():
    assert shaped(LONG) == ('<p style="white-space:pre">How strictly the model obeys the prompt. '
                            "Too low drifts off it; too high burns\ncontrast &amp; flattens "
                            "&lt;detail&gt;.</p>")


def test_every_line_of_a_long_tooltip_is_at_most_eighty_characters():
    words = " ".join(f"word{n}" for n in range(60))

    lines = html.unescape(shaped(words).removeprefix('<p style="white-space:pre">')
                          .removesuffix("</p>")).split("\n")

    assert max(len(line) for line in lines) <= 80
    assert " ".join(lines) == words


def test_a_tooltip_already_written_as_rich_text_is_left_as_written():
    rich = "<b>Bold</b> " + "x" * 80
    assert shaped(rich) == rich


def test_the_dressed_app_shows_a_long_tooltip_as_a_block(qapp, qtbot):
    dress_application(qapp, None)
    label = QLabel("hover me")
    label.setToolTip(LONG)
    qtbot.addWidget(label)
    label.show()

    _hover(label, QPoint(2, 2))

    assert QToolTip.text() == shaped(LONG)


def test_the_dressed_app_shows_a_long_choice_tooltip_as_a_block(qapp, qtbot):
    dress_application(qapp, None)
    choices = QListWidget()
    item = QListWidgetItem("euler")
    item.setToolTip(LONG)
    choices.addItem(item)
    qtbot.addWidget(choices)
    choices.show()

    _hover(choices.viewport(), choices.visualItemRect(item).center())

    assert QToolTip.text() == shaped(LONG)


def test_a_tooltip_can_open_with_a_bold_white_lead():
    assert shaped("Euler a on model pages.", lead="Recommended.") == (
        f'<p style="white-space:pre"><b style="color:{WHITE.name()}">Recommended.</b> '
        "Euler a on model pages.</p>")
