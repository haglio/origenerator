from __future__ import annotations

import inspect
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from origenerator import provenance
from origenerator.db import Database
from origenerator.workflows import WORKFLOW_REGISTRY

# When each version of a workflow landed, as its file's history would say.
LANDED = [(datetime(2026, 4, 1, tzinfo=UTC), "v002"),
          (datetime(2026, 6, 1, tzinfo=UTC), "v003")]


def _history(landed=LANDED):
    return lambda workflow: landed


def _launched(db, prompt_id, *, workflow="sdxl_t2i", version="v003", **fields):
    db.insert_generation(prompt_id=prompt_id, workflow_name=workflow,
                         workflow_version=version, params_json="{}", workflow_json="{}",
                         **fields)


def _file(path):
    subfolder, _, filename = path.rpartition("/")
    return {"filename": filename, "subfolder": subfolder}


def _imported(db, prompt_id, *, workflow="sdxl_t2i", file="image/sdxl_t2i_00001_.png",
              completed_at="2026-05-01T12:00:00+00:00", enhanced_from=None,
              version="imported", graph=None):
    db.insert_generation(prompt_id=prompt_id, workflow_name=workflow,
                         workflow_version=version, params_json="{}",
                         workflow_json=json.dumps(graph or {}), source="imported")
    files = [_file(file)]
    folded = {}
    if enhanced_from:
        files.append(_file(enhanced_from))
        folded["original_files"] = json.dumps([_file(enhanced_from)])
    db.update_generation(prompt_id, status="completed", completed_at=completed_at,
                         output_files=json.dumps(files), **folded)


def _ran(db, prompt_id, version, *, launched, finished, trimmed_from=None, graph=None):
    db.restore_generation({
        "prompt_id": prompt_id, "source": "generated", "workflow_name": "sdxl_t2i",
        "workflow_version": version, "status": "completed", "params_json": "{}",
        "workflow_json": json.dumps(graph or {}), "created_at": launched,
        "completed_at": finished,
        "trimmed_from": trimmed_from,
        "provenance": json.dumps({"recipe": "sdxl_t2i", "recipe_version": version})})


def _block(db, prompt_id):
    return json.loads(db.get_generation(prompt_id)["provenance"])


def _known(block):
    return block["recipe"], block["recipe_version"], block["recipe_version_basis"]


def test_a_row_launched_before_stamping_is_stamped_with_the_version_it_recorded(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    _launched(db, "gen-alpha", version="v003")

    provenance.stamp_unstamped(db)

    block = _block(db, "gen-alpha")
    assert (block["recipe"], block["recipe_version"], block["recipe_version_basis"],
            block["app_commit"]) == ("sdxl_t2i", "v003", "recorded", None)


def test_a_row_its_launch_stamped_keeps_that_stamp(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    stamped = json.dumps({"recipe": "sdxl_t2i", "recipe_version": "v004",
                          "app_commit": "c0ffee"})
    _launched(db, "gen-beta", version="v004", provenance=stamped)

    provenance.stamp_unstamped(db)

    assert db.get_generation("gen-beta")["provenance"] == stamped


def test_a_block_worked_out_later_has_every_key_a_launch_stamp_has(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    _launched(db, "gen-gamma")

    provenance.stamp_unstamped(db)

    assert set(_block(db, "gen-gamma")) == set(
        provenance.at_launch(WORKFLOW_REGISTRY["sdxl_t2i"]))


def test_an_import_no_workflow_claims_is_made_by_nothing_known(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    _imported(db, "imp-alpha", workflow="unknown", file="image/scene_one_00001_.png")

    provenance.stamp_unstamped(db)

    assert _known(_block(db, "imp-alpha")) == (None, None, None)


def test_an_import_takes_the_version_its_workflow_was_on_when_the_file_was_made(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    _imported(db, "imp-beta", file="image/sdxl_t2i_00007_.png",
              completed_at="2026-05-01T12:00:00+00:00")

    provenance.stamp_unstamped(db, history=_history())

    assert _known(_block(db, "imp-beta")) == ("sdxl_t2i", "v002", "file_date")


def test_an_import_older_than_its_workflow_gets_no_version_rather_than_the_first(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    _imported(db, "imp-gamma", completed_at="2026-03-01T12:00:00+00:00")

    provenance.stamp_unstamped(db, history=_history())

    assert _known(_block(db, "imp-gamma")) == ("sdxl_t2i", None, None)


def test_an_import_with_no_file_date_gets_no_version_and_the_rest_are_still_stamped(
        tmp_path):
    db = Database(tmp_path / "origenerator.db")
    _imported(db, "imp-mu", completed_at=None)
    _imported(db, "imp-nu", file="image/sdxl_t2i_00002_.png")

    provenance.stamp_unstamped(db, history=_history())

    assert (_known(_block(db, "imp-mu")), _known(_block(db, "imp-nu"))) == (
        ("sdxl_t2i", None, None), ("sdxl_t2i", "v002", "file_date"))


def test_an_import_made_while_the_old_version_was_still_being_launched_gets_no_version(
        tmp_path):
    db = Database(tmp_path / "origenerator.db")
    _ran(db, "gen-old", "v002", launched="2026-06-03 00:00:00",
         finished="2026-06-03T00:10:00+00:00")
    _imported(db, "imp-during", completed_at="2026-06-02T12:00:00+00:00")
    _imported(db, "imp-after", file="image/sdxl_t2i_00002_.png",
              completed_at="2026-06-10T12:00:00+00:00")

    provenance.stamp_unstamped(db, history=_history())

    assert (_known(_block(db, "imp-during")), _known(_block(db, "imp-after"))) == (
        ("sdxl_t2i", None, None), ("sdxl_t2i", "v003", "file_date"))


def test_an_import_made_after_a_preview_began_launching_the_next_version_gets_no_version(
        tmp_path):
    db = Database(tmp_path / "origenerator.db")
    _ran(db, "gen-early", "v003", launched="2026-05-30 00:00:00",
         finished="2026-05-30T00:10:00+00:00")
    _imported(db, "imp-before", completed_at="2026-05-20T12:00:00+00:00")
    _imported(db, "imp-between", file="image/sdxl_t2i_00002_.png",
              completed_at="2026-05-31T12:00:00+00:00")

    provenance.stamp_unstamped(db, history=_history())

    assert (_known(_block(db, "imp-before")), _known(_block(db, "imp-between"))) == (
        ("sdxl_t2i", "v002", "file_date"), ("sdxl_t2i", None, None))


def test_a_clip_cut_later_from_an_older_run_is_not_a_launch_of_that_version(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    _ran(db, "gen-cut", "v002", launched="2026-06-05 00:00:00",
         finished="2026-06-05T00:00:05+00:00", trimmed_from="gen-source")
    _imported(db, "imp-omicron", completed_at="2026-06-02T12:00:00+00:00")

    provenance.stamp_unstamped(db, history=_history())

    assert _known(_block(db, "imp-omicron")) == ("sdxl_t2i", "v003", "file_date")


PLAIN = {"1": {"class_type": "KSampler", "inputs": {}},
         "2": {"class_type": "SaveImage", "inputs": {}}}
UPSCALED = {"1": {"class_type": "KSampler", "inputs": {}},
            "2": {"class_type": "UpscaleModelLoader", "inputs": {}},
            "3": {"class_type": "SaveImage", "inputs": {}}}


def test_an_import_whose_graph_only_ever_ran_under_another_version_gets_no_version(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    _ran(db, "gen-plain", "v002", launched="2026-05-01 00:00:00",
         finished="2026-05-01T00:00:08+00:00", graph=PLAIN)
    _ran(db, "gen-upscaled", "v003", launched="2026-06-20 00:00:00",
         finished="2026-06-20T00:00:08+00:00", graph=UPSCALED)
    _imported(db, "imp-plain", completed_at="2026-06-10T12:00:00+00:00", graph=PLAIN)
    _imported(db, "imp-upscaled", file="image/sdxl_t2i_00002_.png",
              completed_at="2026-06-10T12:00:00+00:00", graph=UPSCALED)

    provenance.stamp_unstamped(db, history=_history())

    assert (_known(_block(db, "imp-plain")), _known(_block(db, "imp-upscaled"))) == (
        ("sdxl_t2i", None, None), ("sdxl_t2i", "v003", "file_date"))


def test_an_import_whose_graph_never_ran_here_keeps_the_version_its_date_gives(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    _ran(db, "gen-plain", "v002", launched="2026-05-01 00:00:00",
         finished="2026-05-01T00:00:08+00:00", graph=PLAIN)
    _imported(db, "imp-rho", completed_at="2026-06-10T12:00:00+00:00", graph=UPSCALED)

    provenance.stamp_unstamped(db, history=_history())

    assert _known(_block(db, "imp-rho")) == ("sdxl_t2i", "v003", "file_date")


def test_a_file_with_no_graph_in_it_is_no_evidence_either_way(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    _ran(db, "gen-bare", "v002", launched="2026-05-01 00:00:00",
         finished="2026-05-01T00:00:08+00:00")
    _imported(db, "imp-sigma", completed_at="2026-06-10T12:00:00+00:00")

    provenance.stamp_unstamped(db, history=_history())

    assert _known(_block(db, "imp-sigma")) == ("sdxl_t2i", "v003", "file_date")


def test_an_import_saved_under_another_name_is_not_credited_to_the_workflow_it_sits_under(
        tmp_path):
    db = Database(tmp_path / "origenerator.db")
    _imported(db, "imp-delta", file="image/example_blend_00003_.png")

    provenance.stamp_unstamped(db, history=_history())

    assert _known(_block(db, "imp-delta")) == (None, None, None)


def test_the_workflows_name_in_some_other_folder_is_not_its_own_name(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    _imported(db, "imp-epsilon", file="elsewhere/sdxl_t2i_00002_.png")

    provenance.stamp_unstamped(db, history=_history())

    assert _known(_block(db, "imp-epsilon")) == (None, None, None)


def test_a_clip_saved_with_its_sound_still_carries_its_workflows_own_name(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    _imported(db, "imp-zeta", workflow="wan22_flf2v_loop",
              file="video/flf2v_loop_00012-audio.mp4")

    provenance.stamp_unstamped(db, history=_history())

    assert _known(_block(db, "imp-zeta")) == ("wan22_flf2v_loop", "v002", "file_date")


def test_an_enhanced_import_is_judged_by_its_original_not_the_enhancement_on_top(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    _imported(db, "imp-eta", file="image/image_enhance_00009_.png",
              enhanced_from="image/sdxl_t2i_00004_.png")

    provenance.stamp_unstamped(db, history=_history())

    assert _known(_block(db, "imp-eta")) == ("sdxl_t2i", "v002", "file_date")


def test_the_older_imports_placeholder_is_not_taken_for_a_version_either(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    _imported(db, "imp-theta", version="unknown")

    provenance.stamp_unstamped(db, history=_history())

    assert _known(_block(db, "imp-theta")) == ("sdxl_t2i", "v002", "file_date")


def test_an_import_whose_workflow_history_cannot_be_read_waits_for_the_next_launch(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    _imported(db, "imp-iota")

    stamped = provenance.stamp_unstamped(db, history=lambda workflow: None)

    assert (stamped, db.get_generation("imp-iota")["provenance"]) == (0, None)


def test_a_workflows_history_is_read_once_however_many_imports_it_made(tmp_path):
    db = Database(tmp_path / "origenerator.db")
    for n in range(3):
        _imported(db, f"imp-kappa-{n}", file=f"image/sdxl_t2i_0000{n}_.png")
    asked = []

    provenance.stamp_unstamped(
        db, history=lambda workflow: asked.append(workflow.name) or LANDED)

    assert asked == ["sdxl_t2i"]


def test_a_workflows_history_is_the_history_of_the_file_that_declares_it(
        tmp_path, monkeypatch):
    db = Database(tmp_path / "origenerator.db")
    _imported(db, "imp-lambda")
    asked = []
    monkeypatch.setattr(provenance, "version_history",
                        lambda source: asked.append(source) or LANDED)

    provenance.stamp_unstamped(db)

    assert asked == [Path(inspect.getsourcefile(type(WORKFLOW_REGISTRY["sdxl_t2i"])))]


# --- a workflow's history, read from git ---------------------------------------

_IDENTITY = ("-c", "user.email=test@example.com", "-c", "user.name=Test")


def _checkout(tmp_path):
    repo = tmp_path / "checkout"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    return repo


def _commit(repo, version, *, committed, authored=None, note=""):
    (repo / "alpha_workflow.py").write_text(
        f'class AlphaWorkflow:\n{note}    version = "{version}"\n', encoding="utf-8")
    env = {**os.environ, "GIT_COMMITTER_DATE": committed,
           "GIT_AUTHOR_DATE": authored or committed}
    for args in (("add", "-A"), ("commit", "-qm", f"alpha at {version}")):
        subprocess.run(["git", "-C", str(repo), *_IDENTITY, *args], check=True, env=env)


def test_a_workflows_versions_are_read_from_its_files_history_as_they_landed(tmp_path):
    repo = _checkout(tmp_path)
    _commit(repo, "v001", committed="2026-01-05T10:00:00+00:00")
    _commit(repo, "v002", committed="2026-02-05T10:00:00+00:00")
    _commit(repo, "v002", committed="2026-03-05T10:00:00+00:00", note="    title = 'Alpha'\n")

    assert provenance.version_history(repo / "alpha_workflow.py") == [
        (datetime(2026, 1, 5, 10, tzinfo=UTC), "v001"),
        (datetime(2026, 2, 5, 10, tzinfo=UTC), "v002"),
    ]


def test_a_version_is_dated_by_when_it_landed_not_when_it_was_written(tmp_path):
    repo = _checkout(tmp_path)
    _commit(repo, "v001", committed="2026-01-05T10:00:00+00:00")
    _commit(repo, "v002", authored="2026-01-20T10:00:00+00:00",
            committed="2026-02-05T10:00:00+00:00")

    landed = dict(reversed(pair) for pair in provenance.version_history(
        repo / "alpha_workflow.py"))

    assert landed["v002"] == datetime(2026, 2, 5, 10, tzinfo=UTC)


def test_a_file_outside_any_checkout_has_no_history_rather_than_an_empty_one(
        tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    loose = tmp_path / "alpha_workflow.py"
    loose.write_text('class AlphaWorkflow:\n    version = "v001"\n', encoding="utf-8")

    assert provenance.version_history(loose) is None


@pytest.mark.parametrize("name", sorted(WORKFLOW_REGISTRY))
def test_every_workflow_declares_its_version_in_a_form_its_history_can_find(name, tmp_path):
    workflow = WORKFLOW_REGISTRY[name]
    source = Path(inspect.getsourcefile(type(workflow)))
    repo = _checkout(tmp_path)
    copy = repo / source.name
    copy.write_bytes(source.read_bytes())
    for args in (("add", "-A"), ("commit", "-qm", "as it is today")):
        subprocess.run(["git", "-C", str(repo), *_IDENTITY, *args], check=True)

    assert [version for _landed, version in provenance.version_history(copy)] == [
        workflow.version]
