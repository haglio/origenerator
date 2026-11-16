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


def library_paths_in(output_files: str | None) -> set[str]:
    try:
        files = json.loads(output_files or "[]")
    except (ValueError, TypeError):
        return set()
    return {file["library_path"] for file in files
            if isinstance(file, dict) and file.get("library_path")} if isinstance(files, list) else set()
