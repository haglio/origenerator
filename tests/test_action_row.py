from __future__ import annotations

import json

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QToolButton,
    QWidget,
)
from shared_ui.colors import TEXT_SECONDARY
from shared_ui.tick_control import TickControl

from origenerator.action_labels import Labels, stored
from origenerator.generation_state import GenerationSource
from origenerator.gui.action_row import (
    ADD,
    EDIT,
    ActionRow,
    action_checkbox,
    action_pills,
    adding_button,
    setter_button,
)
from origenerator.gui.label_cells import LabelForm
from origenerator.gui.pills import Pill
from origenerator.gui.stylesheet import build_stylesheet
from origenerator.media import MediaType

_BOXES = {MediaType.IMAGE: ("first box", "second box"), MediaType.VIDEO: ("third box",)}
_ACTIONS = {MediaType.IMAGE: ("alpha", "beta", "gamma"), MediaType.VIDEO: ("alpha", "delta")}


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

    def open_setter(side, first="", heard=None, host=None):
        opened.append((side, first))
        window = QWidget()
        qtbot.addWidget(window)
        window.heard = heard
        window.host = host
        return window

    return ActionRow(LabelForm(host), checkboxes=_BOXES, actions=_ACTIONS, open_setter=open_setter)


def _rows(action):
    return action.form().parentWidget()


def _pill_row(action, side) -> QWidget:
    return _rows(action).findChild(QWidget, action_pills(side))


def _pills(action, side) -> list[Pill]:
    return _pill_row(action, side).findChildren(Pill, options=Qt.FindChildOption.FindDirectChildrenOnly)


def _listed(action, side) -> tuple[str, ...]:
    return tuple(pill.text() for pill in _pills(action, side))


def _has_an_x(pill: Pill) -> bool:
    return pill.findChild(QToolButton) is not None


def _adder(action, side) -> QAbstractButton:
    return _rows(action).findChild(QAbstractButton, adding_button(side))


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

    assert (_listed(action, MediaType.IMAGE), action.findChildren(QComboBox)) == (("alpha", "beta"), [])


def test_an_image_with_no_actions_shows_no_pills_and_offers_to_add_them(action):
    action.show_row(_row())

    assert (_listed(action, MediaType.IMAGE), _setter(action, MediaType.IMAGE).text()) == ((), ADD)
    assert ADD == "Add with setter tool…"


def test_an_image_with_actions_offers_to_edit_them(action):
    action.show_row(_row(image=Labels(("alpha",))))

    assert _setter(action, MediaType.IMAGE).text() == EDIT == "Edit with setter tool…"


def _top_left(widget: QWidget, within: QWidget) -> QPoint:
    return widget.mapTo(within, QPoint())


def test_an_image_shows_its_checkboxes_as_it_saved_them_before_its_pills_on_one_line(action, qtbot):
    action.show_row(_row(image=Labels(("alpha",), ("second box",))))
    host = _rows(action)
    host.resize(900, 200)
    with qtbot.waitExposed(host):
        host.show()
    pills = _pill_row(action, MediaType.IMAGE)
    boxes = [_box(action, MediaType.IMAGE, name) for name in _BOXES[MediaType.IMAGE]]

    assert [box.isChecked() for box in boxes] == [False, True]
    assert all(_top_left(box, host).x() + box.width() <= _top_left(pills, host).x()
               and _top_left(box, host).y() < _top_left(pills, host).y() + pills.height()
               for box in boxes)


def test_a_videos_checkbox_stands_before_its_pills_too(action, qtbot):
    action.show_row(_video("vid", video=Labels(("delta",), ("third box",))))
    host = _rows(action)
    host.resize(900, 300)
    with qtbot.waitExposed(host):
        host.show()
    box = _box(action, MediaType.VIDEO, "third box")
    pills = _pill_row(action, MediaType.VIDEO)

    assert box.isChecked()
    assert _top_left(box, host).x() + box.width() <= _top_left(pills, host).x()


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


def test_the_setter_tool_opened_is_given_the_trash_and_the_ears_the_app_handed_the_row(action):
    host = object()
    action.set_setter_host(host)
    action.show_row(_row("img-seven"))

    _setter(action, MediaType.IMAGE).click()

    assert action._windows[MediaType.IMAGE].host is host


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
                       open_setter=lambda side, first="", heard=None, host=None: "nothing waiting")
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
            _box(action, MediaType.IMAGE, "first box").isChecked()) == (("gamma",), EDIT, True)


def test_an_answer_taken_back_in_the_setter_tool_shows_the_item_unlabeled_again(action):
    action.show_row(_row("img-seven", image=Labels(("alpha",))))
    _setter(action, MediaType.IMAGE).click()

    action._windows[MediaType.IMAGE].heard("img-seven", MediaType.IMAGE, None)

    assert (_listed(action, MediaType.IMAGE), _setter(action, MediaType.IMAGE).text()) == ((), ADD)


def test_a_video_made_from_an_image_shows_that_images_part_grayed_beside_its_own(action):
    image = _row("img", image=Labels(("alpha",), ("first box",)))

    action.show_row(_video(video=Labels(("delta",), ("third box",))), image)

    image_part = _setter(action, MediaType.IMAGE).parentWidget()
    assert (_listed(action, MediaType.IMAGE), image_part.isEnabled(),
            _box(action, MediaType.IMAGE, "first box").isChecked()) == (("alpha",), False, True)
    assert (_listed(action, MediaType.VIDEO), _setter(action, MediaType.VIDEO).isHidden(),
            _box(action, MediaType.VIDEO, "third box").isChecked()) == (("delta",), False, True)


def test_a_video_made_from_an_image_offers_no_setter_tool_for_that_images_actions(action):
    action.show_row(_video(), _row("img", image=Labels(("alpha",))))

    assert _setter(action, MediaType.IMAGE).isHidden()


def test_a_video_made_from_an_image_shows_its_pills_grayed_with_nothing_to_remove_or_add(action):
    action.show_row(_video(), _row("img", image=Labels(("alpha",))))

    pills = _pills(action, MediaType.IMAGE)
    assert ([pill.isEnabled() for pill in pills], [_has_an_x(pill) for pill in pills],
            _adder(action, MediaType.IMAGE).isHidden()) == ([False], [False], True)


def test_the_next_image_after_a_video_made_from_one_offers_its_setter_tool_and_pills_again(action):
    action.show_row(_video(), _row("img", image=Labels(("alpha",))))
    action.show_row(_row("other", image=Labels(("alpha",))))

    assert (_setter(action, MediaType.IMAGE).isHidden(),
            [_has_an_x(pill) for pill in _pills(action, MediaType.IMAGE)],
            _adder(action, MediaType.IMAGE).isHidden()) == (False, [True], False)


def test_a_video_made_from_no_image_shows_its_own_image_part_live(action):
    action.show_row(_video(image=Labels(("alpha",))))

    image_part = _setter(action, MediaType.IMAGE).parentWidget()
    assert (_listed(action, MediaType.IMAGE), image_part.isEnabled(),
            _setter(action, MediaType.IMAGE).isHidden()) == (("alpha",), True, False)


def test_its_image_button_opens_the_setter_tool_for_images_on_the_video(action, opened):
    action.show_row(_video("vid-seven"))

    _setter(action, MediaType.IMAGE).click()

    assert opened == [(MediaType.IMAGE, "vid-seven")]


def test_a_video_brought_in_shows_the_image_part_of_the_frame_taken_from_it(action, opened):
    frame = _row("frame", source=GenerationSource.STARTING_FRAME, image=Labels(("beta",)))

    action.show_row(_video("theirs", source=GenerationSource.OUTSIDE), frame)
    _setter(action, MediaType.IMAGE).click()

    assert (_listed(action, MediaType.IMAGE), opened) == (("beta",), [(MediaType.IMAGE, "frame")])


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


def test_the_pills_wrap_onto_more_lines_rather_than_being_cut_short(action, qtbot):
    many = tuple(f"made up action number {n}" for n in range(8))
    action.show_row(_row(image=Labels(many)))
    host = _rows(action)
    host.resize(10, 400)
    with qtbot.waitExposed(host):
        host.show()
    host.layout().activate()
    row = _pill_row(action, MediaType.IMAGE)

    tops = [pill.mapTo(row, QPoint()).y() for pill in _pills(action, MediaType.IMAGE)]
    assert tops == sorted(tops)
    assert tops[0] < tops[-1]
    assert all(pill.width() >= pill.sizeHint().width() for pill in _pills(action, MediaType.IMAGE))


def test_the_button_sits_on_a_line_of_its_own_under_the_checkboxes_and_the_actions(action):
    action.show_row(_row(image=Labels(("alpha",))))
    _rows(action).resize(600, 300)
    _rows(action).show()
    listed = _pill_row(action, MediaType.IMAGE)
    setter = _setter(action, MediaType.IMAGE)
    part = setter.parentWidget()
    part.layout().activate()
    above = [listed, *(_box(action, MediaType.IMAGE, name) for name in _BOXES[MediaType.IMAGE])]

    assert all(_top_left(setter, part).y() >= _top_left(each, part).y() + each.height()
               for each in above)


def test_each_action_is_a_pill_with_an_x_that_removes_it_and_saves_at_once(action, qtbot):
    action.show_row(_row(image=Labels(("alpha", "beta"), ("first box",))))
    alpha = _pills(action, MediaType.IMAGE)[0]

    with qtbot.waitSignal(action.changed) as caught:
        alpha.findChild(QToolButton).click()

    assert caught.args == ["img", MediaType.IMAGE, Labels(("beta",), ("first box",))]
    assert _listed(action, MediaType.IMAGE) == ("beta",)


def _inked(drawn) -> int:
    shot = drawn.toImage()
    return sum(shot.pixelColor(x, y).lightness() >= TEXT_SECONDARY.lightness() - 40
               and shot.pixelColor(x, y).alpha() > 128
               for x in range(shot.width()) for y in range(shot.height()))


def _drawn_whole(button: QAbstractButton) -> bool:
    icon = button.icon().pixmap(button.iconSize())
    return _inked(button.grab()) >= _inked(icon) * 3 // 4


def test_each_pills_x_and_the_plus_are_drawn_whole_under_the_apps_own_look(action, qtbot):
    _rows(action).setStyleSheet(build_stylesheet())
    action.show_row(_row(image=Labels(("alpha",))))
    with qtbot.waitExposed(_rows(action)):
        _rows(action).show()

    x = _pills(action, MediaType.IMAGE)[0].findChild(QToolButton)

    assert (_drawn_whole(x), _drawn_whole(_adder(action, MediaType.IMAGE))) == (True, True)


def test_removing_the_last_pill_turns_the_button_back_to_add(action):
    action.show_row(_row(image=Labels(("alpha",))))

    _pills(action, MediaType.IMAGE)[0].findChild(QToolButton).click()

    assert (_listed(action, MediaType.IMAGE), _setter(action, MediaType.IMAGE).text()) == ((), ADD)


def _offered(action, side) -> list[Pill]:
    return [pill for pill in _rows(action).findChildren(Pill) if pill.isVisible()
            and pill.parentWidget() is not _pill_row(action, side)]


def test_the_plus_offers_the_sides_other_plain_actions_as_pills(action, qtbot):
    action.show_row(_row(image=Labels(("beta",))))
    _rows(action).show()

    _adder(action, MediaType.IMAGE).click()

    offered = _offered(action, MediaType.IMAGE)
    assert ([pill.text() for pill in offered], [_has_an_x(pill) for pill in offered]) == (
        ["alpha", "gamma"], [False, False])


def test_picking_an_offered_pill_adds_it_and_saves_at_once(action, qtbot):
    action.show_row(_row(image=Labels(("beta",), ("second box",))))
    _rows(action).show()
    _adder(action, MediaType.IMAGE).click()
    gamma = next(pill for pill in _offered(action, MediaType.IMAGE) if pill.text() == "gamma")

    with qtbot.waitSignal(action.changed) as caught:
        qtbot.mouseClick(gamma, Qt.MouseButton.LeftButton)

    assert caught.args == ["img", MediaType.IMAGE, Labels(("beta", "gamma"), ("second box",))]
    assert (_listed(action, MediaType.IMAGE), _offered(action, MediaType.IMAGE)) == (
        ("beta", "gamma"), [])


def test_the_first_action_picked_turns_the_button_to_edit(action, qtbot):
    action.show_row(_video("vid"))
    _rows(action).show()
    _adder(action, MediaType.VIDEO).click()
    delta = next(pill for pill in _offered(action, MediaType.VIDEO) if pill.text() == "delta")

    qtbot.mouseClick(delta, Qt.MouseButton.LeftButton)

    assert (_listed(action, MediaType.VIDEO), _setter(action, MediaType.VIDEO).text()) == (
        ("delta",), EDIT)


def test_the_plus_is_gone_once_every_action_is_set(action):
    action.show_row(_row(image=Labels(("gamma", "alpha", "beta"))))

    assert _adder(action, MediaType.IMAGE).isHidden()
