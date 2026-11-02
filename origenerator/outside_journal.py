from __future__ import annotations

import json
from pathlib import Path


def said_in(journal: Path | None) -> list[dict]:
    try:
        lines = journal.read_text(encoding="utf-8").splitlines() if journal else []
    except OSError:
        return []
    said = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if (isinstance(event, dict) and isinstance(event.get("path"), str)
                and isinstance(event.get("t"), int | float)):
            said.append(event)
    return said


def favorites_in(said: list[dict]) -> dict[str, float]:
    told: dict[str, float] = {}
    for event in said:
        if event.get("event") in ("favorite", "unfavorite"):
            told[event["path"]] = max(told.get(event["path"], 0), event["t"] / 1000)
    return told


def actions_in(said: list[dict]) -> dict[str, tuple[float, str]]:
    picks = sorted((event for event in said if event.get("event") == "action"),
                   key=lambda event: event["t"])
    return {event["path"]: (event["t"] / 1000, str(event.get("action") or "")) for event in picks}
