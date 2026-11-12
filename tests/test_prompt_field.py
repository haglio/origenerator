from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QLabel, QWidget

from origenerator.gui.prompt_boxes import set_in_use
from origenerator.gui.prompt_field import (
    DEFAULT_HEIGHT,
    MAX_HEIGHT,
    PROMPT_HEIGHTS,
    PromptField,
    PromptHeights,
)


@pytest.fixture(autouse=True)
def _forget_dragged_heights():
    PROMPT_HEIGHTS.restore({})
    yield
    PROMPT_HEIGHTS.restore({})


def _field(qtbot, key="positive_prompt"):
    field = PromptField(key)
    qtbot.addWidget(field)
    field.resize(300, field.height())
    with qtbot.waitExposed(field):
        field.show()
    return field


def _drag_edge(qtbot, field, dy):
    grab = QPoint(field.viewport().width() // 2, field.viewport().height() - 1)
    drop = grab + QPoint(0, dy)
    qtbot.mousePress(field.viewport(), Qt.MouseButton.LeftButton, pos=grab)
    qtbot.mouseMove(field.viewport(), drop)
    qtbot.mouseRelease(field.viewport(), Qt.MouseButton.LeftButton, pos=drop)


def test_a_fresh_prompt_field_is_the_familiar_height(qtbot):
    assert _field(qtbot).height() == DEFAULT_HEIGHT


def test_dragging_the_lower_edge_makes_the_field_taller(qtbot):
    field = _field(qtbot)
    _drag_edge(qtbot, field, 80)
    assert field.height() == DEFAULT_HEIGHT + 80


def test_a_field_that_moves_under_the_pointer_mid_drag_still_follows_the_pointer(qtbot):
    holder = QWidget()
    qtbot.addWidget(holder)
    holder.resize(400, 600)
    field = PromptField("positive_prompt", holder)
    field.resize(300, field.height())
    with qtbot.waitExposed(holder):
        holder.show()
    grab = QPoint(field.viewport().width() // 2, field.viewport().height() - 1)
    qtbot.mousePress(field.viewport(), Qt.MouseButton.LeftButton, pos=grab)

    field.move(0, 50)
    drop = grab + QPoint(0, 80 - 50)
    qtbot.mouseMove(field.viewport(), drop)
    qtbot.mouseRelease(field.viewport(), Qt.MouseButton.LeftButton, pos=drop)

    assert field.height() == DEFAULT_HEIGHT + 80, (
        "the field moves under the pointer as it grows, so a drag measured in its own "
        "coordinates shifts mid-drag")


def test_dragging_the_lower_edge_up_makes_it_shorter(qtbot):
    field = _field(qtbot)
    _drag_edge(qtbot, field, -40)
    assert field.height() == DEFAULT_HEIGHT - 40


def test_a_drag_far_up_stops_at_one_readable_line(qtbot):
    field = _field(qtbot)
    _drag_edge(qtbot, field, -500)
    assert field.height() < DEFAULT_HEIGHT
    assert field.height() >= field.fontMetrics().lineSpacing()
    assert field.viewport().height() >= field.fontMetrics().lineSpacing()


def test_a_runaway_drag_stops_at_the_cap(qtbot):
    field = _field(qtbot)
    _drag_edge(qtbot, field, 9000)
    assert field.height() == MAX_HEIGHT


def test_pressing_in_the_middle_types_rather_than_resizes(qtbot):
    field = _field(qtbot)
    field.setPlainText("a fox in snow")
    middle = QPoint(field.viewport().width() // 2, field.viewport().height() // 2)
    qtbot.mousePress(field.viewport(), Qt.MouseButton.LeftButton, pos=middle)
    qtbot.mouseMove(field.viewport(), middle + QPoint(0, 60))
    qtbot.mouseRelease(field.viewport(), Qt.MouseButton.LeftButton, pos=middle + QPoint(0, 60))
    assert field.height() == DEFAULT_HEIGHT


def test_the_height_sticks_to_the_param_not_the_widget(qtbot):
    field = _field(qtbot)
    _drag_edge(qtbot, field, 70)

    assert PromptField("positive_prompt").height() == DEFAULT_HEIGHT + 70
    assert PromptField("negative_prompt").height() == DEFAULT_HEIGHT


def test_fields_already_open_follow_the_drag(qtbot):
    dragged = _field(qtbot)
    other = _field(qtbot)
    _drag_edge(qtbot, dragged, 50)
    assert other.height() == DEFAULT_HEIGHT + 50


def test_dragged_heights_survive_a_snapshot_and_restore(qtbot):
    field = _field(qtbot)
    _drag_edge(qtbot, field, 90)
    saved = PROMPT_HEIGHTS.snapshot()

    PROMPT_HEIGHTS.restore({})
    assert field.height() == DEFAULT_HEIGHT
    PROMPT_HEIGHTS.restore(saved)
    assert field.height() == DEFAULT_HEIGHT + 90
    assert PromptField("positive_prompt").height() == DEFAULT_HEIGHT + 90


@pytest.mark.parametrize("stored", [None, "300", {"positive_prompt": "tall"},
                                    {"positive_prompt": True}, [100]])
def test_a_corrupt_stored_height_opens_at_the_default(qtbot, stored):
    PROMPT_HEIGHTS.restore(stored)
    assert _field(qtbot).height() == DEFAULT_HEIGHT


def test_a_field_built_with_its_own_heights_keeps_to_them(qtbot):
    mine = PromptHeights()
    mine.set_height("positive_prompt", 260)

    field = PromptField("positive_prompt", heights=mine)
    qtbot.addWidget(field)

    assert field.height() == 260
    assert PROMPT_HEIGHTS.height("positive_prompt") == DEFAULT_HEIGHT


def test_a_drag_is_filed_in_the_set_the_field_was_given(qtbot):
    mine = PromptHeights()
    field = PromptField("negative_prompt", heights=mine)
    qtbot.addWidget(field)

    field._apply_height(240)
    field._drag = (0.0, 240)
    field.mouseReleaseEvent(QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(0, 0), QPointF(0, 0),
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))

    assert mine.height("negative_prompt") == 240
    assert PROMPT_HEIGHTS.height("negative_prompt") == DEFAULT_HEIGHT


def test_a_prompt_given_no_reason_is_never_grayed_out(qtbot):
    field, label = PromptField("negative_prompt"), QLabel("Negative Prompt")
    for widget in (field, label):
        qtbot.addWidget(widget)

    set_in_use(field, label, "", "What to keep out of the image.")

    assert (field.property("inert"), label.property("inert")) == (False, False)
    assert not field.isReadOnly()
    assert field.toolTip() == label.toolTip() == "What to keep out of the image."


def test_pressing_the_lower_edge_leaves_the_text_cursor_where_it_was(qtbot):
    field = _field(qtbot)
    field.setPlainText("one\ntwo")
    cursor = field.textCursor()
    cursor.setPosition(0)
    field.setTextCursor(cursor)
    grab = QPoint(field.viewport().width() // 2, field.viewport().height() - 1)

    qtbot.mousePress(field.viewport(), Qt.MouseButton.LeftButton, pos=grab)
    qtbot.mouseRelease(field.viewport(), Qt.MouseButton.LeftButton, pos=grab)

    assert field.textCursor().position() == 0
