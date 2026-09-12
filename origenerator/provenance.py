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
from typing import NamedTuple

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


class _Launch(NamedTuple):
    launched: datetime
    finished: datetime
    version: str
    graph: tuple[str, ...]


def _graph_shape(workflow_json: str) -> tuple[str, ...]:
    return tuple(sorted(node.get("class_type", "")
                        for node in json.loads(workflow_json).values()))


def _launches(rows: list[dict]) -> dict[str, list[_Launch]]:
    launches: dict[str, list[_Launch]] = {}
    for row in rows:
        if row["workflow_version"] not in UNRECORDED_VERSIONS and not row["trimmed_from"]:
            launched = _moment(row["created_at"])
            launches.setdefault(row["workflow_name"], []).append(_Launch(
                launched, _moment(row["completed_at"]) or launched,
                row["workflow_version"], _graph_shape(row["workflow_json"])))
    return launches


def _block_for(row: dict, history, launches) -> dict | None:
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
    current = [(landed, version) for landed, version in landings if made and landed <= made]
    if not current:
        return _worked_out(workflow.name, None, None)
    landed_at, version = current[-1]
    ran = launches.get(workflow.name, [])
    if (_two_versions_in_use(landings, landed_at, made, ran)
            or _graph_only_ran_as_other_versions(_graph_shape(row["workflow_json"]), version, ran)):
        return _worked_out(workflow.name, None, None)
    return _worked_out(workflow.name, version, FILE_DATE)


def _two_versions_in_use(landings, landed_at: datetime, made: datetime,
                         launches: list[_Launch]) -> bool:
    older = {earlier for landed, earlier in landings if landed < landed_at}
    newer = {later for landed, later in landings if landed > landed_at}
    return any((launch.version in older and launch.finished >= made)
               or (launch.version in newer and launch.launched <= made)
               for launch in launches)


def _graph_only_ran_as_other_versions(shape: tuple[str, ...], version: str,
                                      launches: list[_Launch]) -> bool:
    ran_as = {launch.version for launch in launches if launch.graph == shape}
    return bool(shape) and bool(ran_as) and version not in ran_as


def _source_history(workflow) -> list[tuple[datetime, str]] | None:
    return version_history(Path(inspect.getsourcefile(type(workflow))))


def stamp_unstamped(db, *, history=_source_history) -> int:
    read: dict[str, list | None] = {}

    def landings(workflow):
        if workflow.name not in read:
            read[workflow.name] = history(workflow)
        return read[workflow.name]

    rows = db.list_generations()
    launches = _launches(rows)
    blocks = {}
    for row in rows:
        if row["provenance"] is None:
            block = _block_for(row, landings, launches)
            if block is not None:
                blocks[row["prompt_id"]] = json.dumps(block)
    db.set_provenance(blocks)
    return len(blocks)
