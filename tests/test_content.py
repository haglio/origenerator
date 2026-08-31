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
