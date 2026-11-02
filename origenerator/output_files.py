from __future__ import annotations

import json
from functools import lru_cache

READINGS_KEPT = 20_000


def parse_file_list(raw) -> list[dict]:
    if not raw:
        return []
    try:
        files = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return files if isinstance(files, list) else []


def produced_output(row: dict) -> bool:
    return _lists_a_file(row.get("output_files"))


@lru_cache(maxsize=READINGS_KEPT)
def _lists_a_file(output_files: str | None) -> bool:
    return bool(parse_file_list(output_files))
