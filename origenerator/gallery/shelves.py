"""The five standing shelves of the table of contents, by key and by label.

Names rather than widgets: the tree draws a row for each of these, and the
spoken vocabulary matches an utterance against the same five, so neither owns
them. They live here, beside the folder keys, because a shelf key is an
identity a stored expansion and a navigation history are written under — it
outlives every widget that ever draws it, and a changed value would orphan
both.
"""
from __future__ import annotations

RECENTS_KEY = "__recents__"   # synthetic tree node listing recently generated items
RECENTS_LABEL = "Latest"      # its row label; a clock is drawn in the caret column.
# "Latest" rather than "Recents" because that is the word the players use
# for the same ordering — a Fun Time session's browse says Latest, and this
# shelf is that same newest-first listing of what the app has made.
STARRED_KEY = "__starred__"   # synthetic tree node collecting every starred folder
# Its row label: the same concept as a Fun Time player's favorites (the star
# there IS the favorite mark), so it wears that name.  The key stays
# "__starred__" so saved expansions and history survive the rename.
STARRED_LABEL = "Favorites"
EXPERIMENTS_KEY = "__experiments__"  # synthetic node: the background-experiment home
EXPERIMENTS_LABEL = "Experiments"    # its row label; a flask is drawn in the caret column
REQUESTS_KEY = "__requests__"  # synthetic node: what spoken requests have queued
REQUESTS_LABEL = "Requests"    # its row label; a mic is drawn in the caret column
TRASH_KEY = "__trash__"   # synthetic node: deleted items still held for recovery
TRASH_LABEL = "Trash"     # its row label; a can is drawn in the caret column
