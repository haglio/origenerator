"""The Request section: the exchange about the item on display, and the line a
request is typed in and sent with Enter."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from shared_ui.colors import BLUE_LIGHT, TEXT_PRIMARY
from shared_ui.spacing import MARGIN_STANDARD

from origenerator.db_requests import Turn
from origenerator.gui.request_exchange import RequestExchange

EXCHANGE = [("a hat", "Gave her a straw hat."), ("make it red", "The hat is red now.")]


def _exchange(qtbot):
    exchange = RequestExchange()
    qtbot.addWidget(exchange)
    exchange.show()
    return exchange


def _asked(qtbot, exchange):
    asked = []
    exchange.asked.connect(asked.append)
    return asked


def test_enter_asks_for_the_words_and_clears_the_line(qtbot):
    exchange = _exchange(qtbot)
    asked = _asked(qtbot, exchange)

    qtbot.keyClicks(exchange._line, "two women")
    qtbot.wait(700)
    assert asked == []  # neither per letter nor on a pause

    qtbot.keyClick(exchange._line, Qt.Key.Key_Return)
    assert asked == ["two women"]
    assert exchange._line.text() == ""


def test_enter_on_an_empty_line_asks_nothing(qtbot):
    exchange = _exchange(qtbot)
    asked = _asked(qtbot, exchange)

    qtbot.keyClick(exchange._line, Qt.Key.Key_Return)

    assert asked == []


def test_the_exchange_lists_each_turn_oldest_first_his_words_over_the_answer(qtbot):
    exchange = _exchange(qtbot)

    exchange.show_exchange(EXCHANGE)

    assert exchange.turns() == EXCHANGE
    assert not exchange._scroll.isHidden()
    first = exchange._entries()[0]
    assert first.said.y() < first.answered.y()


def test_his_words_wear_one_color_and_the_answer_sits_a_step_to_the_right_in_plain_text(qtbot):
    exchange = _exchange(qtbot)

    exchange.show_exchange(EXCHANGE)

    first = exchange._entries()[0]
    assert BLUE_LIGHT.name() in first.said.styleSheet()
    assert TEXT_PRIMARY.name() in first.answered.styleSheet()
    assert first.answered.x() - first.said.x() == MARGIN_STANDARD


def test_the_exchange_grows_with_the_conversation_until_twenty_lines(qtbot):
    exchange = _exchange(qtbot)

    exchange.show_exchange(EXCHANGE)
    short = exchange._scroll.height()
    exchange.show_exchange(EXCHANGE * 3)
    taller = exchange._scroll.height()

    assert short < taller
    assert exchange._scroll.verticalScrollBar().maximum() == 0
    assert taller <= exchange.fontMetrics().lineSpacing() * 20


def test_with_no_exchange_only_the_line_shows(qtbot):
    exchange = _exchange(qtbot)

    exchange.show_exchange([])

    assert exchange._scroll.isHidden()
    assert exchange.turns() == []


def test_a_request_just_asked_shows_as_a_turn_updating_until_its_answer_comes(qtbot):
    exchange = _exchange(qtbot)
    exchange.show_exchange(EXCHANGE)

    exchange.add_turn("brighter")

    assert exchange.turns()[-1] == ("brighter", "")
    assert exchange._status.text() == "updating…" and not exchange._status.isHidden()
    assert not exchange._line.isEnabled()  # one request at a time

    exchange.answered(("brighter", "Brighter now."))

    assert exchange.turns()[-1] == ("brighter", "Brighter now.")
    assert exchange._status.isHidden()
    assert exchange._line.isEnabled()


def test_a_request_the_model_could_not_work_out_comes_off_and_says_so_beside_the_line(qtbot):
    exchange = _exchange(qtbot)
    exchange.show_exchange(EXCHANGE)
    exchange.add_turn("please")

    exchange.failed()

    assert exchange.turns() == EXCHANGE
    assert "couldn't" in exchange._status.text() and not exchange._status.isHidden()
    assert exchange._line.isEnabled()


def test_a_failed_only_turn_leaves_the_line_alone_on_its_own(qtbot):
    exchange = _exchange(qtbot)
    exchange.add_turn("please")

    exchange.failed()

    assert exchange._scroll.isHidden()


def test_a_long_exchange_scrolls_rather_than_growing_and_sits_at_its_end(qtbot):
    exchange = _exchange(qtbot)

    exchange.show_exchange([(f"request {n}", f"answer {n}") for n in range(30)])
    qtbot.waitUntil(lambda: exchange._scroll.verticalScrollBar().maximum() > 0, timeout=2000)

    bar = exchange._scroll.verticalScrollBar()
    assert exchange._scroll.height() == exchange.fontMetrics().lineSpacing() * 20
    assert bar.value() == bar.maximum()


def test_hovering_a_turn_shows_the_change_it_made_to_the_prompts(qtbot):
    exchange = _exchange(qtbot)

    exchange.show_exchange([Turn("no hat", "Took the hat off.", "a woman, a hat", "blurry",
                                 "a woman", "blurry, hat")])

    (entry,) = exchange._entries()
    assert "a woman" in entry.toolTip() and "hat" in entry.toolTip()
    assert exchange._entries()[0].toolTip() != ""


def test_a_turn_with_no_change_recorded_has_nothing_to_show_when_hovered(qtbot):
    exchange = _exchange(qtbot)

    exchange.show_exchange([("no hat", "Nothing to change.")])

    assert exchange._entries()[0].toolTip() == ""


def test_with_no_image_there_is_nothing_to_ask_of(qtbot):
    exchange = _exchange(qtbot)
    exchange.show_exchange(EXCHANGE)

    exchange.set_available(False)

    assert not exchange._line.isEnabled()
    assert exchange.turns() == []
    assert exchange._line.placeholderText() == "Pick an image to ask a change of"

    exchange.set_available(True)

    assert exchange._line.isEnabled()
    assert exchange._line.placeholderText() == "What to change, e.g. two women"
