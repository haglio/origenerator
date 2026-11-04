from __future__ import annotations

from PyQt6.QtCore import QEvent, QPoint, Qt
from PyQt6.QtGui import QHelpEvent, QTextCursor
from PyQt6.QtWidgets import QApplication, QToolTip
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


def _shown_at(qtbot, width):
    exchange = RequestExchange()
    qtbot.addWidget(exchange)
    exchange.resize(width, 300)
    with qtbot.waitExposed(exchange):
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
    assert asked == []

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
    assert not exchange._conversation.isHidden()
    assert exchange._conversation.toPlainText().splitlines()[:2] == list(EXCHANGE[0])


def test_his_words_wear_one_color_and_the_answer_sits_a_step_to_the_right_in_plain_text(qtbot):
    exchange = _exchange(qtbot)

    exchange.show_exchange(EXCHANGE)

    page = exchange._conversation.document()
    words, answer = page.findBlockByNumber(0), page.findBlockByNumber(1)
    assert words.begin().fragment().charFormat().foreground().color() == BLUE_LIGHT
    assert answer.begin().fragment().charFormat().foreground().color() == TEXT_PRIMARY
    assert (words.blockFormat().leftMargin(), answer.blockFormat().leftMargin()) == (0, MARGIN_STANDARD)


def test_the_exchange_grows_with_the_conversation_until_twenty_lines(qtbot):
    exchange = _exchange(qtbot)

    exchange.show_exchange(EXCHANGE)
    short = exchange._conversation.height()
    exchange.show_exchange(EXCHANGE * 3)
    taller = exchange._conversation.height()

    assert short < taller
    assert exchange._conversation.verticalScrollBar().maximum() == 0
    assert taller <= exchange.fontMetrics().lineSpacing() * 20


def test_with_no_exchange_only_the_line_shows(qtbot):
    exchange = _exchange(qtbot)

    exchange.show_exchange([])

    assert exchange._conversation.isHidden()
    assert exchange.turns() == []


def test_a_request_just_asked_shows_as_a_turn_updating_until_its_answer_comes(qtbot):
    exchange = _exchange(qtbot)
    exchange.show_exchange(EXCHANGE)

    exchange.add_turn("brighter")

    assert exchange.turns()[-1] == ("brighter", "")
    assert exchange._status.text() == "updating…"
    assert not exchange._status.isHidden()
    assert not exchange._line.isEnabled()

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
    assert "couldn't" in exchange._status.text()
    assert not exchange._status.isHidden()
    assert exchange._line.isEnabled()


def test_a_failed_only_turn_leaves_the_line_alone_on_its_own(qtbot):
    exchange = _exchange(qtbot)
    exchange.add_turn("please")

    exchange.failed()

    assert exchange._conversation.isHidden()


def test_a_long_exchange_scrolls_rather_than_growing_and_sits_at_its_end(qtbot):
    exchange = _exchange(qtbot)

    exchange.show_exchange([(f"request {n}", f"answer {n}") for n in range(30)])
    qtbot.waitUntil(lambda: exchange._conversation.verticalScrollBar().maximum() > 0, timeout=2000)

    bar = exchange._conversation.verticalScrollBar()
    assert exchange._conversation.height() == exchange.fontMetrics().lineSpacing() * 20
    assert bar.value() == bar.maximum()


def test_hovering_a_turn_shows_the_change_it_made_to_the_prompts(qtbot):
    exchange = _exchange(qtbot)

    exchange.show_exchange([Turn("no hat", "Took the hat off.", "a woman, a hat", "blurry",
                                 "a woman", "blurry, hat")])

    (entry,) = exchange._entries()
    assert "a woman" in entry.tip
    assert "hat" in entry.tip
    assert exchange._entries()[0].tip != ""


def test_a_turn_with_no_change_recorded_has_nothing_to_show_when_hovered(qtbot):
    exchange = _exchange(qtbot)

    exchange.show_exchange([("no hat", "Nothing to change.")])

    assert exchange._entries()[0].tip == ""


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


def test_an_answer_coming_back_grows_the_box_so_no_scroll_bar_shows_on_two_lines(qtbot):
    exchange = _shown_at(qtbot, 400)

    exchange.add_turn("a hat")
    qtbot.wait(20)
    exchange.answered(("a hat", "Gave her a hat."))
    qtbot.wait(20)

    assert exchange._conversation.verticalScrollBar().maximum() == 0


def test_an_answer_that_wraps_onto_several_lines_shows_whole_with_no_scroll_bar(qtbot):
    exchange = _shown_at(qtbot, 300)

    exchange.add_turn("a hat")
    qtbot.wait(20)
    exchange.answered(("a hat", "Gave her a wide straw hat with a ribbon around it. " * 3))
    qtbot.wait(20)

    assert exchange._conversation.verticalScrollBar().maximum() == 0


def test_the_whole_conversation_can_be_selected_at_once(qtbot):
    exchange = _exchange(qtbot)
    exchange.show_exchange(EXCHANGE)
    conversation = exchange._conversation
    conversation.setFocus()

    qtbot.keyClick(conversation, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)

    selected = conversation.textCursor().selection().toPlainText()
    assert selected.splitlines() == [line for turn in EXCHANGE for line in turn]


def test_its_right_click_menu_takes_no_color_from_the_words(qtbot):
    exchange = _exchange(qtbot)
    exchange.show_exchange(EXCHANGE)

    assert "color" not in exchange._conversation.styleSheet()


def test_hovering_his_words_or_the_answer_shows_that_turns_change(qtbot):
    exchange = _shown_at(qtbot, 400)
    exchange.show_exchange([Turn("no hat", "Took it off.", "a hat", "", "a", ""), ("hello", "Hi.")])
    conversation = exchange._conversation

    def tip_on(line):
        block = conversation.document().findBlockByNumber(line)
        return conversation.tip_at(conversation.cursorRect(QTextCursor(block)).center())

    assert "hat" in tip_on(0)
    assert "hat" in tip_on(1)
    assert tip_on(2) == ""


def test_resting_the_mouse_on_a_turn_opens_its_tooltip_and_on_one_with_no_change_closes_it(qtbot):
    exchange = _shown_at(qtbot, 400)
    exchange.show_exchange([Turn("no hat", "Took it off.", "a hat", "", "a", ""), ("hello", "Hi.")])
    conversation = exchange._conversation

    def rest_on(line):
        block = conversation.document().findBlockByNumber(line)
        place = conversation.cursorRect(QTextCursor(block)).center()
        QApplication.sendEvent(conversation.viewport(), QHelpEvent(
            QEvent.Type.ToolTip, place, conversation.viewport().mapToGlobal(place)))

    rest_on(0)
    assert "hat" in QToolTip.text()
    rest_on(2)
    qtbot.waitUntil(lambda: not QToolTip.isVisible(), timeout=2000)


def test_a_place_with_no_turn_has_no_tooltip(qtbot):
    exchange = _shown_at(qtbot, 400)

    assert exchange._conversation.tip_at(QPoint(1, 1)) == ""
