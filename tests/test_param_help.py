"""Every workflow parameter explains itself, once, in one place.

The Generate form's fields carry tooltips drawn from a central map rather than
from each workflow's own definitions: the same key means the same thing in every
workflow that has it, so writing the explanation once is what keeps twelve
descriptions of ``cfg`` from drifting into twelve different claims.
"""
from __future__ import annotations

import re

import pytest

from origenerator.gallery import ENHANCE_SETTING_KEYS
from origenerator.gui.param_help import (
    PARAM_HELP,
    RECOMMENDED,
    definition_help,
    option_help,
    param_help,
)
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.base import SAMPLER_OPTIONS, ParamDef, ParamType


@pytest.mark.parametrize("workflow_name", list(WORKFLOW_REGISTRY))
def test_every_field_on_a_form_is_explained(workflow_name):
    wf = WORKFLOW_REGISTRY[workflow_name]
    fields = {pd.key for pd in wf.param_definitions()} - set(wf.enhance_keys())
    missing = sorted(k for k in fields if not param_help(k))
    assert missing == [], f"{workflow_name} fields with no help: {missing}"


def test_no_help_is_written_for_a_setting_nothing_on_screen_shows():
    shown = set(ENHANCE_SETTING_KEYS)
    for wf in WORKFLOW_REGISTRY.values():
        if wf.selectable:
            shown |= {pd.key for pd in wf.param_definitions()} - set(wf.enhance_keys())
    assert sorted(set(PARAM_HELP) - shown) == []


def test_an_unknown_param_has_no_help_rather_than_a_placeholder():
    # Qt shows no tooltip for an empty string, and an explanation that says
    # nothing is worse than no explanation at all.
    assert param_help("mystery_param") == ""


def test_help_reads_as_a_sentence_not_a_restatement_of_the_label():
    # The failure mode a tooltip pass invites: "Steps: the number of steps".
    for key, text in PARAM_HELP.items():
        assert len(text) > len(key) + 12, f"{key} says nothing its label doesn't"
        assert text[0].isupper(), f"{key} help should start as a sentence"


def test_the_settings_the_enhance_panel_shows_are_all_explained():
    assert all(param_help(key) for key in ENHANCE_SETTING_KEYS)


def test_help_calls_the_picture_a_run_starts_from_what_its_field_is_called():
    stale = sorted(key for key, text in PARAM_HELP.items()
                   if "input picture" in text or "the input's" in text)
    assert stale == []


def test_help_speaks_the_forms_words_outside_its_parentheses():
    jargon = re.compile(r"high-noise|low-noise|ControlNet|ESRGAN|\bCFG\b"
                        r"|\bstages?\b|\baudio\b|\bsampling\b|\bexperts?\b",
                        re.IGNORECASE)
    stale = sorted(key for key, text in PARAM_HELP.items()
                   if jargon.search(re.sub(r"\([^)]*\)", "", text)))
    assert stale == []


@pytest.mark.parametrize("workflow_name", list(WORKFLOW_REGISTRY))
def test_a_field_for_one_pass_says_which_noise_that_pass_works_on(workflow_name):
    halves = {"(First Pass)": "high noise", "(Second Pass)": "low noise"}
    unsaid = [pd.key for pd in WORKFLOW_REGISTRY[workflow_name].param_definitions()
              for suffix, half in halves.items()
              if pd.label.endswith(suffix) and half not in param_help(pd.key).replace("-", " ")]
    assert unsaid == []


def test_the_seed_and_the_handoff_say_which_noise_each_pass_works_on():
    assert "high noise" in PARAM_HELP["noise_seed"]
    assert "high noise" in PARAM_HELP["split_step"] and "low noise" in PARAM_HELP["split_step"]


def test_composition_focus_says_what_composition_is():
    assert "layout" in PARAM_HELP["shift_high"]


def test_the_handoff_says_when_to_move_it_off_halfway():
    assert "motion" in PARAM_HELP["split_step"] and "detail" in PARAM_HELP["split_step"]


def test_the_prompt_strength_help_says_what_one_and_below_do_to_the_negative_prompt():
    assert "At 1 the Negative Prompt is ignored; any lower and it works backwards." in PARAM_HELP["cfg"]
    for key in ("cfg_high", "cfg_low"):
        assert "At 1 this pass ignores the Negative Prompt; any lower and it works backwards." in PARAM_HELP[key]


def test_help_calls_a_lora_a_lora():
    loras = ("lora_high", "lora_low", "lora_strength_high", "lora_strength_low")
    assert all("LoRA" in PARAM_HELP[key] for key in loras)
    assert [key for key, text in PARAM_HELP.items() if "add-on" in text.lower()] == []


def test_every_sampler_says_how_it_works_and_how_long_it_takes():
    unexplained = [name for name in SAMPLER_OPTIONS
                   if "per step" not in option_help("sampler_name", name)]
    assert unexplained == []


@pytest.mark.parametrize("workflow_name", list(WORKFLOW_REGISTRY))
def test_every_number_on_a_form_recommends_what_to_set_it_to(workflow_name):
    numbers = (ParamType.INT, ParamType.FLOAT)
    unadvised = sorted(pd.key for pd in WORKFLOW_REGISTRY[workflow_name].param_definitions()
                       if pd.type in numbers and pd.good is None and pd.key not in RECOMMENDED)
    assert unadvised == []


@pytest.mark.parametrize("workflow_name", list(WORKFLOW_REGISTRY))
def test_a_numbers_good_range_is_one_the_app_holds_it_to_not_a_sentence(workflow_name):
    numbers = (ParamType.INT, ParamType.FLOAT)
    said = sorted(pd.key for pd in WORKFLOW_REGISTRY[workflow_name].param_definitions()
                  if pd.type in numbers and pd.good is None
                  and re.search(r"\d–\d", RECOMMENDED.get(pd.key, "")))
    assert said == []


@pytest.mark.parametrize("workflow_name", list(WORKFLOW_REGISTRY))
def test_a_forms_own_defaults_sit_inside_their_good_ranges(workflow_name):
    outside = sorted(pd.key for pd in WORKFLOW_REGISTRY[workflow_name].param_definitions()
                     if pd.good is not None and not pd.good[0] <= pd.default <= pd.good[1])
    assert outside == []


@pytest.mark.parametrize("workflow_name", list(WORKFLOW_REGISTRY))
def test_a_good_range_stays_inside_what_its_field_can_be_set_to(workflow_name):
    past = sorted(pd.key for pd in WORKFLOW_REGISTRY[workflow_name].param_definitions()
                  if pd.good is not None
                  and not pd.min_val <= pd.good[0] <= pd.good[1] <= pd.max_val)
    assert past == []


@pytest.mark.parametrize("workflow_name", list(WORKFLOW_REGISTRY))
def test_where_a_tooltip_says_a_setting_starts_to_go_wrong_is_its_good_ranges_edge(workflow_name):
    edge = re.compile(r"\b(below|under|above|over|past) (\d+(?:\.\d+)?)x?\b", re.IGNORECASE)
    elsewhere = sorted(
        (pd.key, said) for pd in WORKFLOW_REGISTRY[workflow_name].param_definitions()
        if pd.good is not None
        for side, said in edge.findall(PARAM_HELP.get(pd.key, ""))
        if float(said) != pd.good[side.lower() not in ("below", "under")])
    assert elsewhere == []


def test_the_sampler_step_spacing_and_fixes_recommend_what_to_set_them_to():
    assert {"sampler_name", "scheduler", "enhance_detail_fixes"} <= RECOMMENDED.keys()


def test_a_tooltip_ends_with_what_to_set_it_to():
    steps = next(pd for pd in WORKFLOW_REGISTRY["sdxl_t2i"].param_definitions()
                 if pd.key == "steps")
    assert definition_help(steps) == f"{PARAM_HELP['steps']} Good range: 25–50."


def test_one_value_is_recommended_as_advice_rather_than_as_a_range():
    assert RECOMMENDED["split_step"].startswith("Leave it at 0,")


def test_every_span_of_numbers_is_called_a_good_range():
    unnamed = sorted(key for key, text in RECOMMENDED.items()
                     if re.search(r"\d–\d", text) and "good range" not in text.lower())
    assert unnamed == []


def test_the_one_composition_focus_says_nothing_about_passes():
    assert "pass" not in param_help("shift_high")


def test_a_pages_recommendation_stands_in_for_the_forms_own_advice():
    focus = ParamDef("shift_high", "Composition Focus", ParamType.FLOAT, 8.0, good=(5, 12))
    page = "With the Example Speed LoRA, its page recommends 5."
    assert definition_help(focus, page) == f"{PARAM_HELP['shift_high']} {page}"


def test_how_to_compare_two_step_spacings_stays_whatever_is_recommended():
    spacing = next(pd for pd in WORKFLOW_REGISTRY["sdxl_t2i"].param_definitions()
                   if pd.key == "scheduler")
    tip = definition_help(spacing, "dpmpp_2m works best with karras or exponential.")
    assert "To compare two, keep the seed and change only this" in tip


def test_a_definitions_good_range_is_said_in_its_tooltip():
    pd = ParamDef("mystery_number", "Mystery", ParamType.INT, 30, good=(20, 40))
    assert definition_help(pd) == "Good range: 20–40."


def test_a_durations_good_range_is_said_in_seconds():
    pd = ParamDef("frame_count", "Duration", ParamType.INT, 81, min_val=5, max_val=161, step=4,
                  unit="s", rate=16, good=(81, 161))
    assert " Good range: 5–10 s. " in definition_help(pd)
