"""Every workflow parameter explains itself, once, in one place.

The Generate form's fields carry tooltips drawn from a central map rather than
from each workflow's own definitions: the same key means the same thing in every
workflow that has it, so writing the explanation once is what keeps twelve
descriptions of ``cfg`` from drifting into twelve different claims.
"""

import pytest

from origenerator.gallery import ENHANCE_SETTING_KEYS
from origenerator.gui import param_sections as ps
from origenerator.gui.param_help import PARAM_HELP, param_help
from origenerator.workflows import WORKFLOW_REGISTRY


@pytest.mark.parametrize("workflow_name", list(WORKFLOW_REGISTRY))
def test_every_workflow_param_a_surface_can_show_is_explained(workflow_name):
    # The guard: a new param must be explained before it can ship. Scoped to the
    # params a surface can actually put on screen, which is the same set
    # test_param_sections computes: the enhance keys are hidden from the form and
    # carried by the Enhance panel instead (checked below), and ps.HIDDEN_KEYS
    # get no row at all, editable or read-only. Help for one of those could never
    # be read, and requiring it is what put four unreachable tooltips here.
    wf = WORKFLOW_REGISTRY[workflow_name]
    keys = (set(wf.default_params()) | {pd.key for pd in wf.param_definitions()}) \
        - set(wf.enhance_keys()) - ps.HIDDEN_KEYS
    missing = sorted(k for k in keys if not param_help(k))
    assert missing == [], f"{workflow_name} params with no help: {missing}"


@pytest.mark.parametrize("workflow_name", list(WORKFLOW_REGISTRY))
def test_no_help_is_written_for_a_key_no_surface_can_show(workflow_name):
    # The other way round, so the four cannot come back: a line nobody can read
    # is a line that goes stale unnoticed, which is what the deleted `enhance`
    # entry had already done — it explained a checkbox the panel replaced.
    wf = WORKFLOW_REGISTRY[workflow_name]
    hidden = (set(wf.enhance_keys()) | ps.HIDDEN_KEYS) - set(ENHANCE_SETTING_KEYS)
    unreadable = sorted(k for k in hidden if param_help(k))
    assert unreadable == [], f"{workflow_name} help nothing can show: {unreadable}"


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
    assert all(param_help(key) for key in ENHANCE_SETTING_KEYS)
