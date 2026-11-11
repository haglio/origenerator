from __future__ import annotations

from PyQt6.QtGui import QResizeEvent
from PyQt6.QtWidgets import QToolButton

from origenerator.gui.scope_search_edit import ScopeSearchEdit

LONGER_THAN_ANY_FIELD_HERE = "Library / Images / Alpha Folder / One Two Three / Four Five Six Seven Eight"


def _field(qtbot, width: int) -> ScopeSearchEdit:
    field = ScopeSearchEdit()
    qtbot.addWidget(field)
    field.resize(width, 24)
    return field


def test_a_field_with_no_folder_named_yet_just_invites_a_query(qtbot):
    assert _field(qtbot, 400).placeholderText() == "Search …"


def test_the_placeholder_names_the_whole_path_when_there_is_room_for_it(qtbot):
    field = _field(qtbot, 900)
    field.set_scope("Library / Alpha")
    assert field.placeholderText() == "Search Library / Alpha…", (
        "a folder is named by a short code, and a code alone says nothing of the branch it sits in")


def test_a_path_too_long_for_the_field_keeps_its_tail(qtbot):
    field = _field(qtbot, 200)
    field.set_scope(LONGER_THAN_ANY_FIELD_HERE)
    shown = field.placeholderText()
    assert shown != f"Search {LONGER_THAN_ANY_FIELD_HERE}…"
    kept = shown.removeprefix("Search ").lstrip("…")
    assert kept
    assert LONGER_THAN_ANY_FIELD_HERE.endswith(kept)


def test_an_elided_path_drops_the_invitation_so_there_is_only_one_ellipsis(qtbot):
    field = _field(qtbot, 200)
    field.set_scope(LONGER_THAN_ANY_FIELD_HERE)
    assert field.placeholderText().count("…") == 1


def test_a_wider_field_shows_more_of_the_path(qtbot):
    narrow = _field(qtbot, 150)
    narrow.set_scope(LONGER_THAN_ANY_FIELD_HERE)
    wide = _field(qtbot, 500)
    wide.set_scope(LONGER_THAN_ANY_FIELD_HERE)
    assert len(wide.placeholderText()) > len(narrow.placeholderText())


def test_growing_the_field_re_renders_what_it_can_now_hold(qtbot):
    field = _field(qtbot, 150)
    field.set_scope(LONGER_THAN_ANY_FIELD_HERE)
    narrow = field.placeholderText()
    was = field.size()
    field.resize(500, 24)
    field.resizeEvent(QResizeEvent(field.size(), was))
    assert len(field.placeholderText()) > len(narrow)


def test_naming_the_same_folder_again_leaves_the_placeholder_alone(qtbot):
    field = _field(qtbot, 400)
    field.set_scope("Library / Alpha")
    once = field.placeholderText()
    field.set_scope("Library / Alpha")
    assert field.placeholderText() == once


def _clear_button(field: ScopeSearchEdit) -> QToolButton:
    (button,) = [button for button in field.findChildren(QToolButton) if button.isVisibleTo(field)]
    return button


def _searching(qtbot) -> ScopeSearchEdit:
    field = _field(qtbot, 300)
    field.setClearButtonEnabled(True)
    with qtbot.waitExposed(field):
        field.show()
    field.setText("kitten " * 12)
    field.set_working(True)
    return field


def test_a_search_going_on_leaves_the_clear_button_where_it_was(qtbot):
    field = _field(qtbot, 300)
    field.setClearButtonEnabled(True)
    field.show()
    field.setText("kitten")
    before = _clear_button(field).geometry()

    field.set_working(True)

    assert _clear_button(field).geometry() == before


def test_the_working_circle_turns_just_left_of_the_clear_button(qtbot):
    field = _searching(qtbot)

    assert field._circle_box().right() <= _clear_button(field).geometry().left()


def test_typed_words_never_run_under_the_working_circle(qtbot):
    field = _searching(qtbot)

    field.end(False)
    field.repaint()

    assert field.cursorRect().right() <= field._circle_box().left()


def test_the_circle_turns_while_a_search_is_going(qtbot):
    field = _searching(qtbot)
    started_at = field._turned

    qtbot.waitUntil(lambda: field._turned != started_at)


def test_the_circle_goes_with_the_search_and_gives_the_words_their_room_back(qtbot):
    field = _searching(qtbot)

    field.set_working(False)

    assert not field.working()
    assert field.textMargins().right() == 0
