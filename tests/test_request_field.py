"""The words a tab is asked to change its picture by, typed or as they were heard."""
from __future__ import annotations

from origenerator.gui.request_field import RequestField


def _field(qtbot):
    field = RequestField()
    qtbot.addWidget(field)
    return field


def test_a_pause_in_the_typing_asks_for_the_words(qtbot):
    field = _field(qtbot)
    asked = []
    field.asked.connect(asked.append)

    qtbot.keyClicks(field._words, "two women")
    assert asked == []  # not per letter

    qtbot.waitUntil(lambda: asked == ["two women"], timeout=5000)


def test_it_says_updating_from_the_first_letter_until_the_prompts_catch_up(qtbot):
    field = _field(qtbot)
    field.asked.connect(lambda _words: None)

    qtbot.keyClicks(field._words, "two women")
    assert field._status.text() == "updating…" and not field._status.isHidden()

    qtbot.waitUntil(lambda: not field._pause.isActive(), timeout=5000)
    field.done()
    assert field._status.isHidden()


def test_words_put_in_for_a_picture_ask_for_nothing(qtbot):
    field = _field(qtbot)
    asked = []
    field.asked.connect(asked.append)

    field.show_words("no hat")

    qtbot.wait(field.PAUSE_MS + 100)
    assert asked == []
    assert field._words.text() == "no hat"


def test_a_failed_update_says_so_beside_the_words(qtbot):
    field = _field(qtbot)

    field.failed()

    assert not field._status.isHidden()
    assert "couldn't" in field._status.text()


def test_with_no_picture_there_is_nothing_to_ask_of(qtbot):
    field = _field(qtbot)
    field.show_words("no hat")

    field.set_available(False)

    assert not field._words.isEnabled()
    assert field._words.text() == ""
