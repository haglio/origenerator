from __future__ import annotations

from origenerator.gallery.signatures import parse_params
from origenerator.workflows.non_ai import (
    FOLDER_KEY,
    FOLDER_PARTS_IN_A_NAME,
    TITLE_KEY,
    non_ai_folder,
)


def leaf_folder_label(row: dict) -> str:
    parts = parse_params(row.get("params_json")).get(FOLDER_KEY, "").split("/")
    return "/".join(parts[FOLDER_PARTS_IN_A_NAME:] or parts[-1:])


def started_from_no_image(row: dict) -> bool:
    return non_ai_folder(row.get("workflow_name")) is not None


def recorded_title(row: dict) -> str | None:
    if non_ai_folder(row.get("workflow_name")) is None:
        return None
    return parse_params(row.get("params_json")).get(TITLE_KEY) or None
