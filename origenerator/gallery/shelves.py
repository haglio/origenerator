"""The five shelves every folder of folders leads with, by key and by label.

Names rather than widgets: the tree draws a row for each of these under every
such folder, and the spoken vocabulary matches an utterance against the same
five, so neither owns them. They live here, beside the folder keys, because a shelf key is an
identity a stored expansion and a navigation history are written under — it
outlives every widget that ever draws it, and a changed value would orphan
both.
"""
from __future__ import annotations

from typing import NamedTuple

from origenerator.gallery.tree import ALL_KEY

RECENTS_KEY = "__recents__"   # synthetic tree node listing recently generated items
RECENTS_LABEL = "Latest"      # its row label; a clock is drawn in the caret column.
# "Latest" rather than "Recents" because that is the word the players use
# for the same ordering — a Fun Time session's browse says Latest, and this
# shelf is that same newest-first listing of what the app has made.
FAVORITES_KEY = "__starred__"   # synthetic tree node collecting every favorited folder
# Its row label: the same concept as a Fun Time player's favorites (the star
# there IS the favorite mark), so it wears that name.  The key stays
# "__starred__" so saved expansions and history survive the rename.
FAVORITES_LABEL = "Favorites"
EXPERIMENTS_KEY = "__experiments__"  # synthetic node: the background-experiment home
EXPERIMENTS_LABEL = "Experiments"    # its row label; a flask is drawn in the caret column
REQUESTS_KEY = "__requests__"  # synthetic node: what spoken requests have queued
REQUESTS_LABEL = "Requests"    # its row label; a mic is drawn in the caret column
TRASH_KEY = "__trash__"   # synthetic node: deleted items still held for recovery
TRASH_LABEL = "Trash"     # its row label; a can is drawn in the caret column

SHELVES = (RECENTS_KEY, FAVORITES_KEY, EXPERIMENTS_KEY, REQUESTS_KEY, TRASH_KEY)
SHELF_LABELS = {RECENTS_KEY: RECENTS_LABEL, FAVORITES_KEY: FAVORITES_LABEL,
                EXPERIMENTS_KEY: EXPERIMENTS_LABEL, REQUESTS_KEY: REQUESTS_LABEL,
                TRASH_KEY: TRASH_LABEL}
_IN_FOLDER = "@"


class FolderShelf(NamedTuple):
    shelf: str
    folder: str

    @property
    def key(self) -> str:
        return self.shelf if self.folder == ALL_KEY else f"{self.shelf}{_IN_FOLDER}{self.folder}"


def folder_shelf(key: str | None) -> FolderShelf | None:
    shelf, _, folder = (key or "").partition(_IN_FOLDER)
    return FolderShelf(shelf, folder or ALL_KEY) if shelf in SHELVES else None
