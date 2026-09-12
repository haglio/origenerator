"""What made each generation, kept on its row so a later change can find
everything made before it and remake it.

The block is the family's stamp (:mod:`app_support.provenance`) with the
workflow as its recipe, plus one key of this app's own saying how the recipe
version came to be known.
"""
from __future__ import annotations

import inspect
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from app_support import provenance as family
from app_support.subprocess_utils import hidden_subprocess_kwargs

from origenerator import gallery
from origenerator.workflows import UNRECORDED_VERSIONS, WORKFLOW_REGISTRY

APP = "origenerator"
BASIS = "recipe_version_basis"
RECORDED = "recorded"
FILE_DATE = "file_date"

_GIT_TIMEOUT_SECONDS = 10
_VERSION_SET = re.compile(r'^\+\s+version = "(v\d+)"', re.MULTILINE)


def version_history(source: Path) -> list[tuple[datetime, str]] | None:
    try:
        done = subprocess.run(
            ["git", "-C", str(source.parent), "log", "--format=%x00%cI", "-p", "-U0",
             "--no-color", "--no-ext-diff", "-G", '^[[:space:]]+version = "v',
             "--", source.name],
            capture_output=True, encoding="utf-8", errors="replace", check=True,
            timeout=_GIT_TIMEOUT_SECONDS, **hidden_subprocess_kwargs())
    except (OSError, subprocess.SubprocessError):
        return None
    landed = []
    for commit in done.stdout.split("\0")[1:]:
        when, _, patch = commit.partition("\n")
        version = _VERSION_SET.search(patch)
        if version:
            landed.append((datetime.fromisoformat(when.strip()), version.group(1)))
    return sorted(landed)


def at_launch(workflow) -> dict:
    return {**family.stamp(APP, anchor=__file__, recipe=workflow.name,
                           recipe_version=workflow.version),
            BASIS: RECORDED}


def _worked_out(recipe: str | None, version: str | None, basis: str | None) -> dict:
    return {"schema": family.SCHEMA, "app": APP, "app_commit": None, "app_dirty": None,
            "recipe": recipe, "recipe_version": version,
            "stamped_at": datetime.now(UTC).isoformat(), BASIS: basis}


def _moment(text: str | None) -> datetime | None:
    if text is None:
        return None
    moment = datetime.fromisoformat(text)
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _saved_under_its_own_name(workflow, file: dict) -> bool:
    folder, _, stem = workflow.default_params().get("filename_prefix", "").rpartition("/")
    return (file.get("subfolder") or "") == folder and re.fullmatch(
        re.escape(stem) + r"_\d+_?(?:-audio)?\.\w+", file.get("filename") or "") is not None


def _block_for(row: dict, history) -> dict | None:
    if row["workflow_version"] not in UNRECORDED_VERSIONS:
        return _worked_out(row["workflow_name"], row["workflow_version"], RECORDED)
    workflow = WORKFLOW_REGISTRY.get(row["workflow_name"])
    files = gallery.original_files_of(row) or gallery.row_output_files(row)
    if workflow is None or not files or not _saved_under_its_own_name(workflow, files[0]):
        return _worked_out(None, None, None)
    landings = history(workflow)
    if landings is None:
        return None
    made = _moment(row["completed_at"])
    versions = [version for landed, version in landings if made and landed <= made]
    if not versions:
        return _worked_out(workflow.name, None, None)
    return _worked_out(workflow.name, versions[-1], FILE_DATE)


def _source_history(workflow) -> list[tuple[datetime, str]] | None:
    return version_history(Path(inspect.getsourcefile(type(workflow))))


def stamp_unstamped(db, *, history=_source_history) -> int:
    read: dict[str, list | None] = {}

    def landings(workflow):
        if workflow.name not in read:
            read[workflow.name] = history(workflow)
        return read[workflow.name]

    blocks = {}
    for row in db.list_generations():
        if row["provenance"] is None:
            block = _block_for(row, landings)
            if block is not None:
                blocks[row["prompt_id"]] = json.dumps(block)
    db.set_provenance(blocks)
    return len(blocks)
