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
_.dragEnterEvent  # origenerator/gui/drop_slot.py:64, origenerator/gui/folder_tree.py:304, origenerator/gui/job_queue_view.py:743
_.dropEvent  # origenerator/gui/drop_slot.py:73, origenerator/gui/folder_tree.py:329, origenerator/gui/job_queue_view.py:757
_.contextMenuEvent  # origenerator/gui/drop_slot.py:238
_.takeAt  # origenerator/gui/flow_layout.py:46
_.expandingDirections  # origenerator/gui/flow_layout.py:51
_.hasHeightForWidth  # origenerator/gui/flow_layout.py:54
_.mouseDoubleClickEvent  # origenerator/gui/funestra_pane.py:283, origenerator/gui/job_queue_view.py:151, origenerator/gui/preview_widget.py:600, origenerator/gui/thumbnail_widget.py:392
_.startDrag  # origenerator/gui/folder_tree.py:219
_.wheelEvent  # origenerator/gui/funestra_pane.py:290, origenerator/gui/no_wheel.py:47, origenerator/gui/no_wheel.py:101, origenerator/gui/no_wheel.py:106
_.highlightBlock  # origenerator/gui/past_the_limit.py:12

# --- Qt override signatures -- the framework passes the argument, so the parameter has to be there ---
supported_actions  # origenerator/gui/folder_tree.py:219

# --- funestra's Funestra asks these of what runs on it, through its User protocol ---
_.apply_command  # origenerator/gui/slideshow_view.py:498
_.top_block  # origenerator/gui/slideshow_view.py:507
_.set_showing  # origenerator/gui/slideshow_view.py:510
_.own_frame  # origenerator/gui/slideshow_view.py:513

# --- reached by name, from the table a spoken word is dispatched through ---
# `voice_router._MOTION` maps the spoken on and off words for human inspired to
# "set_learned", which `_hold_the_motion` hands to getattr.
_.set_learned  # origenerator/osr2_motion_driver.py:269

# --- sqlite3 reads this off the connection it was set on ---
_.row_factory  # origenerator/branch_session.py:149, origenerator/branch_session.py:169, origenerator/branch_session.py:287, origenerator/db.py:231

# --- sqlite3 hands this back on rows nothing writes any more, which the listing keeps for every source the enum names ---
_.STROKE_TRIM  # origenerator/generation_state.py:25, the source on a Genau-lane cut, read through _KNOWN_SOURCES in origenerator/db_generations.py

# --- the tokenizers library reads these off the Tokenizer they were set on, in its own Rust code ---
_.normalizer  # origenerator/prompt_tokens.py:193, origenerator/prompt_tokens.py:205, origenerator/prompt_tokens.py:239
_.pre_tokenizer  # origenerator/prompt_tokens.py:195, origenerator/prompt_tokens.py:206, origenerator/prompt_tokens.py:240

# --- style-option fields written for Qt's painter to read, never read back here ---
_.textVisible  # origenerator/gui/progress_caption.py:127, the QStyleOptionProgressBar handed to drawControl
_.features  # origenerator/gui/thumbnail_dropdown.py:144, the QStyleOptionViewItem the item delegate paints from
_.decorationSize  # origenerator/gui/thumbnail_dropdown.py:145, the same option
_.showDecorationSelected  # origenerator/gui/thumbnail_dropdown.py:185, the option a row's ground is drawn from

# --- reachable from nothing yet ---
_.to_logical_rect  # origenerator/ui_scale.py:91, added in 23ee359 for the hosted app with only its tests calling it; the caller it waits for is that work's to land, not this landing's to decide
