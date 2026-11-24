from __future__ import annotations

from origenerator.gallery.groups import rows_under
from origenerator.gallery.output import media_type_of_row
from origenerator.media import MediaType

LATEST = "latest"
OLDEST = "oldest"
LONGEST = "longest"
SHORTEST = "shortest"
_BY_DATE = (LATEST, OLDEST)
_BY_DATE_OR_DURATION = (*_BY_DATE, LONGEST, SHORTEST)


def offered(rows: list[dict]) -> tuple[str, ...]:
    if any(media_type_of_row(row) == MediaType.VIDEO for row in rows):
        return _BY_DATE_OR_DURATION
    return _BY_DATE


def applied(chosen: str, rows: list[dict]) -> str:
    return chosen if chosen in offered(rows) else LATEST


def in_order(rows: list[dict], headings: list[str | None], sort: str
             ) -> tuple[list[dict], list[str | None]]:
    if sort == LATEST:
        return list(rows), list(headings)
    if sort == OLDEST:
        return _flattened([(heading, section[::-1])
                           for heading, section in reversed(_sections(rows, headings))])
    return sorted(rows, key=_seconds, reverse=sort == LONGEST), [None] * len(rows)


def folders_in_order(folders: list, sort: str) -> list:
    return sorted(folders, key=_newest_made_in, reverse=sort != OLDEST)


def _newest_made_in(folder) -> str:
    return max((row.get("created_at") or "" for row in rows_under(folder)), default="")


def by_date(sort: str) -> bool:
    return sort in (LATEST, OLDEST)


def _seconds(row: dict) -> float:
    return row.get("video_seconds") or 0.0


def _sections(rows, headings) -> list[tuple[str | None, list[dict]]]:
    sections: list[tuple[str | None, list[dict]]] = []
    for index, (row, heading) in enumerate(zip(rows, headings, strict=True)):
        if index == 0 or heading:
            sections.append((heading, []))
        sections[-1][1].append(row)
    return sections


def _flattened(sections) -> tuple[list[dict], list[str | None]]:
    rows: list[dict] = []
    headings: list[str | None] = []
    for heading, section in sections:
        rows.extend(section)
        headings.extend([heading, *[None] * (len(section) - 1)])
    return rows, headings
