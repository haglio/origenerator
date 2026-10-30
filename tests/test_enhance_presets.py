"""Enhancement settings saved under a name: what the Enhance panel's dropdown
lists, and the most common enhancements a library starts it with."""
from __future__ import annotations

import json

import pytest

from origenerator import enhance_presets
from origenerator.app_state import AppState
from origenerator.db import Database
from origenerator.enhance_presets import Preset
from origenerator.gallery.enhance import most_used_enhancements
from origenerator.gallery.enhance_fold import fold_enhancement
from origenerator.gallery.enhance_settings import MATCH_SOURCE_MODEL, default_enhance_params
from origenerator.gui import enhance_panel
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.detail_parts import fix_prompts_of, part_named
from tests.test_core import _window


def _enhanced(prompt_id, checkpoint="anemone_v3.safetensors", **settings):
    """An image the Generate form's own enhance finished, at ``settings``."""
    return {
        "prompt_id": prompt_id,
        "workflow_name": "sdxl_t2i",
        "params_json": json.dumps({"checkpoint": checkpoint, "enhance": True, **settings}),
        "output_files": json.dumps(
            [{"filename": f"{prompt_id}.png", "subfolder": "image", "type": "output"}]),
    }


def test_the_enhancements_made_most_often_come_first():
    rows = [_enhanced("a", enhance_scale=2.0), _enhanced("b", enhance_scale=3.0),
            _enhanced("c", enhance_scale=3.0)]

    assert [s["enhance_scale"] for s in most_used_enhancements(rows, 5)] == [3.0, 2.0]


def test_an_image_enhanced_by_the_model_that_made_it_was_enhanced_matching_the_source():
    rows = [_enhanced("a", checkpoint="anemone_v3.safetensors"),
            _enhanced("b", checkpoint="driftwood_v1.safetensors")]

    (settings,) = most_used_enhancements(rows, 5)

    assert settings["checkpoint"] == MATCH_SOURCE_MODEL


def _library_of_one_image(tmp_path, own_params, *runs):
    """The rows of a library holding one image, made at ``own_params``, with a
    standalone enhancement folded onto it for each of ``runs``."""
    db = Database(tmp_path / "t.db")
    db.insert_generation(prompt_id="src", workflow_name="flux_t2i", workflow_version="v001",
                         params_json=json.dumps(own_params), workflow_json="{}")
    db.update_generation("src", status="completed", output_files=json.dumps(
        [{"filename": "src.png", "subfolder": "image", "type": "output"}]))
    for number, run in enumerate(runs, 1):
        prompt_id = f"enhance{number}"
        db.insert_generation(
            prompt_id=prompt_id, workflow_name="image_enhance", workflow_version="v004",
            params_json=json.dumps({"input_image": "image/src.png [output]", **run}),
            workflow_json="{}")
        db.update_generation(prompt_id, status="completed", output_files=json.dumps(
            [{"filename": f"image_enhance_{number:05}_.png", "subfolder": "image",
              "type": "output"}]))
        fold_enhancement(db, db.get_generation(prompt_id))
    return db.list_generations()


def test_an_image_that_recorded_no_model_was_enhanced_matching_the_source_by_the_enhancers_own(
        tmp_path):
    enhancers_own = WORKFLOW_REGISTRY["image_enhance"].default_params()["checkpoint"]
    rows = _library_of_one_image(tmp_path, {}, {"checkpoint": enhancers_own})

    (settings,) = most_used_enhancements(rows, 5)

    assert settings["checkpoint"] == MATCH_SOURCE_MODEL


def test_a_fix_from_before_fixes_had_prompts_counts_with_the_one_the_panel_would_run_for_it(
        tmp_path):
    """The panel cannot run a fix without its part's own prompts any more, so the
    two would be one setting on it, and one preset."""
    rows = _library_of_one_image(
        tmp_path, {},
        {"enhance_detail_fixes": {"faces": 0.45}},
        {"enhance_detail_fixes": {"faces": 0.45},
         "enhance_fix_prompts": {"faces": fix_prompts_of(part_named("faces"), None)}})

    assert len(most_used_enhancements(rows, 5)) == 1


# --- the presets kept beside the library ------------------------------------


def test_a_library_that_never_had_presets_starts_with_its_five_most_common_named_by_settings(
        tmp_path):
    rows = [_enhanced(f"i{number}", enhance_steps=steps)
            for number, steps in enumerate([10, 11, 11, 12, 13, 14, 15])]

    started = enhance_presets.load(lambda: rows, path=tmp_path / "presets.json")

    assert [preset.name for preset in started] == [
        "2x · 11 steps · 0.15 redraw", "2x · 10 steps · 0.15 redraw",
        "2x · 12 steps · 0.15 redraw", "2x · 13 steps · 0.15 redraw",
        "2x · 14 steps · 0.15 redraw"]


def test_the_presets_a_library_started_with_stay_its_presets_as_its_enhancements_change(
        tmp_path):
    path = tmp_path / "presets.json"
    enhance_presets.load(lambda: [_enhanced("a", enhance_steps=10)], path=path)

    later = enhance_presets.load(lambda: [_enhanced("b", enhance_steps=30)], path=path)

    assert [preset.name for preset in later] == ["2x · 10 steps · 0.15 redraw"]


def test_a_saved_preset_goes_at_the_bottom_and_is_there_next_time(tmp_path):
    path = tmp_path / "presets.json"
    enhance_presets.load(lambda: [_enhanced("a", enhance_steps=10)], path=path)

    saved = enhance_presets.save("Crisp", {"enhance_steps": 40}, path=path)

    assert [preset.name for preset in saved] == ["2x · 10 steps · 0.15 redraw", "Crisp"]
    assert saved[1].params == {"enhance_steps": 40}
    assert enhance_presets.load(list, path=path) == saved


def test_a_renamed_preset_keeps_its_settings_and_its_place(tmp_path):
    path = tmp_path / "presets.json"
    before = enhance_presets.load(lambda: [
        _enhanced("a", enhance_steps=10), _enhanced("b", enhance_steps=20),
        _enhanced("c", enhance_steps=20)], path=path)

    renamed = enhance_presets.rename(1, "Soft", path=path)

    assert [preset.name for preset in renamed] == [before[0].name, "Soft"]
    assert renamed[1].params == before[1].params
    assert enhance_presets.load(list, path=path) == renamed


@pytest.mark.parametrize("held", ["not json", "[]", '{"presets": [{"name": "Crisp"}]}'])
def test_presets_that_cannot_be_read_are_none_and_the_next_save_starts_them_again(
        tmp_path, held):
    path = tmp_path / "presets.json"
    path.write_text(held, encoding="utf-8")

    assert enhance_presets.load(lambda: [_enhanced("a", enhance_steps=10)], path=path) == []
    assert enhance_presets.save("Crisp", {"enhance_steps": 40}, path=path) == [
        Preset("Crisp", {"enhance_steps": 40})]


def test_a_preset_saved_after_the_presets_file_went_missing_starts_it_again(tmp_path):
    path = tmp_path / "presets.json"

    enhance_presets.save("Crisp", {"enhance_steps": 40}, path=path)

    assert enhance_presets.load(list, path=path) == [Preset("Crisp", {"enhance_steps": 40})]


def test_the_settings_are_the_preset_holding_them_whatever_each_leaves_to_the_defaults():
    presets = [Preset("Crisp", {"enhance_steps": 40}),
               Preset("Soft", {**default_enhance_params(), "enhance_steps": 30})]

    assert enhance_presets.matching(presets, {**default_enhance_params(), "enhance_steps": 40}) == 0
    assert enhance_presets.matching(presets, {"enhance_steps": 30}) == 1
    assert enhance_presets.matching(presets, {"enhance_steps": 50}) is None


# --- in the window ------------------------------------------------------------


def test_a_preset_saved_in_the_window_is_the_one_its_dropdown_shows_after_a_restart(
        qtbot, tmp_path, monkeypatch):
    path = tmp_path / "ui.json"
    first = _window(qtbot, tmp_path, AppState(path))
    panel = first._gallery_view._enhance.panel
    panel._steps.setValue(44)
    monkeypatch.setattr(enhance_panel.QInputDialog, "getText",
                        staticmethod(lambda *_args, **_kwargs: ("Crisp", True)))
    panel._preset_button.click()
    first.close()

    reopened = _window(qtbot, tmp_path, AppState(path))

    picker = reopened._gallery_view._enhance.panel._preset_picker
    assert picker.currentText() == "Crisp"
