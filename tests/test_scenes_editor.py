from __future__ import annotations

from PyQt6.QtCore import Qt

from origenerator.gui.prompt_marks import RESOLVE_IN_BOTH_PROMPTS, problem_to_resolve
from origenerator.gui.scenes_editor import ScenesEditor
from origenerator.prompt_tokens import CUT_OFF, READ_IN_PIECES
from origenerator.workflows.base import ParamDef
from tests.text_readers import word_reading


def _editor(qtbot, scenes=3):
    frames_def = ParamDef("scene_frames", "Scenes", "scenes", [81], min_val=5, max_val=961,
                          step=4, options=[1, 5, 10, 15, 30, 60], unit="s", shown_in_seconds_at=16.0)
    editor = ScenesEditor(frames_def, lambda dropdown: None, {})
    qtbot.addWidget(editor)
    for _ in range(scenes - 1):
        editor.add_scene()
    return editor


def test_a_scene_is_refused_over_a_thing_in_both_of_its_own_prompts(qtbot):
    editor = _editor(qtbot, scenes=2)
    editor.set_story("positive_prompt", "red cat\n---\nblue dog")

    editor.fields("negative_prompt")[1].setPlainText("blue dog")

    assert problem_to_resolve(editor.text_fields()) == RESOLVE_IN_BOTH_PROMPTS


def test_a_thing_in_one_scenes_positive_and_anothers_negative_is_no_problem(qtbot):
    editor = _editor(qtbot, scenes=2)
    editor.set_story("positive_prompt", "red cat\n---\nblue dog")

    editor.fields("negative_prompt")[1].setPlainText("red cat")

    assert problem_to_resolve(editor.text_fields()) is None


def test_a_scene_with_a_line_of_hers_reads_no_prompts_so_nothing_is_in_both(qtbot):
    editor = _editor(qtbot, scenes=1)
    editor.set_story("positive_prompt", "red cat")
    editor.fields("negative_prompt")[0].setPlainText("red cat")

    editor.fields("scene_lines")[0].setPlainText("made up words")

    assert problem_to_resolve(editor.text_fields()) is None


def test_a_list_of_lengths_short_of_the_scenes_leaves_the_rest_as_they_are(qtbot):
    editor = _editor(qtbot)

    editor.set_scene_frames([161])

    assert editor.scene_frames() == [161, 81, 81]


def test_a_list_of_lengths_past_the_scenes_is_cut_to_fit(qtbot):
    editor = _editor(qtbot, scenes=2)

    editor.set_scene_frames([161, 41, 241])

    assert editor.scene_frames() == [161, 41]


def test_removing_emphasis_reaches_each_scene_the_model_reads_as_plain_text(qtbot):
    editor = _editor(qtbot, scenes=2)
    editor.show_readings({"positive_prompt": word_reading(76, CUT_OFF)})
    first, second = editor.fields("positive_prompt")
    first.setPlainText("(a:1.2), b")
    second.setPlainText("((c))")

    editor.remove_unread_emphasis()

    assert (first.toPlainText(), second.toPlainText()) == ("a, b", "c")


def test_removing_emphasis_leaves_a_scene_whose_model_reads_it(qtbot):
    editor = _editor(qtbot, scenes=1)
    editor.show_readings({"positive_prompt": word_reading(76, READ_IN_PIECES)})
    (field,) = editor.fields("positive_prompt")
    field.setPlainText("(a:1.2), b")

    editor.remove_unread_emphasis()

    assert field.toPlainText() == "(a:1.2), b"


def test_removing_emphasis_from_a_scene_can_be_undone(qtbot):
    editor = _editor(qtbot, scenes=1)
    editor.show_readings({"positive_prompt": word_reading(76, CUT_OFF)})
    (field,) = editor.fields("positive_prompt")
    field.setPlainText("(a:1.2), b")

    editor.remove_unread_emphasis()
    qtbot.keyClick(field, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)

    assert field.toPlainText() == "(a:1.2), b"
