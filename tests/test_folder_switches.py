from __future__ import annotations

from types import SimpleNamespace

from origenerator.gui.folder_switches import FolderSwitches
from tests.real_db import database_of


class _Screen:
    def __init__(self):
        self.starred: list = []

    def open_leaf_folder(self):
        return None

    def set_items_favorite(self, prompt_ids, favorite):
        self.starred.append((list(prompt_ids), favorite))


class _Library:
    def __init__(self):
        self.folder_meta: dict[str, dict] = {}
        self.reading = SimpleNamespace(highest_id=41)

    def leaf_folders(self):
        return {"leaf": [{"prompt_id": "a"}, {"prompt_id": "b", "starred": 1}]}


class _Enhance:
    def enhance_what_awaits(self, rows):
        pass


def _switches():
    library, db = _Library(), database_of()
    return FolderSwitches(_Screen(), db, _Enhance(), library=library), library, db


def test_favoriting_a_folder_saves_it_and_writes_its_record_from_the_newest_item_on():
    switches, library, db = _switches()

    assert switches.set_favorite("leaf", True) is True

    assert db.folder_meta_map()["leaf"] == {"custom_name": None, "starred": True,
                                            "favorite_after_id": 41, "enhance_after_id": None}
    assert library.folder_meta["leaf"] == {"custom_name": None, "starred": True, "favorite_after_id": 41}


def test_a_folder_already_favorited_is_left_as_it_is():
    switches, _library, db = _switches()
    switches.set_favorite("leaf", True)
    version = db.library_version()

    assert switches.set_favorite("leaf", True) is False
    assert db.library_version() == version


def test_unfavoriting_keeps_the_rest_of_the_folders_record():
    switches, library, db = _switches()
    switches.set_enhancing("leaf", True)
    switches.set_favorite("leaf", True)

    switches.set_favorite("leaf", False)

    assert library.folder_meta["leaf"] == {"custom_name": None, "starred": False,
                                 "enhance_after_id": 41, "favorite_after_id": None}
    assert db.folder_meta_map()["leaf"] == {"custom_name": None, "starred": False,
                                            "favorite_after_id": None, "enhance_after_id": 41}
