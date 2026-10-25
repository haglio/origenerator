"""Each animation's sample, and the order they are worked through: a video the
user kept of that act from a picture sorted that way, most-kept first."""
from __future__ import annotations

from collections import defaultdict

from origenerator import animation_paths, gallery
from origenerator.act_settings import GENAU, VIDEO, act_of, loops
from origenerator.db_generations import was_kept
from origenerator.file_refs import frame_name
from origenerator.generation_state import GenerationStatus
from origenerator.media import MediaType

Path = tuple[str, str, str]  # lane, act, state


def _made(row: dict) -> str:
    return row.get("created_at") or ""


def _states_by_picture(rows: list[dict]) -> dict[str, str]:
    return {
        frame_name(file.get("filename")): row.get("picture_state") or ""
        for row in rows
        if gallery.media_type_of_row(row) == MediaType.IMAGE
        for file in gallery.row_output_files(row)
    }


def _kept_clips(rows: list[dict]) -> list[dict]:
    return [row for row in rows
            if row.get("status") == GenerationStatus.COMPLETED
            and gallery.produced_output(row)
            and gallery.media_type_of_row(row) == MediaType.VIDEO
            and gallery.is_image_conditioned(row.get("workflow_name") or "")
            and was_kept(row)]


def samples_by_path(rows: list[dict], *, content: dict | None = None
                     ) -> dict[Path, list[dict]]:
    """Every kept video that stands as a sample, by the animation it is one of,
    newest first; one serves the loop lane only if a looping workflow made it."""
    states = _states_by_picture(rows)
    found: dict[Path, list[dict]] = defaultdict(list)
    for clip in sorted(_kept_clips(rows), key=_made, reverse=True):
        act = act_of(clip)
        state = states.get(frame_name(
            gallery.parse_params(clip.get("params_json")).get("input_image")), "")
        if not act or not state:
            continue
        lanes = (VIDEO, GENAU) if loops(clip) else (VIDEO,)
        for lane in lanes:
            if animation_paths.allows(lane, act, state, content=content):
                found[(lane, act, state)].append(clip)
    return dict(found)


def paths_in_order(rows: list[dict], *, content: dict | None = None) -> list[Path]:
    """Every animation the table holds, by how many kept clips it has and then by
    the table's own order, so two runs list them the same way."""
    samples = samples_by_path(rows, content=content)
    listed = animation_paths.every_path(content=content)
    return sorted(listed, key=lambda path: -len(samples.get(path, ())))
