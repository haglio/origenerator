from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QHelpEvent, QImage, QMouseEvent, QTextCursor, QTextDocument
from PySide6.QtWidgets import QApplication, QToolTip
from shared_ui.colors import BG_TERTIARY, BLUE_LIGHT, TEXT_MUTED, TEXT_PRIMARY
from shared_ui.spacing import MARGIN_STANDARD
from shared_ui.testing import appending_to

from origenerator.db_requests import Turn
from origenerator.gui.generate_button import GenerateButton
from origenerator.gui.inflight import RunReading
from origenerator.gui.progress_bar import ProgressBar
from origenerator.gui.request_exchange import RequestExchange
from origenerator.gui.source_tile import SourceTile

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
    exchange.asked.connect(appending_to(asked))
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


def _request_button(exchange) -> GenerateButton:
    (button,) = [button for button in exchange.findChildren(GenerateButton)
                 if button.text() == "Request"]
    return button


def test_the_request_button_at_the_end_of_the_line_asks_for_the_words_and_clears_the_line(qtbot):
    exchange = _exchange(qtbot)
    asked = _asked(qtbot, exchange)
    qtbot.keyClicks(exchange._line, "two women")

    qtbot.mouseClick(_request_button(exchange), Qt.MouseButton.LeftButton)

    assert (asked, exchange._line.text()) == (["two women"], "")
    row = exchange._line.parentWidget().layout().itemAt(1)
    assert row.layout().itemAt(row.layout().count() - 1).widget() is _request_button(exchange)


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


def test_a_request_just_asked_shows_as_a_turn_until_its_answer_comes(qtbot):
    exchange = _exchange(qtbot)
    exchange.show_exchange(EXCHANGE)

    exchange.add_turn("brighter")

    assert exchange.turns()[-1] == ("brighter", "")
    assert exchange._status.isHidden()
    assert not exchange._line.isEnabled()

    exchange.answered(("brighter", "Brighter now."))

    assert exchange.turns()[-1] == ("brighter", "Brighter now.")
    assert exchange._line.isEnabled()


def _sweeping_bars(exchange) -> list[str]:
    return [bar.caption() for bar in exchange.findChildren(ProgressBar)
            if not bar.isHidden() and bar.maximum() == 0]


def test_the_request_button_is_a_sweeping_bar_of_its_own_size_while_a_request_is_worked_out(
        qtbot):
    exchange = _exchange(qtbot)
    button = _request_button(exchange)
    size = button.size()

    exchange.add_turn("brighter")
    (bar,) = [bar for bar in exchange.findChildren(ProgressBar) if not bar.isHidden()]

    assert (_sweeping_bars(exchange), button.isHidden(), bar.size()) == (["Request"], True, size)

    exchange.answered(("brighter", "Brighter now."))

    assert (_sweeping_bars(exchange), button.isHidden()) == ([], False)


def test_an_exchange_shown_with_a_request_still_being_worked_out_waits_on_it(qtbot):
    exchange = _exchange(qtbot)

    exchange.show_exchange(EXCHANGE, asking="brighter")

    assert exchange.turns()[-1] == ("brighter", "")
    assert _sweeping_bars(exchange) == ["Request"]
    assert not exchange._line.isEnabled()

    exchange.answered(("brighter", "Brighter now."))

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
    assert tip_on(3) == ""


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
    rest_on(3)
    qtbot.waitUntil(lambda: not QToolTip.isVisible(), timeout=2000)


def test_a_place_with_no_turn_has_no_tooltip(qtbot):
    exchange = _shown_at(qtbot, 400)

    assert exchange._conversation.tip_at(QPoint(1, 1)) == ""


def _thumbnails(tmp_path, *names):
    paths = {}
    for name in names:
        image = QImage(40, 20, QImage.Format.Format_RGB32)
        image.fill(QColor("gray"))
        path = tmp_path / f"{name}.png"
        image.save(str(path))
        paths[name] = str(path)
    return paths


def _changed(said, made=""):
    return Turn(said, "Changed it.", "a hat", "", "a cap", "", made=made)


def test_hovering_a_turn_shows_the_item_before_it_on_the_left_and_the_one_made_from_it(
        qtbot, tmp_path):
    paths = _thumbnails(tmp_path, "start", "first", "second")
    exchange = _exchange(qtbot)
    exchange.set_thumbnail_of(paths.get)

    exchange.show_exchange([_changed("a cap", made="first"), _changed("red", made="second")],
                           started_on="start")

    first, second = exchange._entries()
    assert first.tip.index(paths["start"]) < first.tip.index(paths["first"])
    assert second.tip.index(paths["first"]) < second.tip.index(paths["second"])
    assert first.tip.index(paths["first"]) < first.tip.index("cap")


def test_a_turn_nothing_was_made_from_shows_a_question_mark_after_and_before_the_next(
        qtbot, tmp_path):
    paths = _thumbnails(tmp_path, "start", "second")
    exchange = _exchange(qtbot)
    exchange.set_thumbnail_of(paths.get)

    exchange.show_exchange([_changed("a cap"), _changed("red", made="second")],
                           started_on="start")

    first, second = exchange._entries()
    assert paths["start"] in first.tip
    assert paths["second"] in second.tip
    assert [_stand_in_sizes(entry.tip) for entry in (first, second)] == [
        [None, (192, 96)], [(192, 96), None]]


def _stand_in_sizes(tip):
    document = QTextDocument()
    document.setHtml(tip)
    sizes = []
    block = document.begin()
    while block.isValid():
        for fragment in _fragments(block):
            if fragment.charFormat().isImageFormat():
                picture = fragment.charFormat().toImageFormat()
                sizes.append((round(picture.width()), round(picture.height()))
                             if "not made" in picture.name() else None)
        block = block.next()
    return sizes


def _fragments(block):
    it = block.begin()
    while not it.atEnd():
        yield it.fragment()
        it += 1


def test_the_stand_in_for_an_item_not_made_is_a_gray_the_hover_box_does_not_wear(
        qtbot, tmp_path):
    paths = _thumbnails(tmp_path, "start")
    exchange = _exchange(qtbot)
    exchange.set_thumbnail_of(paths.get)

    exchange.show_exchange([_changed("a cap")], started_on="start")

    (entry,) = exchange._entries()
    name = next(part.split('"')[0] for part in entry.tip.split('src="')[1:] if "not made" in part)
    stand_in = QImage(name)
    assert (stand_in.width(), stand_in.height()) == (192, 96)
    assert stand_in.pixelColor(2, 2) == TEXT_MUTED
    assert TEXT_MUTED != BG_TERTIARY
    marked = [(x, y) for x in range(192) for y in range(96)
              if stand_in.pixelColor(x, y) != TEXT_MUTED]
    assert min(y for _x, y in marked) < 30
    assert max(y for _x, y in marked) > 66


def _placed(exchange, kind):
    return [widget for widget in exchange._conversation.viewport().findChildren(kind)
            if not widget.isHidden()]


def test_a_turn_that_changed_something_and_made_nothing_offers_generate_under_it(qtbot):
    exchange = _shown_at(qtbot, 400)
    asked = []
    exchange.generate_asked.connect(appending_to(asked))

    exchange.show_exchange([("hello", "Hi."), _changed("a cap"), _changed("red")])

    buttons = _placed(exchange, GenerateButton)
    assert [button.text() for button in buttons] == ["Generate", "Generate"]
    qtbot.mouseClick(buttons[1], Qt.MouseButton.LeftButton)
    assert asked == [2]


def test_a_turn_that_left_the_prompts_and_settings_as_they_were_offers_no_generate(qtbot):
    exchange = _shown_at(qtbot, 400)

    exchange.show_exchange([Turn("red", "It was already red.", "a red hat", "", "a red hat", ""),
                            _changed("a cap")])

    assert len(_placed(exchange, GenerateButton)) == 1


def test_generate_sits_under_its_turns_answer_on_a_line_of_its_own(qtbot):
    exchange = _shown_at(qtbot, 400)

    exchange.show_exchange([_changed("a cap"), _changed("red")])
    qtbot.wait(20)

    conversation = exchange._conversation
    first, _second = _placed(exchange, GenerateButton)
    answer = conversation.document().findBlockByNumber(1)
    next_words = conversation.document().findBlockByNumber(3)
    assert first.y() >= conversation.cursorRect(QTextCursor(answer)).bottom()
    assert first.geometry().bottom() < conversation.cursorRect(QTextCursor(next_words)).top()


def test_a_turn_an_item_was_made_from_shows_its_thumbnail_where_generate_would_be(
        qtbot, tmp_path):
    paths = _thumbnails(tmp_path, "first")
    exchange = _shown_at(qtbot, 400)
    exchange.set_thumbnail_of(paths.get)

    exchange.show_exchange([_changed("a cap", made="first"), _changed("red")])

    assert len(_placed(exchange, GenerateButton)) == 1
    html = exchange._conversation.document().toHtml()
    assert paths["first"] in html


def _thumbnail_place(exchange) -> QPoint:
    conversation = exchange._conversation
    block = conversation.document().findBlockByNumber(2)
    corner = conversation.document().documentLayout().blockBoundingRect(block).topLeft()
    return QPoint(round(corner.x()) + MARGIN_STANDARD + 4,
                  round(corner.y() + block.blockFormat().topMargin()) + 4)


def _shown_with_a_thumbnail(qtbot, tmp_path):
    paths = _thumbnails(tmp_path, "first")
    exchange = _shown_at(qtbot, 400)
    exchange.set_thumbnail_of(paths.get)
    exchange.show_exchange([_changed("a cap", made="first")])
    return exchange


def test_clicking_a_turns_thumbnail_opens_the_item_it_made_as_a_link_tile_does(qtbot, tmp_path):
    exchange = _shown_with_a_thumbnail(qtbot, tmp_path)
    opened = []
    exchange.item_activated.connect(appending_to(opened))

    qtbot.mouseClick(exchange._conversation.viewport(), Qt.MouseButton.LeftButton,
                     pos=_thumbnail_place(exchange))
    qtbot.mouseClick(exchange._conversation.viewport(), Qt.MouseButton.LeftButton,
                     pos=QPoint(2, 2))

    assert opened == ["first"]


def _move_to(viewport, place: QPoint) -> None:
    QApplication.sendEvent(viewport, QMouseEvent(
        QEvent.Type.MouseMove, QPointF(place), QPointF(viewport.mapToGlobal(place)),
        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))


def test_the_pointer_over_a_turns_thumbnail_is_the_hand_a_link_tile_shows(qtbot, tmp_path):
    exchange = _shown_with_a_thumbnail(qtbot, tmp_path)
    viewport = exchange._conversation.viewport()

    _move_to(viewport, _thumbnail_place(exchange))
    over = viewport.cursor().shape()
    _move_to(viewport, QPoint(2, 2))

    assert (over, viewport.cursor().shape()) == (SourceTile().cursor().shape(),
                                                 Qt.CursorShape.IBeamCursor)


def test_a_turn_whose_item_is_being_made_shows_its_progress_until_the_thumbnail_comes(
        qtbot, tmp_path):
    paths = _thumbnails(tmp_path, "first")
    thumbnails = {}
    exchange = _shown_at(qtbot, 400)
    exchange.set_thumbnail_of(thumbnails.get)
    exchange.show_exchange([_changed("a cap", made="first")])

    exchange.note_in_flight({"first": RunReading(status="running", progress=(3, 10))})

    (bar,) = _placed(exchange, ProgressBar)
    assert (bar.value(), bar.maximum()) == (3, 10)
    assert _placed(exchange, GenerateButton) == []

    thumbnails["first"] = paths["first"]
    exchange.note_in_flight({})

    assert _placed(exchange, ProgressBar) == []
    assert paths["first"] in exchange._conversation.document().toHtml()


def test_auto_generate_sits_at_the_end_of_the_line_and_starts_off(qtbot):
    exchange = _shown_at(qtbot, 400)

    switch = exchange._auto_generate
    assert switch.text() == "Auto-generate"
    assert not switch.isChecked()
    assert switch.geometry().left() > exchange._line.geometry().right()


def test_with_auto_generate_on_each_answer_that_changes_something_is_generated(qtbot):
    exchange = _shown_at(qtbot, 400)
    asked = []
    exchange.generate_asked.connect(appending_to(asked))
    exchange.set_auto_generate(True)
    exchange.show_exchange([_changed("a cap", made="first")])

    exchange.add_turn("hello")
    exchange.answered(("hello", "Hi."))
    exchange.add_turn("red")
    exchange.answered(_changed("red"))

    assert asked == [2]


def test_with_auto_generate_on_an_answer_that_left_everything_as_it_was_makes_nothing(qtbot):
    exchange = _shown_at(qtbot, 400)
    asked = []
    exchange.generate_asked.connect(asked.append)
    exchange.set_auto_generate(True)

    exchange.add_turn("red")
    exchange.answered(Turn("red", "It was already red.", "a red hat", "", "a red hat", ""))

    assert asked == []


def test_with_auto_generate_off_an_answer_waits_for_generate(qtbot):
    exchange = _shown_at(qtbot, 400)
    asked = []
    exchange.generate_asked.connect(appending_to(asked))

    exchange.add_turn("red")
    exchange.answered(_changed("red"))

    assert asked == []


def test_flipping_auto_generate_says_so(qtbot):
    exchange = _shown_at(qtbot, 400)
    chosen = []
    exchange.auto_generate_chosen.connect(appending_to(chosen))

    qtbot.mouseClick(exchange._auto_generate, Qt.MouseButton.LeftButton)

    assert chosen == [True]


def test_a_spoken_turn_with_no_answer_that_changed_something_offers_generate_too(qtbot):
    exchange = _shown_at(qtbot, 400)

    exchange.show_exchange([Turn("no hat", "", "a hat", "", "a", "")])

    assert len(_placed(exchange, GenerateButton)) == 1
