from __future__ import annotations

from origenerator.gallery.signatures import parse_params
from origenerator.output_files import library_paths_in
from origenerator.workflows.non_ai import (
    FOLDER_KEY,
    FOLDER_PARTS_IN_A_NAME,
    TITLE_KEY,
    VERSION_GROUP_KEY,
    non_ai_folder,
)


def leaf_folder_label(row: dict) -> str:
    parts = parse_params(row.get("params_json")).get(FOLDER_KEY, "").split("/")
    return "/".join(parts[FOLDER_PARTS_IN_A_NAME:] or parts[-1:])


def started_from_no_image(row: dict) -> bool:
    return non_ai_folder(row.get("workflow_name")) is not None


def video_kino_plays(row: dict) -> str | None:
    if not started_from_no_image(row):
        return None
    return next(iter(sorted(library_paths_in(row.get("output_files")))), None)


def alternate_versions(row: dict, videos) -> list[dict]:
    group = _version_group(row)
    if group is None:
        return []
    return [other for other in videos
            if other.get("workflow_name") == row["workflow_name"]
            and other["prompt_id"] != row["prompt_id"] and _version_group(other) == group]


def _version_group(row: dict) -> str | None:
    if non_ai_folder(row.get("workflow_name")) is None:
        return None
    return parse_params(row.get("params_json")).get(VERSION_GROUP_KEY) or None


def recorded_title(row: dict) -> str | None:
    if non_ai_folder(row.get("workflow_name")) is None:
        return None
    return parse_params(row.get("params_json")).get(TITLE_KEY) or None
