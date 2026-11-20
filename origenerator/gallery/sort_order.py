from __future__ import annotations

from origenerator.gallery.output import media_type_of_row
from origenerator.media import MediaType

NEWEST = "newest"
OLDEST = "oldest"
LONGEST = "longest"
SHORTEST = "shortest"
_BY_DATE = (NEWEST, OLDEST)
_BY_DATE_OR_DURATION = (*_BY_DATE, LONGEST, SHORTEST)


def offered(rows: list[dict]) -> tuple[str, ...]:
    if any(media_type_of_row(row) == MediaType.VIDEO for row in rows):
        return _BY_DATE_OR_DURATION
    return _BY_DATE


def in_order(rows: list[dict], headings: list[str | None], sort: str
             ) -> tuple[list[dict], list[str | None]]:
    if sort == NEWEST:
        return list(rows), list(headings)
    sections = _sections(rows, headings)
    if sort == OLDEST:
        sections = [(heading, section[::-1]) for heading, section in reversed(sections)]
    else:
        sections = [(heading, sorted(section, key=_seconds, reverse=sort == LONGEST))
                    for heading, section in sections]
    return _flattened(sections)


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
