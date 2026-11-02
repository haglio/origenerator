from __future__ import annotations

from collections import defaultdict

from origenerator import animation_paths, gallery
from origenerator.action_settings import GENAU, VIDEO, action_of, loops
from origenerator.db_generations import was_kept
from origenerator.file_refs import frame_name
from origenerator.generation_state import GenerationStatus
from origenerator.media import MediaType

Path = tuple[str, str, str]


def _made(row: dict) -> str:
    return row.get("created_at") or ""


def _states_by_image(rows: list[dict]) -> dict[str, str]:
    return {
        frame_name(file.get("filename")): row.get("image_state") or ""
        for row in rows
        if gallery.media_type_of_row(row) == MediaType.IMAGE
        for file in gallery.row_output_files(row)
    }


def _kept_videos(rows: list[dict]) -> list[dict]:
    return [row for row in rows
            if row.get("status") == GenerationStatus.COMPLETED
            and gallery.produced_output(row)
            and gallery.media_type_of_row(row) == MediaType.VIDEO
            and gallery.is_image_conditioned(row.get("workflow_name") or "")
            and was_kept(row)]


def samples_by_path(rows: list[dict], *, content: dict | None = None
                     ) -> dict[Path, list[dict]]:
    states = _states_by_image(rows)
    found: dict[Path, list[dict]] = defaultdict(list)
    for video in sorted(_kept_videos(rows), key=_made, reverse=True):
        action = action_of(video)
        state = states.get(frame_name(
            gallery.parse_params(video.get("params_json")).get("input_image")), "")
        if not action or not state:
            continue
        lanes = (VIDEO, GENAU) if loops(video) else (VIDEO,)
        for lane in lanes:
            if animation_paths.allows(lane, action, state, content=content):
                found[(lane, action, state)].append(video)
    return dict(found)


def paths_in_order(rows: list[dict], *, content: dict | None = None) -> list[Path]:
    samples = samples_by_path(rows, content=content)
    listed = animation_paths.every_path(content=content)
    return sorted(listed, key=lambda path: -len(samples.get(path, ())))
