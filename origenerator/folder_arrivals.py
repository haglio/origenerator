from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

from origenerator.gallery.output import is_in_progress


class Arrivals(NamedTuple):
    to_star: list[str]
    to_enhance: list[dict]
    marks: dict[str, tuple[int | None, int | None]]


def _highest_id(rows: list[dict]) -> int:
    return max((row["id"] for row in rows), default=0)


def arrivals_in(leaves: dict[str, list[dict]], meta: dict[str, dict], *,
                would_enhance: Callable[[dict], bool], older_stars: bool = False) -> Arrivals:
    to_star: list[str] = []
    to_enhance: list[dict] = []
    marks: dict[str, tuple[int | None, int | None]] = {}
    for key, rows in leaves.items():
        held = meta.get(key) or {}
        starred_from = held.get("favorite_after_id") if held.get("starred") else None
        enhancing_from = held.get("enhance_after_id")
        favorite_mark, enhance_mark = starred_from, enhancing_from
        taken_up = older_stars and held.get("starred") and starred_from is None
        if starred_from is not None or taken_up:
            arrived = [row for row in rows if row["id"] > (starred_from or 0)]
            to_star += [row["prompt_id"] for row in arrived if not row.get("starred")]
            favorite_mark = max(starred_from or 0, _highest_id(arrived))
        if enhancing_from is not None:
            arrived = [row for row in rows if row["id"] > enhancing_from]
            waiting = [row["id"] for row in arrived if is_in_progress(row)]
            to_enhance += [row for row in arrived
                           if not is_in_progress(row) and would_enhance(row)]
            enhance_mark = (min(waiting) - 1 if waiting
                            else max(enhancing_from, _highest_id(arrived)))
        if (favorite_mark, enhance_mark) != (starred_from, enhancing_from):
            marks[key] = (favorite_mark, enhance_mark)
    return Arrivals(to_star, to_enhance, marks)
