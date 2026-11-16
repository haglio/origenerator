from __future__ import annotations

from origenerator.gui.folder_switches import FolderSwitches
from tests.real_db import database_of


class _Host:
    def __init__(self):
        self.meta: dict[str, dict] = {}
        self.starred: list = []

    def open_leaf_folder(self):
        return None

    def leaf_folders(self):
        return {"leaf": [{"prompt_id": "a"}, {"prompt_id": "b", "starred": 1}]}

    def folder_meta(self):
        return self.meta

    def highest_id_listed(self):
        return 41

    def set_items_favorite(self, prompt_ids, favorite):
        self.starred.append((list(prompt_ids), favorite))


class _Enhance:
    def enhance_what_awaits(self, rows):
        pass


def _switches():
    host, db = _Host(), database_of()
    return FolderSwitches(host, db, _Enhance()), host, db


def test_favoriting_a_folder_saves_it_and_writes_its_record_from_the_newest_item_on():
    switches, host, db = _switches()

    assert switches.set_favorite("leaf", True) is True

    assert db.folder_meta_map()["leaf"] == {"custom_name": None, "starred": True,
                                            "favorite_after_id": 41, "enhance_after_id": None}
    assert host.meta["leaf"] == {"custom_name": None, "starred": True, "favorite_after_id": 41}


def test_a_folder_already_favorited_is_left_as_it_is():
    switches, _host, db = _switches()
    switches.set_favorite("leaf", True)
    version = db.library_version()

    assert switches.set_favorite("leaf", True) is False
    assert db.library_version() == version


def test_unfavoriting_keeps_the_rest_of_the_folders_record():
    switches, host, db = _switches()
    switches.set_enhancing("leaf", True)
    switches.set_favorite("leaf", True)

    switches.set_favorite("leaf", False)

    assert host.meta["leaf"] == {"custom_name": None, "starred": False,
                                 "enhance_after_id": 41, "favorite_after_id": None}
    assert db.folder_meta_map()["leaf"] == {"custom_name": None, "starred": False,
                                            "favorite_after_id": None, "enhance_after_id": 41}
