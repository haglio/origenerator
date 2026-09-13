from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, tzinfo
from itertools import accumulate

BREAK_BETWEEN_SECTIONS = timedelta(hours=2)

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def section_headings(rows, *, zone: tzinfo | None = None,
                     today: date | None = None) -> list[str | None]:
    stamps = [row.get("created_at") for row in rows]
    if not all(stamps):
        return [None] * len(rows)
    if today is None:
        today = datetime.now(UTC).astimezone(zone).date()
    made = [datetime.fromisoformat(stamp).replace(tzinfo=UTC).astimezone(zone)
            for stamp in stamps]
    placed = list(accumulate(reversed(made), max))[::-1]
    starts = [index for index in range(len(placed))
              if index == 0 or placed[index - 1] - placed[index] >= BREAK_BETWEEN_SECTIONS]
    headings: list[str | None] = [None] * len(placed)
    for start, end in zip(starts, [*starts[1:], len(placed)]):
        headings[start] = _heading(oldest=placed[end - 1], newest=placed[start], today=today)
    return headings


def _heading(*, oldest: datetime, newest: datetime, today: date) -> str:
    begun = f"{_day(oldest, today)}, {_clock(oldest)}"
    if newest.date() != oldest.date():
        return f"{begun} – {_day(newest, today)}, {_clock(newest)}"
    if _clock(newest) == _clock(oldest):
        return begun
    return f"{begun} – {_clock(newest)}"


def _day(moment: datetime, today: date) -> str:
    day = f"{_WEEKDAYS[moment.weekday()]} {_MONTHS[moment.month - 1]} {moment.day}"
    return day if moment.year == today.year else f"{day} {moment.year}"


def _clock(moment: datetime) -> str:
    return f"{moment.hour % 12 or 12}:{moment.minute:02d} {'AM' if moment.hour < 12 else 'PM'}"
