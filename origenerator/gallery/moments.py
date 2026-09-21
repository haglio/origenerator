from __future__ import annotations

from datetime import UTC, datetime

BEFORE_EVERY_RECORD = datetime.min.replace(tzinfo=UTC)


def moment_of(stamp: str | None) -> datetime:
    if not stamp:
        return BEFORE_EVERY_RECORD
    moment = datetime.fromisoformat(stamp)
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)
