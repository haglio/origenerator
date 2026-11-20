from __future__ import annotations

from origenerator.gallery import ALL_KEY
from origenerator.gallery.collection import (
    ALL_ITEMS_KEY,
    TRASH_KEY,
    FolderCollection,
    folder_collection,
)


def test_a_folders_collection_is_read_back_off_its_key():
    collection = FolderCollection(TRASH_KEY, "image/sdxl_t2i")

    assert folder_collection(collection.key) == collection


def test_alls_collections_keep_the_keys_the_collections_had_before_they_moved_under_it():
    assert FolderCollection(ALL_ITEMS_KEY, ALL_KEY).key == ALL_ITEMS_KEY
    assert folder_collection(ALL_ITEMS_KEY) == FolderCollection(ALL_ITEMS_KEY, ALL_KEY)
