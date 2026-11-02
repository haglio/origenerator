"""The collections every folder of folders leads with, by key and by label.

Names rather than widgets: the tree draws a row for each of these under every
such folder, and the spoken vocabulary matches an utterance against their
names, so neither owns them. They live here, beside the folder keys, because a
collection key is an identity a stored expansion and a navigation history are
written under — it outlives every widget that ever draws it, and a changed
value would orphan both.
"""
from __future__ import annotations

from typing import NamedTuple

from origenerator.gallery.tree import ALL_KEY

LATEST_KEY = "__recents__"   # synthetic tree node listing recently generated items
LATEST_LABEL = "Latest"
# "Latest" rather than "Latest" because that is the word the Funestras use
# for the same ordering — a Fun Time session's browse says Latest, and this
# collection is that same newest-first listing of what the app has made.
FAVORITES_KEY = "__starred__"   # synthetic tree node collecting every favorited folder
# Its row label: the same concept as a Fun Time Funestra's favorites (the star
# there IS the favorite mark), so it wears that name.  The key stays
# "__starred__" so saved expansions and history survive the rename.
FAVORITES_LABEL = "Favorites"
ENHANCED_KEY = "__enhanced__"   # synthetic node: every enhanced image under its folder
ENHANCED_LABEL = "Enhanced"
EXPERIMENTS_KEY = "__experiments__"  # synthetic node: the background-experiment home
EXPERIMENTS_LABEL = "Experiments"
TRASH_KEY = "__trash__"   # synthetic node: deleted items still held in the Trash
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
