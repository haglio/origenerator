from __future__ import annotations

from dataclasses import dataclass

from origenerator.gallery import JobKind, job_kind_label
from origenerator.generation_state import GenerationSource, source_of
from origenerator.timing import clock_duration
from origenerator.workflows import WORKFLOW_REGISTRY

LONG_RUN_SECONDS = 60


@dataclass(frozen=True)
class RunOutcome:
    """What a run came to, for whoever reports on it rather than redraws for it.

    ``seconds`` is the run itself, never the wait in the line before it.
    """

    kind: str
    recipe: str
    seconds: float | None
    ok: bool
    source: str
    generation: str


@dataclass(frozen=True)
class Notice:
    title: str
    body: str
    ok: bool
    generation: str


def notice_for(outcome: RunOutcome) -> Notice | None:
    if outcome.kind != JobKind.VIDEO:
        return None
    if outcome.source != GenerationSource.GENERATED:
        return None
    if outcome.seconds is None or outcome.seconds < LONG_RUN_SECONDS:
        return None
    took = clock_duration(outcome.seconds)
    if outcome.ok:
        return Notice(f"{outcome.kind} ready", f"{outcome.recipe} · {took}", ok=True,
                      generation=outcome.generation)
    return Notice(f"{outcome.kind} failed",
                  f"{outcome.recipe} · stopped after {took}", ok=False,
                  generation=outcome.generation)


def outcome_of_row(row: dict, *, ok: bool, seconds: float | None) -> RunOutcome:
    """What a run came to, read off its stored row rather than off a live job."""
    workflow_name = row.get("workflow_name") or ""
    workflow = WORKFLOW_REGISTRY.get(workflow_name)
    return RunOutcome(
        kind=job_kind_label(workflow_name),
        recipe=workflow.display_name if workflow is not None else workflow_name,
        seconds=seconds,
        ok=ok,
        source=source_of(row),
        generation=row.get("enhance_of") or row.get("prompt_id") or "",
    )
