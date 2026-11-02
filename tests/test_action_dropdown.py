from __future__ import annotations

import json

import pytest
from PyQt6.QtWidgets import QComboBox, QLabel, QMessageBox, QPushButton, QWidget
from shared_ui.spacing import GAP_MEDIUM

from origenerator.gui import action_dropdown
from origenerator.gui.action_dropdown import (
    ACTION_LABEL,
    SORT_BUTTON,
    ActionDropdown,
)
from origenerator.gui.label_cells import LabelForm

_STATES = ("state one", "state two", "state three")
_ACTIONS_OFFERED = ("action one", "action two")


def _row(prompt_id="img", *, filename="scene_00001_.png", state=None, action=None):
    return {
        "prompt_id": prompt_id,
        "workflow_name": "sdxl_t2i",
        "output_files": json.dumps([{"filename": filename}]),
        "image_state": state,
        "action": action,
    }


@pytest.fixture
def dropdown(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    return ActionDropdown(_STATES, _ACTIONS_OFFERED, LabelForm(host))


def test_an_image_offers_every_state_and_opens_on_the_one_it_was_sorted_as(dropdown):
    dropdown.show_row(_row(state="state two"))

    assert not dropdown.isHidden()
    assert dropdown.picked() == "state two"
    assert dropdown.offered() == ["", *_STATES]


def test_the_list_sits_one_gap_from_its_button_as_a_forms_field_does(dropdown):
    dropdown.show_row(_row())
    dropdown.parentWidget().resize(600, 40)
    dropdown.parentWidget().show()
    dropdown.layout().activate()
    listed = dropdown.findChild(QComboBox)
    button = dropdown.findChild(QPushButton, SORT_BUTTON)

    assert button.x() - (listed.x() + listed.width()) == GAP_MEDIUM


def test_an_image_nobody_has_sorted_yet_opens_on_nothing(dropdown):
    dropdown.show_row(_row())

    assert dropdown.picked() == ""


def test_an_image_sorted_as_a_state_the_list_no_longer_offers_opens_on_nothing(dropdown):
    dropdown.show_row(_row(state="a state taken off the list"))

    assert not dropdown.isHidden()
    assert dropdown.picked() == ""


def test_picking_a_state_says_which_image_it_is_for(dropdown, qtbot):
    dropdown.show_row(_row("img-7"))

    with qtbot.waitSignal(dropdown.chosen) as caught:
        dropdown.pick("state three")

    assert caught.args == ["img-7", "state three"]


def test_putting_an_image_up_does_not_read_as_someone_picking_for_it(dropdown):
    said = []
    dropdown.chosen.connect(lambda *args: said.append(args))

    dropdown.show_row(_row("img-7", state="state one"))

    assert said == []


def test_taking_the_answer_back_says_so_rather_than_saying_nothing(dropdown, qtbot):
    dropdown.show_row(_row("img-7", state="state one"))

    with qtbot.waitSignal(dropdown.chosen) as caught:
        dropdown.pick("")

    assert caught.args == ["img-7", ""]


def test_a_video_offers_every_action_and_opens_on_the_one_it_shows(dropdown):
    dropdown.show_row(_row(filename="scene_00001_.mp4", action="action two"))

    assert not dropdown.isHidden()
    assert dropdown.picked() == "action two"
    assert dropdown.offered() == ["", *_ACTIONS_OFFERED]


def test_an_action_the_list_lacks_shows_as_itself_at_its_foot(dropdown):
    dropdown.show_row(_row(filename="scene_00001_.mp4", action="an action from elsewhere"))

    assert dropdown.picked() == "an action from elsewhere"
    assert dropdown.offered() == ["", *_ACTIONS_OFFERED, "an action from elsewhere"]


def test_an_action_spelled_like_one_on_the_list_but_for_case_and_spacing_is_that_action(dropdown):
    dropdown.show_row(_row(filename="scene_00001_.mp4", action="  ACTION   two "))

    assert dropdown.picked() == "action two"
    assert dropdown.offered() == ["", *_ACTIONS_OFFERED]


def test_only_an_image_offers_the_button_that_sorts_images(dropdown):
    sort = dropdown.findChild(QPushButton, SORT_BUTTON)

    dropdown.show_row(_row(filename="scene_00001_.mp4"))
    on_a_video = sort.isHidden()
    dropdown.show_row(_row())

    assert (on_a_video, sort.isHidden()) == (True, False)


def test_the_list_says_whether_it_is_an_images_or_a_videos(dropdown):
    inner = dropdown.findChild(QComboBox)

    dropdown.show_row(_row(filename="scene_00001_.mp4"))
    on_a_video = inner.toolTip()
    dropdown.show_row(_row())

    assert (on_a_video, inner.toolTip()) == (
        "What this video shows — the action it was made as",
        "What this image already shows — which decides what it can be animated as")


def test_a_tab_showing_nothing_shows_no_row(dropdown):
    dropdown.show_row(_row())
    dropdown.clear()

    assert dropdown.isHidden()


def test_the_row_is_labeled_action(dropdown):
    name = dropdown.parentWidget().layout().labelForField(dropdown)

    assert ACTION_LABEL in [label.text() for label in name.findChildren(QLabel)]


def test_the_list_opens_on_a_dash_rather_than_a_phrase(dropdown):
    assert dropdown.findChild(QComboBox).itemText(0) == "— "


def test_the_list_opens_wide_enough_for_the_longest_action(dropdown):
    inner = dropdown.findChild(QComboBox)
    longest = max(inner.fontMetrics().horizontalAdvance(inner.itemText(i))
                  for i in range(inner.count()))

    assert inner.view().minimumWidth() > longest


def test_a_button_beside_the_list_opens_the_window_that_answers_for_them_all(
        dropdown, monkeypatch):
    said = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda parent, title, text: said.append(text))
    monkeypatch.setattr(action_dropdown, "the_sorting_window",
                        lambda first="": "Every image already says what it shows.")

    dropdown.findChild(QPushButton, SORT_BUTTON).click()

    assert said == ["Every image already says what it shows."]


def test_pressing_it_again_brings_the_window_it_opened_back_rather_than_a_second(
        dropdown, monkeypatch, qtbot):
    made = []

    def one_window(first=""):
        window = QWidget()
        qtbot.addWidget(window)
        made.append(window)
        return window

    monkeypatch.setattr(action_dropdown, "the_sorting_window", one_window)
    button = dropdown.findChild(QPushButton, SORT_BUTTON)

    button.click()
    button.click()

    assert len(made) == 1


def test_the_button_beside_the_list_says_what_pressing_it_sets(dropdown):
    button = dropdown.findChild(QPushButton, SORT_BUTTON)

    assert (button.text(), button.toolTip()) == (
        "Set image actions…",
        ("Set this image's action, then every image nobody has answered for, "
         "one press apiece"))


def test_pressing_it_starts_on_the_image_in_front_of_him(dropdown, monkeypatch):
    opened = []
    monkeypatch.setattr(QMessageBox, "information", lambda parent, title, text: None)
    monkeypatch.setattr(action_dropdown, "the_sorting_window",
                        lambda first="": opened.append(first) or "nothing waiting")

    dropdown.show_row(_row("img-seven", state="state two"))
    dropdown.findChild(QPushButton, SORT_BUTTON).click()

    assert opened == ["img-seven"]
