from __future__ import annotations

import pytest

from origenerator.gui import param_sections as ps
from origenerator.workflows import WORKFLOW_REGISTRY


def test_sections_are_in_the_canonical_display_order():
    titles = [s.title for s in ps.SECTIONS]
    assert titles == [
        "Prompts & Seed", "Workflow, Models & LoRAs", "Calibration",
        "Size", "Video", "Sound",
    ]


def test_enhance_has_no_section_because_it_is_not_a_folder_setting():
    assert "Enhance" not in [s.title for s in ps.SECTIONS]
    for key in ("enhance", "enhance_scale", "enhance_steps", "enhance_denoise"):
        assert ps.section_title(key) == ps.OTHER_TITLE


def test_section_title_places_each_kind_of_param_in_its_section():
    assert ps.section_title("positive_prompt") == "Prompts & Seed"
    assert ps.section_title("input_image") == "Prompts & Seed"
    assert ps.section_title("seed") == "Prompts & Seed"
    assert ps.section_title("noise_seed") == "Prompts & Seed"
    assert ps.section_title("checkpoint") == "Workflow, Models & LoRAs"
    assert ps.section_title("lora_high") == "Workflow, Models & LoRAs"
    assert ps.section_title("steps") == "Calibration"
    assert ps.section_title("scheduler") == "Calibration"
    assert ps.section_title("upscale_model") == "Workflow, Models & LoRAs"
    assert ps.section_title("width") == "Size"
    assert ps.section_title("frame_count") == "Video"
    assert ps.section_title("frame_rate") == "Video"
    assert ps.section_title("audio_prompt") == "Sound"
    assert ps.section_title("audio_seed") == "Sound"


def test_unknown_key_falls_into_the_other_section_sorted_last():
    assert ps.section_title("mystery_param") == ps.OTHER_TITLE
    assert ps.key_rank("mystery_param") > ps.key_rank("audio_seed")


def test_key_rank_orders_across_and_within_sections():
    assert ps.key_rank("positive_prompt") < ps.key_rank("seed")
    assert ps.key_rank("seed") < ps.key_rank("steps")
    assert ps.key_rank("steps") < ps.key_rank("width")
    assert ps.key_rank("steps") < ps.key_rank("cfg") < ps.key_rank("sampler_name")
    assert ps.key_rank("sampler_name") < ps.key_rank("scheduler") < ps.key_rank("shift_high")


def test_sorting_a_workflows_keys_by_rank_is_stable_for_unknowns():
    keys = ["zeta_extra", "steps", "positive_prompt", "alpha_extra"]
    ordered = sorted(keys, key=ps.key_rank)
    assert ordered == ["positive_prompt", "steps", "zeta_extra", "alpha_extra"]


def test_default_collapse_leaves_only_prompts_seed_and_the_workflow_open():
    open_sections = [s.title for s in ps.SECTIONS if not s.collapsed]
    assert open_sections == [ps.PROMPTS_TITLE, ps.WORKFLOW_TITLE]


@pytest.mark.parametrize("workflow_name", list(WORKFLOW_REGISTRY))
def test_every_field_on_a_form_maps_to_a_named_section(workflow_name):
    wf = WORKFLOW_REGISTRY[workflow_name]
    fields = {pd.key for pd in wf.param_definitions()} - set(wf.enhance_keys())
    unmapped = sorted(k for k in fields if ps.section_title(k) == ps.OTHER_TITLE)
    assert unmapped == [], f"{workflow_name} fields without a section: {unmapped}"
