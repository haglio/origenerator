from __future__ import annotations

from origenerator.gallery import ALL_KEY
from origenerator.gallery.shelves import RECENTS_KEY, TRASH_KEY, FolderShelf, folder_shelf


def test_a_folders_shelf_is_read_back_off_its_key():
    shelf = FolderShelf(TRASH_KEY, "image/sdxl_t2i")

    assert folder_shelf(shelf.key) == shelf


def test_alls_shelves_keep_the_keys_the_shelves_had_before_they_moved_under_it():
    assert FolderShelf(RECENTS_KEY, ALL_KEY).key == RECENTS_KEY
    assert folder_shelf(RECENTS_KEY) == FolderShelf(RECENTS_KEY, ALL_KEY)
