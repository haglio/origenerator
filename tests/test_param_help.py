"""Every workflow parameter explains itself, once, in one place.

The Generate form's fields carry tooltips drawn from a central map rather than
from each workflow's own definitions: the same key means the same thing in every
workflow that has it, so writing the explanation once is what keeps twelve
descriptions of ``cfg`` from drifting into twelve different claims.
"""
from __future__ import annotations

import pytest

from origenerator.gallery import ENHANCE_SETTING_KEYS
from origenerator.gui.param_help import PARAM_HELP, param_help
from origenerator.workflows import WORKFLOW_REGISTRY


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
