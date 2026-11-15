from __future__ import annotations

from origenerator.gui.folder_switches import FolderSwitches


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


class _Db:
    def __init__(self):
        self.saved: list = []

    def set_folder_favorite(self, key, favorite, *, after_id=None):
        self.saved.append(("favorite", key, favorite, after_id))

    def set_folder_enhance(self, key, *, after_id=None):
        self.saved.append(("enhance", key, after_id))


class _Enhance:
    def enhance_what_awaits(self, rows):
        pass


def _switches():
    host, db = _Host(), _Db()
    return FolderSwitches(host, db, _Enhance()), host, db


def test_favoriting_a_folder_saves_it_and_writes_its_record_from_the_newest_item_on():
    switches, host, db = _switches()

    assert switches.set_favorite("leaf", True) is True

    assert db.saved == [("favorite", "leaf", True, 41)]
    assert host.meta["leaf"] == {"custom_name": None, "starred": True, "favorite_after_id": 41}


def test_a_folder_already_favorited_is_left_as_it_is():
    switches, _host, db = _switches()
    switches.set_favorite("leaf", True)

    assert switches.set_favorite("leaf", True) is False
    assert len(db.saved) == 1


def test_unfavoriting_keeps_the_rest_of_the_folders_record():
    switches, host, db = _switches()
    switches.set_enhancing("leaf", True)
    switches.set_favorite("leaf", True)

    switches.set_favorite("leaf", False)

    assert host.meta["leaf"] == {"custom_name": None, "starred": False,
                                 "enhance_after_id": 41, "favorite_after_id": None}
    assert db.saved[-1] == ("favorite", "leaf", False, None)
