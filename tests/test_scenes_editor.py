from __future__ import annotations

from origenerator.gui.scenes_editor import ScenesEditor
from origenerator.workflows.base import ParamDef


def _editor(qtbot, scenes=3):
    frames_def = ParamDef("scene_frames", "Scenes", "scenes", [81], min_val=5, max_val=961,
                          step=4, options=[1, 5, 10, 15, 30, 60], unit="s", rate=16.0)
    editor = ScenesEditor(frames_def, lambda dropdown: None, {})
    qtbot.addWidget(editor)
    for _ in range(scenes - 1):
        editor.add_scene()
    return editor


def test_a_list_of_lengths_short_of_the_scenes_leaves_the_rest_as_they_are(qtbot):
    editor = _editor(qtbot)

    editor.set_scene_frames([161])

    assert editor.scene_frames() == [161, 81, 81]


def test_a_list_of_lengths_past_the_scenes_is_cut_to_fit(qtbot):
    editor = _editor(qtbot, scenes=2)

    editor.set_scene_frames([161, 41, 241])

    assert editor.scene_frames() == [161, 41]
