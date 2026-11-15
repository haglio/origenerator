from __future__ import annotations

import pytest
from PySide6.QtCore import QSize

from origenerator.gallery import collection as collections
from origenerator.gallery.collection import Collection, Glyph, Voice
from origenerator.gallery.shapes import LANDSCAPE
from origenerator.gui import folder_icons
from origenerator.gui.folder_tree import DROP_KEY_ROLE
from origenerator.gui.item_tile import ItemTile
from origenerator.library_views import LibrarySnapshot
from origenerator.reference import reference_sections
from origenerator.voice.app_commands import GoToCollection, say_collections
from origenerator.voice.commands import CollectionCommand, match_voice_command, spoken_phrases
from tests.test_gallery_pane import _pane
from tests.test_gallery_pane import _row as _pane_row
from tests.test_gallery_tree import _children, _image, _table_of_contents

_SHORTLIST_KEY = "__shortlist__"
_SHORTLIST = Collection(
    _SHORTLIST_KEY, "Shortlist", "Items kept for a second look", Glyph("flask", "BLUE"),
    rows=lambda library: [row for row in library.rows if row.get("shortlisted")],
    marked=True, gathers_folders=True, empty="Nothing on the shortlist yet.",
    voice=Voice(("shortlist",)))


@pytest.fixture
def a_new_collection(monkeypatch):
    monkeypatch.setattr(collections, "ALL_COLLECTIONS",
                        (*collections.ALL_COLLECTIONS, _SHORTLIST))
    folder_icons.collection_icon.cache_clear()
    yield _SHORTLIST
    folder_icons.collection_icon.cache_clear()


def test_a_new_collection_is_a_row_of_the_toc_with_its_name_tip_icon_and_drop(
        qtbot, a_new_collection):
    half = _table_of_contents(qtbot, [_image("i1", "a cat")])
    (all_row,) = [half.topLevelItem(i) for i in range(half.topLevelItemCount())]
    (row,) = [row for row in _children(all_row) if row.text(0) == "Shortlist"]
    size = QSize(48, 48)

    assert row.toolTip(0) == "Items kept for a second look"
    assert (row.icon(0).pixmap(size).toImage()
            == folder_icons.collection_icon(_SHORTLIST_KEY).pixmap(size).toImage())
    assert row.data(0, DROP_KEY_ROLE) == _SHORTLIST_KEY
    assert folder_icons.collection_mark(_SHORTLIST_KEY)[0] == "flask"
    assert folder_icons.collection_kind_icon(_SHORTLIST_KEY)[1] == "Shortlist"


def test_a_new_collection_is_gathered_counted_and_drawn_by_the_gallery(
        qtbot, db, a_new_collection):
    kept = {**_pane_row("a", 1), "shortlisted": True}
    pane, scroll = _pane(qtbot, db)
    pane.set_model(LibrarySnapshot([kept, _pane_row("b", 2)]))

    assert [row["prompt_id"] for row in pane.rows_for_collection(_SHORTLIST_KEY)] == ["a"]
    assert pane.collection_counts(LANDSCAPE)[_SHORTLIST_KEY] == 1
    pane.show_collection(_SHORTLIST_KEY)
    assert len(scroll.widget().findChildren(ItemTile)) == 1

    pane.set_model(LibrarySnapshot([_pane_row("b", 2)]))
    pane.show_collection(_SHORTLIST_KEY)
    assert scroll.widget().text() == "Nothing on the shortlist yet."


def test_a_new_collection_answers_to_its_spoken_names(a_new_collection):
    said: dict = {}
    say_collections([a_new_collection], said)

    assert said == {phrase: GoToCollection(_SHORTLIST_KEY) for phrase in (
        "shortlist", "shortlist collection", "go to shortlist", "open shortlist",
        "show shortlist")}
    assert match_voice_command("shortlist") == CollectionCommand(_SHORTLIST_KEY)
    assert "shortlist" in spoken_phrases()


def test_a_new_spoken_collection_is_listed_with_the_others_in_the_reference(
        monkeypatch, a_new_collection):
    said = {GoToCollection(_SHORTLIST_KEY): ("shortlist",)}
    monkeypatch.setattr("origenerator.reference.said_as",
                        lambda command: said.get(command, ()))

    (core, *_rest) = reference_sections()
    (collections_group,) = [group for group in core.groups if group.title == "Collections"]

    assert [row.description for row in collections_group.rows][-1] == "Shortlist"

