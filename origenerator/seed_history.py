from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from origenerator import gallery
from origenerator.workflows import WORKFLOW_REGISTRY


@dataclass(frozen=True)
class SeedUse:
    seed: int
    thumbnail: str | None
    size: tuple[int, int] | None = None


SeedHistory = Callable[[str], list[SeedUse]]


class SeedUseKind(StrEnum):
    DRAWN = "drawn"
    CANCELED = "canceled"
    FAILED = "failed"


def seed_history(rows, key: str, records=()) -> list[SeedUse]:
    records = [record for record in records if _role(record["seed_key"]) == _role(key)]
    used = [*_uses_in_rows(rows, key),
            *(_use_in(record) for record in records if record["kind"] != SeedUseKind.DRAWN)]
    last_used = {}
    for when, use in used:
        last_used[use.seed] = max(last_used.get(use.seed, ""), when)
    drawn = [(when, use) for when, use in (_use_in(record) for record in records
                                           if record["kind"] == SeedUseKind.DRAWN)
             if last_used.get(use.seed, "") < when]
    dated = sorted([*used, *drawn], key=lambda when_and_use: when_and_use[0], reverse=True)
    return [use for _when, use in dated]


def _uses_in_rows(rows, key: str):
    for row in rows:
        seed = _seed_in(row, key)
        if seed is None:
            continue
        if gallery.produced_output(row):
            yield row.get("created_at") or "", SeedUse(int(seed), row.get("thumbnail_path"))
        elif gallery.is_in_progress(row):
            size = output_size(row.get("workflow_name"),
                               gallery.parse_params(row.get("params_json")))
            yield row.get("created_at") or "", SeedUse(int(seed), None, size)


def _use_in(record: dict) -> tuple[str, SeedUse]:
    size = (record["width"], record["height"]) if record["width"] and record["height"] else None
    return record["created_at"], SeedUse(int(record["seed"]), record["thumbnail_path"], size)


def _role(key: str) -> str:
    return "seed" if key in gallery.GENERATION_SEED_KEYS else key


def _seed_in(row: dict, key: str):
    if _role(key) == "seed":
        return gallery.generation_seed(row)
    return gallery.parse_params(row.get("params_json")).get(key)


def output_size(workflow_name: str | None, params: dict) -> tuple[int, int] | None:
    if params.get("width") and params.get("height"):
        return int(params["width"]), int(params["height"])
    workflow = WORKFLOW_REGISTRY.get(workflow_name or "")
    return workflow.derived_display_size(params) if workflow is not None else None
