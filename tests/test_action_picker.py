"""The row on a config tab saying what the item it is showing shows.

States are the committed example overlay's own (see CLAUDE.md).
"""
from __future__ import annotations

import json

import pytest
from PyQt6.QtWidgets import QComboBox, QLabel, QMessageBox, QPushButton, QWidget

from origenerator.gui import action_picker
from origenerator.gui.action_picker import (
    ACTION_LABEL,
    SORT_BUTTON,
    ActionPicker,
)

_STATES = ("state one", "state two", "state three")
_ACTS = ("act one", "act two")


def _row(prompt_id="img", *, filename="scene_00001_.png", state=None, act=None):
    return {
        "prompt_id": prompt_id,
        "workflow_name": "sdxl_t2i",
        "output_files": json.dumps([{"filename": filename}]),
        "picture_state": state,
        "act": act,
    }


@pytest.fixture
def picker(qtbot):
    made = ActionPicker(_STATES, _ACTS)
    qtbot.addWidget(made)
    return made


def test_a_picture_offers_every_state_and_opens_on_the_one_it_was_sorted_as(picker):
    picker.show_row(_row(state="state two"))

    assert not picker.isHidden()
    assert picker.picked() == "state two"
    assert picker.offered() == ["", *_STATES]


def test_a_picture_nobody_has_sorted_yet_opens_on_nothing(picker):
    picker.show_row(_row())

    assert picker.picked() == ""


def test_a_picture_sorted_as_a_state_the_list_no_longer_offers_opens_on_nothing(picker):
    picker.show_row(_row(state="a state taken off the list"))

    assert not picker.isHidden()
    assert picker.picked() == ""


def test_picking_a_state_says_which_picture_it_is_for(picker, qtbot):
    picker.show_row(_row("img-7"))

    with qtbot.waitSignal(picker.chosen) as caught:
        picker.pick("state three")

    assert caught.args == ["img-7", "state three"]


def test_putting_a_picture_up_does_not_read_as_someone_picking_for_it(picker):
    said = []
    picker.chosen.connect(lambda *args: said.append(args))

    picker.show_row(_row("img-7", state="state one"))

    assert said == []


def test_taking_the_answer_back_says_so_rather_than_saying_nothing(picker, qtbot):
    picker.show_row(_row("img-7", state="state one"))

    with qtbot.waitSignal(picker.chosen) as caught:
        picker.pick("")

    assert caught.args == ["img-7", ""]


def test_a_video_offers_every_act_and_opens_on_the_one_it_shows(picker):
    picker.show_row(_row(filename="scene_00001_.mp4", act="act two"))

    assert not picker.isHidden()
    assert picker.picked() == "act two"
    assert picker.offered() == ["", *_ACTS]


def test_an_act_the_list_lacks_shows_as_itself_at_its_foot(picker):
    picker.show_row(_row(filename="scene_00001_.mp4", act="an act from elsewhere"))

    assert picker.picked() == "an act from elsewhere"
    assert picker.offered() == ["", *_ACTS, "an act from elsewhere"]


def test_an_act_spelled_like_one_on_the_list_but_for_case_and_spacing_is_that_act(picker):
    picker.show_row(_row(filename="scene_00001_.mp4", act="  ACT   two "))

    assert picker.picked() == "act two"
    assert picker.offered() == ["", *_ACTS]


def test_only_a_picture_offers_the_button_that_sorts_pictures(picker):
    sort = picker.findChild(QPushButton, SORT_BUTTON)

    picker.show_row(_row(filename="scene_00001_.mp4"))
    on_a_video = sort.isHidden()
    picker.show_row(_row())

    assert (on_a_video, sort.isHidden()) == (True, False)


def test_the_list_says_whether_it_is_a_pictures_or_a_videos(picker):
    combo = picker.findChild(QComboBox)

    picker.show_row(_row(filename="scene_00001_.mp4"))
    on_a_video = combo.toolTip()
    picker.show_row(_row())

    assert (on_a_video, combo.toolTip()) == (
        "What this video shows — the act it was made as",
        "What this picture already shows — which decides what it can be animated as")


def test_a_tab_showing_nothing_shows_no_row(picker):
    picker.show_row(_row())
    picker.clear()

    assert picker.isHidden()


def test_the_row_is_labelled_action(picker):
    assert ACTION_LABEL in [label.text() for label in picker.findChildren(QLabel)]


def test_the_list_opens_on_a_dash_rather_than_a_phrase(picker):
    assert picker.findChild(QComboBox).itemText(0) == "— "


def test_the_list_opens_wide_enough_for_the_longest_action(picker):
    combo = picker.findChild(QComboBox)
    longest = max(combo.fontMetrics().horizontalAdvance(combo.itemText(i))
                  for i in range(combo.count()))

    assert combo.view().minimumWidth() > longest


def test_a_button_beside_the_list_opens_the_window_that_answers_for_them_all(
        picker, monkeypatch):
    """The same window its own launcher opens, built in one place, so the two
    cannot come to show different pictures."""
    said = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda parent, title, text: said.append(text))
    monkeypatch.setattr(action_picker, "the_sorting_window",
                        lambda first="": "Every picture already says what it shows.")

    picker.findChild(QPushButton, SORT_BUTTON).click()

    assert said == ["Every picture already says what it shows."]


def test_pressing_it_again_brings_the_window_it_opened_back_rather_than_a_second(
        picker, monkeypatch, qtbot):
    made = []

    def one_window(first=""):
        window = QWidget()
        qtbot.addWidget(window)
        made.append(window)
        return window

    monkeypatch.setattr(action_picker, "the_sorting_window", one_window)
    button = picker.findChild(QPushButton, SORT_BUTTON)

    button.click()
    button.click()

    assert len(made) == 1


def test_the_button_beside_the_list_says_what_pressing_it_sets(picker):
    """His words for what that button does: "set image actions"."""
    button = picker.findChild(QPushButton, SORT_BUTTON)

    assert (button.text(), button.toolTip()) == (
        "Set image actions…",
        "Set this picture's action, then every picture nobody has answered for, "
        "one press apiece")


def test_pressing_it_starts_on_the_picture_in_front_of_him(picker, monkeypatch):
    """His words: it "should start with the current image, then go on to the usual
    queue", so the window is told which picture is on display."""
    opened = []
    monkeypatch.setattr(QMessageBox, "information", lambda parent, title, text: None)
    monkeypatch.setattr(action_picker, "the_sorting_window",
                        lambda first="": opened.append(first) or "nothing waiting")

    picker.show_row(_row("img-seven", state="state two"))
    picker.findChild(QPushButton, SORT_BUTTON).click()

    assert opened == ["img-seven"]
