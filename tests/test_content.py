from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from origenerator import content

REPO_ROOT = Path(__file__).resolve().parents[1]

_PROBE = """
import json
from pathlib import Path
import origenerator.content as content
content.LOCAL_CONTENT = content.EXAMPLE_CONTENT

reads, probes = [], []
_read, _is_dir = Path.read_text, Path.is_dir
Path.read_text = lambda self, *a, **k: (reads.append(self.name), _read(self, *a, **k))[1]
Path.is_dir = lambda self: (probes.append(str(self)), _is_dir(self))[1]

{imports}

Path.read_text, Path.is_dir = _read, _is_dir
print(json.dumps({{
    "overlay_reads": [r for r in reads if r.startswith("content.")],
    "probes": probes,
}}))
"""


def _run_in_a_fresh_interpreter(*statements) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(REPO_ROOT), os.environ.get("PYTHONPATH", "")) if p)
    return subprocess.run(
        [sys.executable, "-c", "\n".join(statements)],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=False,
    )


def _import_in_a_fresh_interpreter(*modules) -> dict:
    result = _run_in_a_fresh_interpreter(
        _PROBE.format(imports="\n".join(f"import {m}" for m in modules)))
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_the_committed_example_answers_when_there_is_no_local_overlay(tmp_path):
    example = tmp_path / "content.example.json"
    example.write_text(json.dumps({"library_root": "C:/example"}), encoding="utf-8")

    loaded = content.load_content(tmp_path / "content.local.json", example)

    assert loaded == {"library_root": "C:/example"}


def test_the_local_overlay_answers_instead_when_it_is_there(tmp_path):
    local = tmp_path / "content.local.json"
    local.write_text(json.dumps({"library_root": "D:/private"}), encoding="utf-8")
    example = tmp_path / "content.example.json"
    example.write_text(json.dumps({"library_root": "C:/example"}), encoding="utf-8")

    assert content.load_content(local, example) == {"library_root": "D:/private"}


def test_the_local_overlay_is_not_merged_over_the_example(tmp_path):
    local = tmp_path / "content.local.json"
    local.write_text(json.dumps({"library_root": "D:/private"}), encoding="utf-8")
    example = tmp_path / "content.example.json"
    example.write_text(json.dumps({"library_root": "C:/example", "extra": 1}), encoding="utf-8")

    assert "extra" not in content.load_content(local, example)


def test_two_callers_are_not_handed_the_same_dictionary(tmp_path):
    example = tmp_path / "content.example.json"
    example.write_text(json.dumps({"library_root": "C:/example"}), encoding="utf-8")
    local = tmp_path / "content.local.json"

    first = content.load_content(local, example)
    second = content.load_content(local, example)

    assert first == second
    assert first is not second


def test_the_overlay_is_read_once_however_many_modules_want_it():
    seen = _import_in_a_fresh_interpreter(
        "origenerator.config", "origenerator.search",
        "origenerator.action_settings", "origenerator.workflows")

    assert seen["overlay_reads"] == ["content.example.json"]


def test_a_workflow_imports_on_an_overlay_that_is_missing_what_it_wants(tmp_path):
    incomplete = tmp_path / "content.local.json"
    complete = json.loads((REPO_ROOT / "content.example.json").read_text())
    complete.pop("detail_fix_parts")
    incomplete.write_text(json.dumps(complete), encoding="utf-8")

    result = _run_in_a_fresh_interpreter(
        "from pathlib import Path",
        "import origenerator.content as content",
        f"content.LOCAL_CONTENT = Path({str(incomplete)!r})",
        "import origenerator.workflows",
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("module", ["origenerator.search", "origenerator.action_settings"])
def test_a_consumer_of_the_overlay_does_not_read_it_at_import(module):
    seen = _import_in_a_fresh_interpreter(module)

    assert seen["overlay_reads"] == ["content.example.json"]



def test_a_local_overlay_missing_a_key_the_example_documents_is_named(tmp_path):
    complete = json.loads((REPO_ROOT / "content.example.json").read_text())
    local = tmp_path / "content.local.json"
    local.write_text(json.dumps(
        {k: v for k, v in complete.items() if k not in ("detail_fix_parts", "speech_python")}),
        encoding="utf-8")

    assert content.missing_overlay_keys(local, REPO_ROOT / "content.example.json") == (
        "detail_fix_parts", "speech_python"), (
        "every key the example documents is named when it is missing, even one the app could "
        "start without, so the launch can stop on it: a feature that quietly goes without its "
        "key reads as the model having a bad day")


def test_a_complete_overlay_is_missing_nothing(tmp_path):
    local = tmp_path / "content.local.json"
    local.write_text((REPO_ROOT / "content.example.json").read_text(), encoding="utf-8")

    assert content.missing_overlay_keys(
        local, REPO_ROOT / "content.example.json") == ()


def test_a_key_left_empty_to_switch_its_feature_off_is_not_missing(tmp_path):
    example = tmp_path / "content.example.json"
    example.write_text(json.dumps({"library_root": "C:/x", "search_synonyms": [["a"]]}),
                       encoding="utf-8")
    local = tmp_path / "content.local.json"
    local.write_text(json.dumps({"library_root": "D:/y", "search_synonyms": []}),
                     encoding="utf-8")

    assert content.missing_overlay_keys(local, example) == (), (
        "a key left empty is how its feature is switched off, so it is not named as missing")


def test_no_local_overlay_at_all_is_missing_nothing(tmp_path):
    example = tmp_path / "content.example.json"
    example.write_text(json.dumps({"library_root": "C:/x"}), encoding="utf-8")

    assert content.missing_overlay_keys(tmp_path / "content.local.json", example) == ()


def test_the_comment_the_example_carries_is_not_a_key_to_copy(tmp_path):
    example = tmp_path / "content.example.json"
    example.write_text(json.dumps({"_comment": "what this file is", "library_root": "C:/x"}),
                       encoding="utf-8")
    local = tmp_path / "content.local.json"
    local.write_text(json.dumps({"library_root": "D:/y"}), encoding="utf-8")

    assert content.missing_overlay_keys(local, example) == ()


def test_this_repos_own_example_is_what_a_local_overlay_is_measured_against():
    documented = {k for k in json.loads(
        (REPO_ROOT / "content.example.json").read_text()) if k != "_comment"}

    assert documented == {
        "speech_python", "lora_training_python", "lora_training_scripts",
        "krea2_training_python", "krea2_training_scripts", "trainable_loras",
        "pinned_kino_settings", "search_synonyms",
        "pinned_genau_settings", "detail_fix_parts", "genau_flick_prompts",
        "genau_finale_checkbox",
        "model_recommendations",
        "image_actions", "video_actions", "site_words", "display_names",
    }


def test_the_pyproject_says_the_launch_needs_every_key_of_the_example_in_the_local_overlay():
    declared = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "tool"]["haglio"]["opens-only-with"]

    compared = _run_in_a_fresh_interpreter(
        "import origenerator.content as content",
        "print(content.EXAMPLE_CONTENT)",
        "print(content.LOCAL_CONTENT)",
    )

    assert compared.returncode == 0, compared.stderr
    assert [REPO_ROOT / declared["every-key-of"], REPO_ROOT / declared["in"]] == [
        Path(line) for line in compared.stdout.splitlines()]


def test_an_overlay_written_before_the_pins_were_renamed_reads_under_the_new_names(tmp_path):
    example = tmp_path / "content.example.json"
    example.write_text(json.dumps({"pinned_kino_settings": {},
                                   "pinned_genau_settings": {}}), encoding="utf-8")
    local = tmp_path / "content.local.json"
    local.write_text(json.dumps({"combine_recipes": {"alpha": {"workflow": "wan22_i2v"}},
                                 "genau_recipes": {}}), encoding="utf-8")

    loaded = content.load_content(local, example)

    assert loaded["pinned_kino_settings"] == {"alpha": {"workflow": "wan22_i2v"}}
    assert loaded["pinned_genau_settings"] == {}
    assert content.missing_overlay_keys(local, example) == ()


def test_a_preview_without_an_overlay_of_its_own_reads_the_production_checkouts(tmp_path):
    preview, production = tmp_path / "preview", tmp_path / "production"
    preview.mkdir(), production.mkdir()

    assert content.local_overlay(preview, production) == production / "content.local.json"


def test_a_preview_with_an_overlay_of_its_own_reads_that_one(tmp_path):
    preview, production = tmp_path / "preview", tmp_path / "production"
    preview.mkdir(), production.mkdir()
    (preview / "content.local.json").write_text("{}", encoding="utf-8")

    assert content.local_overlay(preview, production) == preview / "content.local.json"


def test_a_copy_that_is_no_preview_reads_only_its_own_overlay(tmp_path):
    assert content.local_overlay(tmp_path, None) == tmp_path / "content.local.json"
