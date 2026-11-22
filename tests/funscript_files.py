from __future__ import annotations

from pathlib import Path

from app_support.funscript import document, write


def back_and_forth_actions(seconds: float, *, hz: float) -> list[dict]:
    span_ms = round(seconds * 1000)
    if span_ms <= 0 or hz <= 0:
        return []
    halves = 2 * max(1, round(seconds * hz))
    return [{"at": round(i * span_ms / halves), "pos": 0 if i % 2 == 0 else 100}
            for i in range(halves + 1)]


def write_funscript(path, actions: list[dict], *, duration_seconds: int | None = None) -> None:
    span = round(actions[-1]["at"] / 1000) if actions else 0
    write(Path(path), document(actions, duration_seconds=span if duration_seconds is None else duration_seconds,
                               creator="a test"))
