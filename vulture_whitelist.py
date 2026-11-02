"""Vulture whitelist — names the scan reports that are not dead code.

Handed to vulture as one more file to read, so a mention here counts as a use.
Nothing imports or runs it; `_` is the placeholder `--make-whitelist` writes for
"some object". Grouped by reason, so each entry can be checked against the thing
that actually calls it.

The family's dead-code gate fails on an entry that has stopped suppressing
anything, so nothing may stay here once its subject is gone.

Everything in it is now a caller vulture cannot follow -- Qt's C++ event loop,
sqlite3, COM, funestra, the tokenizers library, one string-dispatch table. The
section this file opened with, the 38 names the first scan reported and nobody
had yet judged, is empty: backlog item 24 read each one and either deleted it or
gave it a reader.
An entry added here from now on says which of those six it is, or it does not
belong.
"""
from __future__ import annotations

# --- Qt event handlers and layout hooks -- called by the C++ event loop, never from here ---
_.dragEnterEvent
_.dropEvent
_.contextMenuEvent
_.takeAt
_.expandingDirections
_.hasHeightForWidth
_.mouseDoubleClickEvent
_.startDrag
_.wheelEvent
_.highlightBlock

# --- Qt override signatures -- the framework passes the argument, so the parameter has to be there ---
supported_actions

# --- vulture: funestra's Funestra asks these of what runs on it, through its User protocol ---
_.apply_command
_.top_block
_.set_showing
_.own_frame

# --- vulture: reached by name, from the table a spoken word is dispatched through ---
# `voice_router._MOTION` maps the spoken on and off words for human inspired to
# "set_learned", which `_hold_the_motion` hands to getattr.
_.set_learned

# --- sqlite3 reads this off the connection it was set on ---
_.row_factory

# --- sqlite3 hands this back on rows nothing writes any more, which the listing keeps for every source the enum names ---
_.STROKE_TRIM

# --- vulture: the tokenizers library reads these off the Tokenizer they were set on, in its own Rust code ---
_.normalizer
_.pre_tokenizer

# --- style-option fields written for Qt's painter to read, never read back here ---
_.textVisible  # origenerator/gui/progress_bar.py:127, the QStyleOptionProgressBar handed to drawControl
_.features  # origenerator/gui/thumbnail_dropdown.py:144, the QStyleOptionViewItem the item delegate paints from
_.decorationSize
_.showDecorationSelected

# --- vulture: reachable from nothing yet ---
_.to_logical_rect
