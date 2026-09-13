from __future__ import annotations

import pytest

from origenerator.gui import param_sections as ps
from origenerator.workflows import WORKFLOW_REGISTRY


def test_sections_are_in_the_canonical_display_order():
    titles = [s.title for s in ps.SECTIONS]
    assert titles == [
        "Prompts", "Seed", "Models & Add-ons", "Drawing", "Motion",
        "Size", "Video", "Sound",
    ]


def test_enhance_has_no_section_because_it_is_not_a_folder_setting():
    # Every section here holds params that decide which gallery folder a run
    # lands in. An enhancement doesn't — it's a finish applied afterward — so it
    # is deliberately absent, and the gallery's Enhance subpanel owns it instead.
    assert "Enhance" not in [s.title for s in ps.SECTIONS]
    for key in ("enhance", "enhance_scale", "enhance_steps", "enhance_denoise"):
        assert ps.section_title(key) == ps.OTHER_TITLE


def test_section_title_places_each_kind_of_param_in_its_section():
    assert ps.section_title("positive_prompt") == "Prompts"
    assert ps.section_title("input_image") == "Prompts"
    assert ps.section_title("seed") == "Seed"
    assert ps.section_title("noise_seed") == "Seed"
    assert ps.section_title("checkpoint") == "Models & Add-ons"
    assert ps.section_title("lora_high") == "Models & Add-ons"
    assert ps.section_title("steps") == "Drawing"
    assert ps.section_title("scheduler") == "Drawing"
    assert ps.section_title("upscale_model") == "Models & Add-ons"
    assert ps.section_title("motion_hz") == "Motion"
    assert ps.section_title("anchor_y") == "Motion"
    assert ps.section_title("width") == "Size"
    assert ps.section_title("frame_count") == "Video"
    assert ps.section_title("frame_rate") == "Video"
    assert ps.section_title("audio_prompt") == "Sound"
    assert ps.section_title("audio_seed") == "Sound"


def test_unknown_key_falls_into_the_other_section_sorted_last():
    assert ps.section_title("mystery_param") == ps.OTHER_TITLE
    # It ranks after every mapped key, so it renders in a trailing catch-all.
    assert ps.key_rank("mystery_param") > ps.key_rank("audio_seed")


def test_key_rank_orders_across_and_within_sections():
    # Across sections: a prompt precedes a seed precedes a sampling setting.
    assert ps.key_rank("positive_prompt") < ps.key_rank("seed")
    assert ps.key_rank("seed") < ps.key_rank("steps")
    assert ps.key_rank("steps") < ps.key_rank("width")
    # Within Sampling: the user's steps/cfg/sampler/scheduler/shift order holds.
    assert ps.key_rank("steps") < ps.key_rank("cfg") < ps.key_rank("sampler_name")
    assert ps.key_rank("sampler_name") < ps.key_rank("scheduler") < ps.key_rank("shift_high")


def test_sorting_a_workflows_keys_by_rank_is_stable_for_unknowns():
    # Stable sort: unknown keys keep their given order at the end, mapped keys jump
    # to their canonical slots.
    keys = ["zeta_extra", "steps", "positive_prompt", "alpha_extra"]
    ordered = sorted(keys, key=ps.key_rank)
    assert ordered == ["positive_prompt", "steps", "zeta_extra", "alpha_extra"]


def test_default_collapse_leaves_only_prompts_and_seed_open():
    open_sections = [s.title for s in ps.SECTIONS if not s.collapsed]
    assert open_sections == ["Prompts", "Seed"]


@pytest.mark.parametrize("workflow_name", list(WORKFLOW_REGISTRY))
def test_every_field_on_a_form_maps_to_a_named_section(workflow_name):
    wf = WORKFLOW_REGISTRY[workflow_name]
    fields = {pd.key for pd in wf.param_definitions()} - set(wf.enhance_keys())
    unmapped = sorted(k for k in fields if ps.section_title(k) == ps.OTHER_TITLE)
    assert unmapped == [], f"{workflow_name} fields without a section: {unmapped}"
