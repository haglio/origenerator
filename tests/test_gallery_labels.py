from __future__ import annotations

from origenerator.gallery.labels import ENHANCE_WORKFLOW, job_kind_label


def test_an_enhance_is_a_kind_of_job_of_its_own():
    assert job_kind_label(ENHANCE_WORKFLOW) == "Enhance"


def test_a_workflow_this_build_does_not_have_registered_has_no_kind():
    assert job_kind_label("no_such_workflow") == ""
    assert job_kind_label(None) == ""
