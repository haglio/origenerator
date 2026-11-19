from __future__ import annotations

import pytest
from PySide6.QtCore import QRect, Qt
from shared_ui.message_shape import HEARD_MARK, MESSAGE_TOP_MARGIN

from origenerator.gui.message_over_a_funestra import MessageOverAFunestra

_FUNESTRA = QRect(2560, 0, 800, 600)
_LONG = ("a model's answer that runs on and on about every change it made to the prompt, "
         "far longer than any slideshow is wide")


@pytest.fixture
def message(qtbot) -> MessageOverAFunestra:
    message = MessageOverAFunestra()
    qtbot.addWidget(message)
    return message


def test_the_message_is_a_window_of_its_own_over_the_funestra_as_fun_times_is(message):
    assert message.isWindow()
    assert message.windowFlags() & Qt.WindowType.WindowStaysOnTopHint


def test_the_message_takes_neither_the_keyboard_nor_a_click_from_the_funestra_beneath(message):
    assert message.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert message.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert message.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_the_message_comes_up_across_the_top_of_the_funestra_in_the_middle(message):
    message.say_over(_FUNESTRA, "scene one")

    note = message.geometry()
    assert message.isVisible()
    assert note.top() == _FUNESTRA.top() + MESSAGE_TOP_MARGIN
    assert abs(note.center().x() - _FUNESTRA.center().x()) <= 1


@pytest.mark.parametrize("mark", ["", HEARD_MARK])
def test_a_message_too_long_for_the_funestra_is_elided_to_fit(message, mark):
    narrow = QRect(2560, 0, 400, 300)

    message.say_over(narrow, _LONG, mark=mark)

    assert (message.geometry().left() >= narrow.left() + MESSAGE_TOP_MARGIN,
            message.geometry().right() < narrow.right() - MESSAGE_TOP_MARGIN,
            "…" in message.text()) == (True, True, True)


def test_a_message_follows_its_funestra_when_the_funestra_widens(message):
    message.say_over(QRect(2560, 0, 400, 300), _LONG)

    message.reposition_over(QRect(2560, 0, 4000, 300))

    assert message.text() == _LONG


def test_a_message_that_fits_is_shown_whole(message):
    message.say_over(_FUNESTRA, "scene one")

    assert message.text() == "scene one"


def test_a_message_shut_down_is_off_the_screen(message):
    message.say_over(_FUNESTRA, "scene one")

    message.shutdown()

    assert not message.isVisible()
