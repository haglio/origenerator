from __future__ import annotations

from typing import NamedTuple

from funestra.hud_title import LATEST_LABEL

from origenerator.gallery.tree import ALL_KEY

LATEST_KEY = "__recents__"
FAVORITES_KEY = "__starred__"
FAVORITES_LABEL = "Favorites"
ENHANCED_KEY = "__enhanced__"
ENHANCED_LABEL = "Enhanced"
EXPERIMENTS_KEY = "__experiments__"
EXPERIMENTS_LABEL = "Experiments"
TRASH_KEY = "__trash__"
TRASH_LABEL = "Trash"

COLLECTIONS = (LATEST_KEY, FAVORITES_KEY, ENHANCED_KEY, EXPERIMENTS_KEY, TRASH_KEY)
COLLECTION_LABELS = {LATEST_KEY: LATEST_LABEL, FAVORITES_KEY: FAVORITES_LABEL,
                     ENHANCED_KEY: ENHANCED_LABEL, EXPERIMENTS_KEY: EXPERIMENTS_LABEL,
                     TRASH_KEY: TRASH_LABEL}
_IN_FOLDER = "@"


class FolderCollection(NamedTuple):
    which: str
    folder: str

    @property
    def key(self) -> str:
        return self.which if self.folder == ALL_KEY else f"{self.which}{_IN_FOLDER}{self.folder}"


def folder_collection(key: str | None) -> FolderCollection | None:
    collection, _, folder = (key or "").partition(_IN_FOLDER)
    return FolderCollection(collection, folder or ALL_KEY) if collection in COLLECTIONS else None
