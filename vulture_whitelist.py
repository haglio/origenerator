"""Vulture whitelist — names the scan reports that are not dead code.

Handed to vulture as one more file to read, so a mention here counts as a use.
Nothing imports or runs it; `_` is the placeholder `--make-whitelist` writes for
"some object". Grouped by reason, so each entry can be checked against the thing
that actually calls it.

`tests/test_dead_code.py` fails on an entry that has stopped suppressing
anything, so nothing may stay here once its subject is gone.

Everything in it is now a caller vulture cannot follow -- Qt's C++ event loop,
sqlite3, COM, funestra, one string-dispatch table. The section this file
opened with, the 38 names the first scan reported and nobody had yet judged, is
empty: backlog item 24 read each one and either deleted it or gave it a reader.
An entry added here from now on says which of those five it is, or it does not
belong.
"""
from __future__ import annotations

# --- Qt event handlers and layout hooks -- called by the C++ event loop, never from here ---
_.dragEnterEvent  # noqa  # origenerator/gui/drop_slot.py:64, origenerator/gui/folder_tree.py:304, origenerator/gui/generation_queue.py:743
_.dropEvent  # noqa  # origenerator/gui/drop_slot.py:73, origenerator/gui/folder_tree.py:329, origenerator/gui/generation_queue.py:757
_.contextMenuEvent  # noqa  # origenerator/gui/drop_slot.py:238
_.takeAt  # noqa  # origenerator/gui/flow_layout.py:46
_.expandingDirections  # noqa  # origenerator/gui/flow_layout.py:51
_.hasHeightForWidth  # noqa  # origenerator/gui/flow_layout.py:54
_.startDrag  # noqa  # origenerator/gui/folder_tree.py:219
_.wheelEvent  # noqa  # origenerator/gui/funestra_pane.py:263, origenerator/gui/no_wheel.py:47, origenerator/gui/no_wheel.py:101, origenerator/gui/no_wheel.py:106

# --- Qt override signatures -- the framework passes the argument, so the parameter has to be there ---
supported_actions  # noqa  # origenerator/gui/folder_tree.py:219

# --- funestra's Funestra asks these of what runs on it, through its User protocol ---
_.apply_command  # noqa  # origenerator/gui/slideshow_view.py:1617
_.status_fields  # noqa  # origenerator/gui/slideshow_view.py:1623
_.top_block  # noqa  # origenerator/gui/slideshow_view.py:1626
_.set_showing  # noqa  # origenerator/gui/slideshow_view.py:1629

# --- reached by name, from the table a spoken word is dispatched through ---
# `voice_router._MOTION` maps the spoken on and off words for human inspired to
# "set_learned", which `_hold_the_motion` hands to getattr.
_.set_learned  # noqa  # origenerator/osr2_motion_driver.py:269

# --- sqlite3 reads this off the connection it was set on ---
_.row_factory  # noqa  # origenerator/branch_session.py:149, origenerator/branch_session.py:169, origenerator/branch_session.py:287, origenerator/db.py:231

# --- sqlite3 hands this back on rows nothing writes any more, which the listing keeps for every source the enum names ---
_.STROKE_TRIM  # noqa  # origenerator/generation_state.py:25, the source on a Genau-lane cut, read through _KNOWN_SOURCES in origenerator/db_generations.py

# --- style-option fields written for Qt's painter to read, never read back here ---
_.textVisible  # noqa  # origenerator/gui/progress_caption.py:127, the QStyleOptionProgressBar handed to drawControl
_.features  # noqa  # origenerator/gui/pictured_dropdown.py:144, the QStyleOptionViewItem the item delegate paints from
_.decorationSize  # noqa  # origenerator/gui/pictured_dropdown.py:145, the same option
_.showDecorationSelected  # noqa  # origenerator/gui/pictured_dropdown.py:185, the option a row's ground is drawn from

# --- reachable from nothing yet ---
_.to_logical_rect  # noqa  # origenerator/ui_scale.py:91, added in 23ee359 for the hosted app with only its tests calling it; the caller it waits for is that work's to land, not this landing's to decide
