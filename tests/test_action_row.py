from __future__ import annotations

import json

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QComboBox, QLabel, QMessageBox, QPushButton, QWidget
from shared_ui.tick_control import TickControl

from origenerator.action_labels import Labels, stored
from origenerator.generation_state import GenerationSource
from origenerator.gui.action_row import (
    ADD,
    EDIT,
    UNSAID,
    ActionRow,
    action_checkbox,
    listed_actions,
    setter_button,
)
from origenerator.gui.label_cells import LabelForm
from origenerator.media import MediaType

_BOXES = {MediaType.IMAGE: ("first box", "second box"), MediaType.VIDEO: ("third box",)}


def _row(prompt_id="img", *, filename="scene_00001_.png", image=None, video=None,
         source=GenerationSource.GENERATED):
    image_actions, image_checked = stored(image) if image is not None else (None, None)
    video_actions, video_checked = stored(video) if video is not None else (None, None)
    return {"prompt_id": prompt_id, "workflow_name": "sdxl_t2i", "source": source,
            "output_files": json.dumps([{"filename": filename}]),
            "image_actions": image_actions, "image_checked": image_checked,
            "video_actions": video_actions, "video_checked": video_checked}


def _video(prompt_id="vid", **kwargs):
    return _row(prompt_id, filename="scene_00001_.mp4", **kwargs)


@pytest.fixture
def opened():
    return []


@pytest.fixture
def action(qtbot, opened):
    host = QWidget()
    qtbot.addWidget(host)

    def open_setter(side, first="", heard=None):
        opened.append((side, first))
        window = QWidget()
        qtbot.addWidget(window)
        window.heard = heard
        return window

    return ActionRow(LabelForm(host), checkboxes=_BOXES, open_setter=open_setter)


def _rows(action):
    return action.form().parentWidget()


def _listed(action, side) -> str:
    return _rows(action).findChild(QLabel, listed_actions(side)).text()


def _setter(action, side) -> QPushButton:
    return _rows(action).findChild(QPushButton, setter_button(side))


def _box(action, side, name) -> TickControl:
    return _rows(action).findChild(TickControl, action_checkbox(side, name))


def _named(action, side) -> str:
    part = _setter(action, side).parentWidget()
    cell = action.form().labelForField(part)
    return next(label.text() for label in cell.findChildren(QLabel) if label.text())


def test_an_image_lists_the_actions_it_was_set_with_and_no_dropdown(action):
    action.show_row(_row(image=Labels(("alpha", "beta"))))

    assert (_listed(action, MediaType.IMAGE), action.findChildren(QComboBox)) == ("alpha, beta", [])


def test_an_image_with_no_actions_shows_a_dash_and_offers_to_add_them(action):
    action.show_row(_row())

    assert (_listed(action, MediaType.IMAGE), _setter(action, MediaType.IMAGE).text()) == (
        UNSAID, ADD)
    assert ADD == "Add actions with setter tool…"


def test_an_image_with_actions_offers_to_edit_them(action):
    action.show_row(_row(image=Labels(("alpha",))))

    assert _setter(action, MediaType.IMAGE).text() == EDIT == "Edit actions with setter tool…"


def test_an_image_shows_its_checkboxes_to_the_right_of_its_button_as_it_saved_them(action, qtbot):
    action.show_row(_row(image=Labels(("alpha",), ("second box",))))
    host = _rows(action)
    host.resize(900, 60)
    with qtbot.waitExposed(host):
        host.show()
    button = _setter(action, MediaType.IMAGE)

    boxes = [_box(action, MediaType.IMAGE, name) for name in _BOXES[MediaType.IMAGE]]

    assert [box.isChecked() for box in boxes] == [False, True]
    assert all(box.mapTo(action, box.rect().topLeft()).x()
               > button.mapTo(action, button.rect().topLeft()).x() for box in boxes)


def test_clicking_a_checkbox_saves_it_with_the_actions_the_item_already_has(action, qtbot):
    action.show_row(_row(image=Labels(("alpha",))))

    with qtbot.waitSignal(action.changed) as caught:
        _box(action, MediaType.IMAGE, "first box").click()

    assert caught.args == ["img", MediaType.IMAGE, Labels(("alpha",), ("first box",))]


def test_an_image_shows_no_video_part(action):
    action.show_row(_row())

    assert _setter(action, MediaType.VIDEO).parentWidget().isHidden()


def test_the_button_opens_the_setter_tool_on_the_item_on_the_tab(action, opened):
    action.show_row(_row("img-seven"))

    _setter(action, MediaType.IMAGE).click()

    assert opened == [(MediaType.IMAGE, "img-seven")]


def test_pressing_it_again_brings_the_window_it_opened_back_rather_than_a_second(action, opened):
    action.show_row(_row("img-seven"))

    _setter(action, MediaType.IMAGE).click()
    action._windows[MediaType.IMAGE].show()
    _setter(action, MediaType.IMAGE).click()

    assert len(opened) == 1


def test_a_setter_tool_with_nothing_to_set_says_so(qtbot, monkeypatch):
    said = []
    monkeypatch.setattr(QMessageBox, "information", lambda parent, title, text: said.append(text))
    host = QWidget()
    qtbot.addWidget(host)
    action = ActionRow(LabelForm(host), checkboxes=_BOXES,
                       open_setter=lambda side, first="", heard=None: "nothing waiting")
    action.show_row(_row())

    _setter(action, MediaType.IMAGE).click()

    assert said == ["nothing waiting"]


def test_an_answer_the_setter_tool_gives_for_the_item_on_the_tab_shows_at_once(action):
    action.show_row(_row("img-seven"))
    _setter(action, MediaType.IMAGE).click()
    heard = action._windows[MediaType.IMAGE].heard

    heard("img-seven", MediaType.IMAGE, Labels(("gamma",), ("first box",)))
    heard("another image", MediaType.IMAGE, Labels(("alpha",)))

    assert (_listed(action, MediaType.IMAGE), _setter(action, MediaType.IMAGE).text(),
            _box(action, MediaType.IMAGE, "first box").isChecked()) == ("gamma", EDIT, True)


def test_an_answer_taken_back_in_the_setter_tool_shows_the_item_unlabeled_again(action):
    action.show_row(_row("img-seven", image=Labels(("alpha",))))
    _setter(action, MediaType.IMAGE).click()

    action._windows[MediaType.IMAGE].heard("img-seven", MediaType.IMAGE, None)

    assert (_listed(action, MediaType.IMAGE), _setter(action, MediaType.IMAGE).text()) == (
        UNSAID, ADD)


def test_a_video_made_from_an_image_shows_that_images_part_grayed_beside_its_own(action):
    image = _row("img", image=Labels(("alpha",), ("first box",)))

    action.show_row(_video(video=Labels(("delta",), ("third box",))), image)

    image_part = _setter(action, MediaType.IMAGE).parentWidget()
    assert (_listed(action, MediaType.IMAGE), image_part.isEnabled(),
            _box(action, MediaType.IMAGE, "first box").isChecked()) == ("alpha", False, True)
    assert (_listed(action, MediaType.VIDEO), _setter(action, MediaType.VIDEO).isHidden(),
            _box(action, MediaType.VIDEO, "third box").isChecked()) == ("delta", False, True)


def test_a_video_made_from_no_image_shows_its_own_image_part_live(action):
    action.show_row(_video(image=Labels(("alpha",))))

    image_part = _setter(action, MediaType.IMAGE).parentWidget()
    assert (_listed(action, MediaType.IMAGE), image_part.isEnabled(),
            _setter(action, MediaType.IMAGE).isHidden()) == ("alpha", True, False)


def test_its_image_button_opens_the_setter_tool_for_images_on_the_video(action, opened):
    action.show_row(_video("vid-seven"))

    _setter(action, MediaType.IMAGE).click()

    assert opened == [(MediaType.IMAGE, "vid-seven")]


def test_a_video_brought_in_shows_the_image_part_of_the_frame_taken_from_it(action, opened):
    frame = _row("frame", source=GenerationSource.STARTING_FRAME, image=Labels(("beta",)))

    action.show_row(_video("theirs", source=GenerationSource.OUTSIDE), frame)
    _setter(action, MediaType.IMAGE).click()

    assert (_listed(action, MediaType.IMAGE), opened) == ("beta", [(MediaType.IMAGE, "frame")])


def test_a_videos_button_opens_the_setter_tool_for_videos(action, opened):
    action.show_row(_video("vid-seven"))

    _setter(action, MediaType.VIDEO).click()

    assert opened == [(MediaType.VIDEO, "vid-seven")]


def test_a_tab_showing_nothing_shows_no_row(action):
    action.show_row(_video())
    action.clear()

    assert all(_setter(action, side).parentWidget().isHidden()
               for side in (MediaType.IMAGE, MediaType.VIDEO))


def test_an_images_row_is_actions_and_a_videos_rows_are_image_actions_and_video_actions(action):
    action.show_row(_row())
    on_an_image = _named(action, MediaType.IMAGE)
    action.show_row(_video())

    assert (on_an_image, _named(action, MediaType.IMAGE), _named(action, MediaType.VIDEO)) == (
        "Actions", "Image Actions", "Video Actions")


def test_the_actions_wrap_rather_than_being_cut_short(action):
    action.show_row(_row(image=Labels(("alpha",))))

    listed = _rows(action).findChild(QLabel, listed_actions(MediaType.IMAGE))
    assert listed.wordWrap()


def test_the_button_sits_on_a_line_of_its_own_under_the_actions(action):
    action.show_row(_row(image=Labels(("alpha",))))
    _rows(action).resize(600, 300)
    _rows(action).show()
    listed = _rows(action).findChild(QLabel, listed_actions(MediaType.IMAGE))
    setter = _setter(action, MediaType.IMAGE)
    part = setter.parentWidget()
    part.layout().activate()

    assert setter.mapTo(part, QPoint()).y() >= listed.mapTo(part, QPoint()).y() + listed.height()
