"""Vulture whitelist — names the scan reports that are not dead code.

Handed to vulture as one more file to read, so a mention here counts as a use.
Nothing imports or runs it; `_` is the placeholder `--make-whitelist` writes for
"some object". Grouped by reason, so each entry can be checked against the thing
that actually calls it.

`tests/test_dead_code.py` fails on an entry that has stopped suppressing
anything, so nothing may stay here once its subject is gone.
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

# --- sqlite3 reads this off the connection it was set on ---
_.row_factory  # noqa  # origenerator/branch_session.py:149, origenerator/branch_session.py:169, origenerator/branch_session.py:287, origenerator/db.py:231

# --- ctypes PROPVARIANT fields consumed by COM IPropertyStore (win32.py: _set_lnk_aumid) ---
_.vt  # noqa  # origenerator/win32.py:146
_.pwszVal  # noqa  # origenerator/win32.py:147

# --- Reported when this gate went in, 2026-08-30: not yet judged -----------
#
# Every line below is something vulture reports today. They are here so the
# gate could be turned on before the deletions rather than after -- backlog
# item 24 is the pass that reads each one and either deletes it or gives it a
# caller, and this section is that item's worklist. It is meant to reach zero;
# nothing new belongs in it.
#
# Nothing here was deleted while the gate went in: within a repo the order is
# tests first, then deletions, and most of these are accessors some test still
# calls, so removing one changes what the suite covers. The cheap end to start
# from is what vulture is most certain of -- the two unused imports in
# `gui/stroke_panel.py` and the unused local in `gui/reroll_controller.py`.

# origenerator/ambient_audio.py
_.playing  # noqa  # unused method: ambient_audio.py:65, osr2_stroke_driver.py:146, osr2_stroke_driver.py:163

# origenerator/experiments/policy.py
base_prompt_id  # noqa  # unused variable: policy.py:61
mutated_keys  # noqa  # unused variable: policy.py:62

# origenerator/gui/combine_panel.py
_.set_intent  # noqa  # unused method: combine_panel.py:156
_.set_category  # noqa  # unused method: combine_panel.py:178

# origenerator/gui/corner_controls.py
_.set_starred  # noqa  # unused method: corner_controls.py:172, thumbnail_widget.py:184

# origenerator/gui/diff_text.py
showing_diff  # noqa  # unused function: diff_text.py:111

# origenerator/gui/gallery_view.py
_match_voice_command  # noqa  # unused function: gallery_view.py:310
_._showing_recents  # noqa  # unused method: gallery_view.py:6023
_._apply_selection  # noqa  # unused method: gallery_view.py:6199

# origenerator/gui/generate_config_panel.py
_.requesting_changes  # noqa  # unused method: generate_config_panel.py:862

# origenerator/gui/generation_queue.py
_.thumbs  # noqa  # unused method: generation_queue.py:337
_.running_preview  # noqa  # unused method: generation_queue.py:512

# origenerator/gui/info_pane_tabs.py
_.preview_paused  # noqa  # unused method: info_pane_tabs.py:474

# origenerator/gui/looping_preview.py
previews_paused  # noqa  # unused function: looping_preview.py:79

# origenerator/gui/osr2_stroke_driver.py
_.set_cruise  # noqa  # unused method: osr2_stroke_driver.py:257
_.cruising  # noqa  # unused property: osr2_stroke_driver.py:272

# origenerator/gui/param_form.py
_._width_label  # noqa  # unused attribute: param_form.py:144, param_form.py:362
_._height_label  # noqa  # unused attribute: param_form.py:145, param_form.py:363

# origenerator/gui/prompt_find.py
_.current_field  # noqa  # unused method: prompt_find.py:141

# origenerator/gui/split_folder_tree.py
_.tree_for  # noqa  # unused method: split_folder_tree.py:126

# origenerator/gui/thumbnail_widget.py
_.is_starred  # noqa  # unused method: thumbnail_widget.py:181
_.is_enhancing  # noqa  # unused method: thumbnail_widget.py:220

