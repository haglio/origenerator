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
from origenerator.gui.param_help import PARAM_HELP, option_help, param_help
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.base import SAMPLER_OPTIONS


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


@pytest.mark.parametrize("key", ["shift", "shift_high"])
def test_composition_focus_says_what_composition_is(key):
    assert "layout" in PARAM_HELP[key]


def test_the_handoff_says_when_to_move_it_off_halfway():
    assert "motion" in PARAM_HELP["split_step"] and "detail" in PARAM_HELP["split_step"]


def test_help_calls_a_lora_a_lora():
    loras = ("lora_high", "lora_low", "lora_strength_high", "lora_strength_low")
    assert all("LoRA" in PARAM_HELP[key] for key in loras)
    assert [key for key, text in PARAM_HELP.items() if "add-on" in text.lower()] == []


def test_every_sampler_says_how_it_works_and_how_long_it_takes():
    unexplained = [name for name in SAMPLER_OPTIONS
                   if "per step" not in option_help("sampler_name", name)]
    assert unexplained == []
