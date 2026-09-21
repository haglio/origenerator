"""The search field's placeholder, which says where a query would search.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

from PyQt6.QtGui import QResizeEvent

from origenerator.gui.scope_search_edit import ScopeSearchEdit

# A path wide enough that no field in these tests can hold all of it.
LONG = "Library / Pictures / Alpha Recipe / One Two Three / Four Five Six Seven Eight"


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
    assert field.placeholderText() == "Search Library / Alpha…"


def test_a_path_too_long_for_the_field_keeps_its_tail(qtbot):
    """The tail is the folder itself and its nearest parents, which is the half
    that answers "search where?" -- a folder's own code says nothing alone."""
    field = _field(qtbot, 200)
    field.set_scope(LONG)
    shown = field.placeholderText()
    assert shown != f"Search {LONG}…"
    kept = shown.removeprefix("Search ").lstrip("…")
    assert kept and LONG.endswith(kept)


def test_an_elided_path_drops_the_invitation_so_there_is_only_one_ellipsis(qtbot):
    field = _field(qtbot, 200)
    field.set_scope(LONG)
    assert field.placeholderText().count("…") == 1


def test_a_wider_field_shows_more_of_the_path(qtbot):
    narrow = _field(qtbot, 150)
    narrow.set_scope(LONG)
    wide = _field(qtbot, 500)
    wide.set_scope(LONG)
    assert len(wide.placeholderText()) > len(narrow.placeholderText())


def test_growing_the_field_re_renders_what_it_can_now_hold(qtbot):
    """The handler is called rather than waited for: a resize is delivered when
    Qt next runs its loop, and a test that spun one would be timing-dependent."""
    field = _field(qtbot, 150)
    field.set_scope(LONG)
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
