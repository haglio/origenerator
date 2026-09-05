"""Vulture whitelist — names the scan reports that are not dead code.

Handed to vulture as one more file to read, so a mention here counts as a use.
Nothing imports or runs it; `_` is the placeholder `--make-whitelist` writes for
"some object". Grouped by reason, so each entry can be checked against the thing
that actually calls it.

`tests/test_dead_code.py` fails on an entry that has stopped suppressing
anything, so nothing may stay here once its subject is gone.

Everything in it is now a caller vulture cannot follow -- Qt's C++ event loop,
sqlite3, COM, player_core, one string-dispatch table. The section this file
opened with, the 38 names the first scan reported and nobody had yet judged, is
empty: backlog item 24 read each one and either deleted it or gave it a reader.
An entry added here from now on says which of those five it is, or it does not
belong.
"""

# --- Qt event handlers and layout hooks -- called by the C++ event loop, never from here ---
_.dragMoveEvent  # noqa  # origenerator/gui/drop_slot.py:168, origenerator/gui/enhance_panel.py:454, origenerator/gui/folder_tree.py:242, origenerator/gui/generation_queue.py:633
_.dropEvent  # noqa  # origenerator/gui/drop_slot.py:174, origenerator/gui/enhance_panel.py:457, origenerator/gui/folder_tree.py:255, origenerator/gui/generation_queue.py:644
_.takeAt  # noqa  # origenerator/gui/flow_layout.py:46
_.expandingDirections  # noqa  # origenerator/gui/flow_layout.py:51
_.hasHeightForWidth  # noqa  # origenerator/gui/flow_layout.py:54
_.startDrag  # noqa  # origenerator/gui/folder_tree.py:204
_.wheelEvent  # noqa  # origenerator/gui/no_wheel.py:43, origenerator/gui/no_wheel.py:97, origenerator/gui/no_wheel.py:102

# --- Qt override signatures -- the framework passes the argument, so the parameter has to be there ---
supported_actions  # noqa  # origenerator/gui/folder_tree.py:204

# --- player_core reads this off the stroke state this app writes it on ---
# `cruise_control` asks `direct.playing` whether the stroke is running before it
# advances the wave stack; nothing here reads it back.
_.playing  # noqa  # origenerator/gui/osr2_stroke_driver.py:146, origenerator/gui/osr2_stroke_driver.py:163

# --- reached by name, from the table a spoken word is dispatched through ---
# `gallery_view._VOICE_STROKE` maps AppCommand.CRUISE_ON/CRUISE_OFF to the string
# "set_cruise", which `_turn_stroke_knob` hands to getattr.
_.set_cruise  # noqa  # origenerator/gui/osr2_stroke_driver.py:257

# --- sqlite3 reads this off the connection it was set on ---
_.row_factory  # noqa  # origenerator/branch_session.py:149, origenerator/branch_session.py:169, origenerator/branch_session.py:287, origenerator/db.py:231

# --- style-option fields written for Qt's painter to read, never read back here ---
_.textVisible  # noqa  # origenerator/gui/progress_caption.py:127, the QStyleOptionProgressBar handed to drawControl

# --- reachable from nothing yet ---
_.to_logical_rect  # noqa  # origenerator/ui_scale.py:91, added in 23ee359 for the hosted app with only its tests calling it; the caller it waits for is that work's to land, not this landing's to decide
