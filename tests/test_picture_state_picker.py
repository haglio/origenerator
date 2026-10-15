"""The row on a config tab saying what the picture it is showing shows.

States are the committed example overlay's own (see CLAUDE.md).
"""
from __future__ import annotations

import json

import pytest
from PyQt6.QtWidgets import QComboBox, QLabel, QMessageBox, QPushButton, QWidget

from origenerator.gui import picture_state_picker
from origenerator.gui.picture_state_picker import (
    ACTION_LABEL,
    SORT_BUTTON,
    PictureStatePicker,
)

_STATES = ("state one", "state two", "state three")


def _row(prompt_id="img", *, filename="scene_00001_.png", state=None):
    return {
        "prompt_id": prompt_id,
        "workflow_name": "sdxl_t2i",
        "output_files": json.dumps([{"filename": filename}]),
        "picture_state": state,
    }


@pytest.fixture
def picker(qtbot):
    made = PictureStatePicker(_STATES)
    qtbot.addWidget(made)
    return made


def test_a_picture_offers_every_state_and_opens_on_the_one_it_was_sorted_as(picker):
    picker.show_row(_row(state="state two"))

    assert not picker.isHidden()
    assert picker.chosen_state() == "state two"
    assert picker.offered() == ["", *_STATES]


def test_a_picture_nobody_has_sorted_yet_opens_on_nothing(picker):
    picker.show_row(_row())

    assert picker.chosen_state() == ""


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


def test_a_video_has_no_state_to_pick_and_the_row_stays_away(picker):
    picker.show_row(_row(filename="scene_00001_.mp4"))

    assert picker.isHidden()


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
    monkeypatch.setattr(picture_state_picker, "the_sorting_window",
                        lambda: "Every picture already says what it shows.")

    picker.findChild(QPushButton, SORT_BUTTON).click()

    assert said == ["Every picture already says what it shows."]


def test_pressing_it_again_brings_the_window_it_opened_back_rather_than_a_second(
        picker, monkeypatch, qtbot):
    made = []

    def one_window():
        window = QWidget()
        qtbot.addWidget(window)
        made.append(window)
        return window

    monkeypatch.setattr(picture_state_picker, "the_sorting_window", one_window)
    button = picker.findChild(QPushButton, SORT_BUTTON)

    button.click()
    button.click()

    assert len(made) == 1
