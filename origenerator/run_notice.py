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
    display_name: str
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


def _title(outcome: RunOutcome) -> str | None:
    if outcome.kind == JobKind.TRAINING:
        return "LoRA ready" if outcome.ok else "Training failed"
    if outcome.kind == JobKind.VIDEO and outcome.source == GenerationSource.GENERATED:
        return f"{outcome.kind} {'ready' if outcome.ok else 'failed'}"
    return None


def notice_for(outcome: RunOutcome) -> Notice | None:
    title = _title(outcome)
    if title is None or outcome.seconds is None or outcome.seconds < LONG_RUN_SECONDS:
        return None
    took = clock_duration(outcome.seconds)
    body = f"{outcome.display_name} · {took}" if outcome.ok else f"{outcome.display_name} · stopped after {took}"
    return Notice(title, body, ok=outcome.ok, generation=outcome.generation)


def outcome_of_row(row: dict, *, ok: bool, seconds: float | None) -> RunOutcome:
    """What a run came to, read off its stored row rather than off a live job."""
    workflow_name = row.get("workflow_name") or ""
    workflow = WORKFLOW_REGISTRY.get(workflow_name)
    return RunOutcome(
        kind=job_kind_label(workflow_name),
        display_name=workflow.display_name if workflow is not None else workflow_name,
        seconds=seconds,
        ok=ok,
        source=source_of(row),
        generation=row.get("enhance_of") or row.get("prompt_id") or "",
    )
