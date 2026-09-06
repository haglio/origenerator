"""Dragging a prompt field taller, and the height it keeps afterwards."""

import pytest
from PyQt6.QtCore import QPoint, Qt

from origenerator.gui.prompt_field import (
    DEFAULT_HEIGHT,
    MAX_HEIGHT,
    PROMPT_HEIGHTS,
    PromptField,
)


@pytest.fixture(autouse=True)
def _forget_dragged_heights():
    """Start and end each test with no remembered heights.

    They are app-wide by design — one number per param for the whole process —
    so without this one test's drag would set the next one's starting size.
    """
    PROMPT_HEIGHTS.restore({})
    yield
    PROMPT_HEIGHTS.restore({})


def _field(qtbot, key="positive_prompt"):
    field = PromptField(key)
    qtbot.addWidget(field)
    field.resize(300, field.height())
    field.show()
    qtbot.waitExposed(field)
    return field


def _drag_edge(qtbot, field, dy):
    """Grab the field's lower edge and pull it ``dy`` pixels down (up, if negative)."""
    grab = QPoint(field.viewport().width() // 2, field.viewport().height() - 1)
    drop = grab + QPoint(0, dy)
    qtbot.mousePress(field.viewport(), Qt.MouseButton.LeftButton, pos=grab)
    qtbot.mouseMove(field.viewport(), drop)
    qtbot.mouseRelease(field.viewport(), Qt.MouseButton.LeftButton, pos=drop)


def test_a_fresh_prompt_field_is_the_familiar_height(qtbot):
    # Nothing dragged yet: the size prompts have always been, so the form looks
    # the same until the user asks for something else.
    assert _field(qtbot).height() == DEFAULT_HEIGHT


def test_dragging_the_lower_edge_makes_the_field_taller(qtbot):
    field = _field(qtbot)
    _drag_edge(qtbot, field, 80)
    assert field.height() == DEFAULT_HEIGHT + 80


def test_dragging_the_lower_edge_up_makes_it_shorter(qtbot):
    field = _field(qtbot)
    _drag_edge(qtbot, field, -40)
    assert field.height() == DEFAULT_HEIGHT - 40


def test_a_drag_far_up_stops_at_one_readable_line(qtbot):
    # The handle can't be dragged into nothing: a field you can't read a line of
    # is a field you can no longer find the handle on either.
    field = _field(qtbot)
    _drag_edge(qtbot, field, -500)
    assert field.height() < DEFAULT_HEIGHT           # it did shrink
    assert field.height() >= field.fontMetrics().lineSpacing()
    assert field.viewport().height() >= field.fontMetrics().lineSpacing()


def test_a_runaway_drag_stops_at_the_cap(qtbot):
    field = _field(qtbot)
    _drag_edge(qtbot, field, 9000)
    assert field.height() == MAX_HEIGHT


def test_pressing_in_the_middle_types_rather_than_resizes(qtbot):
    # Only the lower edge is a handle; the rest of the field is for writing in.
    field = _field(qtbot)
    field.setPlainText("a fox in snow")
    middle = QPoint(field.viewport().width() // 2, field.viewport().height() // 2)
    qtbot.mousePress(field.viewport(), Qt.MouseButton.LeftButton, pos=middle)
    qtbot.mouseMove(field.viewport(), middle + QPoint(0, 60))
    qtbot.mouseRelease(field.viewport(), Qt.MouseButton.LeftButton, pos=middle + QPoint(0, 60))
    assert field.height() == DEFAULT_HEIGHT


def test_the_height_sticks_to_the_param_not_the_widget(qtbot):
    # The form is rebuilt on every workflow switch and every new tab, so a height
    # that lived on the widget would be gone by the next click.
    field = _field(qtbot)
    _drag_edge(qtbot, field, 70)

    assert PromptField("positive_prompt").height() == DEFAULT_HEIGHT + 70
    # …and only that param's: the short negative prompt isn't dragged open too.
    assert PromptField("negative_prompt").height() == DEFAULT_HEIGHT


def test_fields_already_open_follow_the_drag(qtbot):
    # Two tabs showing the same prompt: dragging one and finding the other still
    # small would make "this field is this tall" untrue the moment you switch tabs.
    dragged = _field(qtbot)
    other = _field(qtbot)
    _drag_edge(qtbot, dragged, 50)
    assert other.height() == DEFAULT_HEIGHT + 50


def test_dragged_heights_survive_a_snapshot_and_restore(qtbot):
    field = _field(qtbot)
    _drag_edge(qtbot, field, 90)
    saved = PROMPT_HEIGHTS.snapshot()

    PROMPT_HEIGHTS.restore({})                     # a fresh process, nothing dragged
    assert field.height() == DEFAULT_HEIGHT
    PROMPT_HEIGHTS.restore(saved)                  # the session state, reloaded
    assert field.height() == DEFAULT_HEIGHT + 90
    assert PromptField("positive_prompt").height() == DEFAULT_HEIGHT + 90


@pytest.mark.parametrize("stored", [None, "300", {"positive_prompt": "tall"},
                                    {"positive_prompt": True}, [100]])
def test_a_corrupt_stored_height_opens_at_the_default(qtbot, stored):
    # ui_state.json is hand-editable and outlives any one version of this app; a
    # value that isn't a height must cost the default, not the launch.
    PROMPT_HEIGHTS.restore(stored)
    assert _field(qtbot).height() == DEFAULT_HEIGHT
