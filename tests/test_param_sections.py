import pytest

from origenerator.gui import param_sections as ps
from origenerator.workflows import WORKFLOW_REGISTRY


def test_sections_are_in_the_canonical_display_order():
    titles = [s.title for s in ps.SECTIONS]
    assert titles == [
        "Prompts", "Seed", "Model & LoRA", "Sampling",
        "Dimensions", "Frames", "Output",
    ]


def test_section_title_places_each_kind_of_param_in_its_section():
    assert ps.section_title("positive_prompt") == "Prompts"
    assert ps.section_title("input_image") == "Prompts"
    assert ps.section_title("seed") == "Seed"
    assert ps.section_title("noise_seed") == "Seed"
    assert ps.section_title("checkpoint") == "Model & LoRA"
    assert ps.section_title("lora_high") == "Model & LoRA"
    assert ps.section_title("vae") == "Model & LoRA"          # passthrough model file
    assert ps.section_title("steps") == "Sampling"
    assert ps.section_title("scheduler") == "Sampling"
    assert ps.section_title("width") == "Dimensions"
    assert ps.section_title("frame_count") == "Frames"
    assert ps.section_title("frame_rate") == "Frames"
    assert ps.section_title("filename_prefix") == "Output"


def test_unknown_key_falls_into_the_other_section_sorted_last():
    assert ps.section_title("mystery_param") == ps.OTHER_TITLE
    # It ranks after every mapped key, so it renders in a trailing catch-all.
    assert ps.key_rank("mystery_param") > ps.key_rank("filename_prefix")


def test_key_rank_orders_across_and_within_sections():
    # Across sections: a prompt precedes a seed precedes a sampling knob.
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
def test_every_workflow_param_maps_to_a_named_section(workflow_name):
    # The consistency guarantee: no registered workflow may carry a param that
    # falls through to "Other". A new param must be assigned a home in SECTIONS,
    # so the form groups it the same way for every workflow that shares it.
    wf = WORKFLOW_REGISTRY[workflow_name]
    keys = set(wf.default_params()) | {pd.key for pd in wf.param_definitions()}
    unmapped = sorted(k for k in keys if ps.section_title(k) == ps.OTHER_TITLE)
    assert unmapped == [], f"{workflow_name} params without a section: {unmapped}"
