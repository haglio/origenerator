"""The content overlay: which file answers, and how often it is read.

Every value that describes the library rather than the code comes from here, so
`load_content` is called from five module scopes across four packages — and
before it was cached, importing `config` alone read and parsed the JSON, and
importing config plus search plus recipe_match plus workflows read the same file
six times over.

The count is a test rather than a comment because nothing else would show it:
six reads and one read behave identically, so the number can only go back up
silently.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from origenerator import content

REPO_ROOT = Path(__file__).resolve().parents[1]

# Instrument `Path.read_text` and the two stat calls, then import the modules
# that want the overlay, and report what the filesystem was asked for. In a
# fresh interpreter, because every one of these is an import-time cost and this
# one has already paid it.
_PROBE = """
import json
from pathlib import Path
import origenerator.content as content
content.LOCAL_CONTENT = content.EXAMPLE_CONTENT
content.load_content.cache_clear()

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
        cwd=REPO_ROOT, env=env, capture_output=True, text=True,
    )


def _import_in_a_fresh_interpreter(*modules) -> dict:
    result = _run_in_a_fresh_interpreter(
        _PROBE.format(imports="\n".join(f"import {m}" for m in modules)))
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_the_committed_example_answers_when_there_is_no_local_overlay(tmp_path):
    example = tmp_path / "content.example.json"
    example.write_text(json.dumps({"suite_root": "C:/example"}), encoding="utf-8")

    loaded = content.load_content(tmp_path / "content.local.json", example)

    assert loaded == {"suite_root": "C:/example"}


def test_the_local_overlay_answers_instead_when_it_is_there(tmp_path):
    local = tmp_path / "content.local.json"
    local.write_text(json.dumps({"suite_root": "D:/private"}), encoding="utf-8")
    example = tmp_path / "content.example.json"
    example.write_text(json.dumps({"suite_root": "C:/example"}), encoding="utf-8")

    assert content.load_content(local, example) == {"suite_root": "D:/private"}


def test_two_callers_are_not_handed_the_same_dictionary(tmp_path):
    """The read is cached; the parse is not. A shared dict would make one
    module's edit of the overlay every other module's edit of it — the
    cross-module mutable state this whole file exists to keep out."""
    example = tmp_path / "content.example.json"
    example.write_text(json.dumps({"suite_root": "C:/example"}), encoding="utf-8")
    local = tmp_path / "content.local.json"

    first = content.load_content(local, example)
    second = content.load_content(local, example)

    assert first == second
    assert first is not second


def test_the_overlay_is_read_once_however_many_modules_want_it():
    """Five module scopes across four packages ask for it, and twenty-four
    modules import `config` alone. One read."""
    seen = _import_in_a_fresh_interpreter(
        "origenerator.config", "origenerator.search",
        "origenerator.recipe_match", "origenerator.workflows")

    assert seen["overlay_reads"] == ["content.example.json"]


def test_a_workflow_imports_on_an_overlay_that_is_missing_what_it_wants(tmp_path):
    """`workflows/__init__` is imported by twelve modules, and reached the
    overlay at import through one workflow module\'s detector labels — with no
    .get and no try. The overlay replaces the committed example rather than
    merging with it, so an overlay written before `detector_labels` existed, or
    edited to drop it, took the whole app down with a bare KeyError: no window,
    and nothing said about which key or which file.

    The control on this is in tests/test_stroke_aim.py — the same overlay, read
    where the labels are actually used, still refuses.
    """
    incomplete = tmp_path / "content.local.json"
    complete = json.loads((REPO_ROOT / "content.example.json").read_text())
    complete.pop("detector_labels")
    incomplete.write_text(json.dumps(complete), encoding="utf-8")

    result = _run_in_a_fresh_interpreter(
        "from pathlib import Path",
        "import origenerator.content as content",
        f"content.LOCAL_CONTENT = Path({str(incomplete)!r})",
        "import origenerator.workflows",
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("module", ["origenerator.search", "origenerator.recipe_match"])
def test_a_consumer_of_the_overlay_does_not_read_it_at_import(module):
    """It reads `config`'s, which is the one read above; asking again at its own
    import is what made the count six."""
    seen = _import_in_a_fresh_interpreter(module)

    assert seen["overlay_reads"] == ["content.example.json"]


# --- the overlay is behind the app ---------------------------------------------
#
# `content.local.json` is hand-maintained and git-ignored, so it does not gain a
# key when the app does — and the committed example has gone from three keys to
# nine in six weeks. Each of those six additions is a launch where a local
# overlay written the day before is short of one, and three of the nine are read
# with a bare subscript, which used to be a dead icon and a traceback in a log
# nobody opens.


def test_a_local_overlay_missing_a_key_the_example_documents_is_named(tmp_path):
    complete = json.loads((REPO_ROOT / "content.example.json").read_text())
    local = tmp_path / "content.local.json"
    local.write_text(json.dumps(
        {k: v for k, v in complete.items() if k not in ("genau_source", "suite_root")}),
        encoding="utf-8")

    assert content.missing_overlay_keys(local, REPO_ROOT / "content.example.json") == (
        "genau_source", "suite_root")


def test_a_complete_overlay_is_missing_nothing(tmp_path):
    local = tmp_path / "content.local.json"
    local.write_text((REPO_ROOT / "content.example.json").read_text(), encoding="utf-8")

    assert content.missing_overlay_keys(
        local, REPO_ROOT / "content.example.json") == ()


def test_a_key_present_but_empty_is_not_missing(tmp_path):
    """How you switch a feature off: the key is there with nothing in it. Every
    consumer of an optional key already reads it as `.get(key) or default`."""
    example = tmp_path / "content.example.json"
    example.write_text(json.dumps({"suite_root": "C:/x", "search_synonyms": [["a"]]}),
                       encoding="utf-8")
    local = tmp_path / "content.local.json"
    local.write_text(json.dumps({"suite_root": "D:/y", "search_synonyms": []}),
                     encoding="utf-8")

    assert content.missing_overlay_keys(local, example) == ()


def test_no_local_overlay_at_all_is_missing_nothing(tmp_path):
    """A fresh or public checkout: the example is not compared against itself,
    it IS what loads."""
    example = tmp_path / "content.example.json"
    example.write_text(json.dumps({"suite_root": "C:/x"}), encoding="utf-8")

    assert content.missing_overlay_keys(tmp_path / "content.local.json", example) == ()


def test_the_comment_the_example_carries_is_not_a_key_to_copy(tmp_path):
    example = tmp_path / "content.example.json"
    example.write_text(json.dumps({"_comment": "what this file is", "suite_root": "C:/x"}),
                       encoding="utf-8")
    local = tmp_path / "content.local.json"
    local.write_text(json.dumps({"suite_root": "D:/y"}), encoding="utf-8")

    assert content.missing_overlay_keys(local, example) == ()


def test_this_repos_own_example_is_what_a_local_overlay_is_measured_against():
    """No second list to keep in step: the file that documents the shape is the
    one the check reads, so a key added to it is a key the overlay must carry."""
    documented = {k for k in json.loads(
        (REPO_ROOT / "content.example.json").read_text()) if k != "_comment"}

    assert documented == {
        "suite_root", "ambient_audio_dir", "genau_source", "recipe_categories",
        "combine_recipes", "search_synonyms", "genau_recipes", "detail_fix_parts",
        "detector_labels",
    }
