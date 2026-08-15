"""Every workflow parameter explains itself, once, in one place.

The Generate form's fields carry tooltips drawn from a central map rather than
from each workflow's own definitions: the same key means the same thing in every
workflow that has it, so writing the explanation once is what keeps twelve
descriptions of ``cfg`` from drifting into twelve different claims.
"""

import pytest

from origenerator.gui.param_help import PARAM_HELP, param_help
from origenerator.workflows import WORKFLOW_REGISTRY


@pytest.mark.parametrize("workflow_name", list(WORKFLOW_REGISTRY))
def test_every_workflow_param_is_explained(workflow_name):
    # The guard: a new param must be explained before it can ship. Covers the
    # hidden ones too — the form renders those as read-only rows, and a row you
    # cannot change is the one you most want explained.
    wf = WORKFLOW_REGISTRY[workflow_name]
    keys = set(wf.default_params()) | {pd.key for pd in wf.param_definitions()}
    missing = sorted(k for k in keys if not param_help(k))
    assert missing == [], f"{workflow_name} params with no help: {missing}"


def test_an_unknown_param_has_no_help_rather_than_a_placeholder():
    # Qt shows no tooltip for an empty string, and an explanation that says
    # nothing is worse than no explanation at all.
    assert param_help("mystery_param") == ""


def test_help_reads_as_a_sentence_not_a_restatement_of_the_label():
    # The failure mode a tooltip pass invites: "Steps: the number of steps".
    for key, text in PARAM_HELP.items():
        assert len(text) > len(key) + 12, f"{key} says nothing its label doesn't"
        assert text[0].isupper(), f"{key} help should start as a sentence"


def test_the_knobs_the_enhance_panel_shows_are_all_explained():
    from origenerator.gallery import ENHANCE_SETTING_KEYS

    assert all(param_help(key) for key in ENHANCE_SETTING_KEYS)
