from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from origenerator import gallery, timing
from origenerator.generation_state import GenerationStatus
from origenerator.gui.generation_job import display_status
from origenerator.gui.inflight import FOLDER_CELLS, InFlightItem, RunReading
from origenerator.media import MediaType
from origenerator.voice.dictation import words_of
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.derived_size import resolve_input_image_path

logger = logging.getLogger(__name__)

SOURCE_FRAME_KINDS = (gallery.JobKind.VIDEO, gallery.JobKind.ENHANCE)
TRAINING_KEY = "fix training"


@dataclass(frozen=True)
class InFlightSources:
    db: object
    jobs: object
    populate: object
    tree: object


@dataclass(frozen=True)
class InFlightCallbacks:
    cancel: Callable[[str], None]
    reveal: Callable[[str], None]
    go_to_item: Callable[[str], None]
    shield: Callable[[str, bool], None]


class InFlightItems:
    def __init__(self, sources: InFlightSources, image_rows: Callable[[], list],
                 image_index: Callable[[], dict], callbacks: InFlightCallbacks):
        self._db = sources.db
        self._jobs = sources.jobs
        self._populate = sources.populate
        self._tree = sources.tree
        self._image_rows = image_rows
        self._image_index = image_index
        self._on_cancel = callbacks.cancel
        self._on_reveal = callbacks.reveal
        self._on_go_to_item = callbacks.go_to_item
        self._on_shield = callbacks.shield

    def build(self, rows=None, requests=None) -> list[InFlightItem]:
        job_by_pid = {job.prompt_id: (key, job)
                         for key, jobs in self._jobs.jobs_by_folder.items()
                         for job in jobs}
        records = {r["prompt_id"]: r for r in (self._db.list_requests()
                                               if requests is None else requests)}
        typical: dict[str, float | None] = {}
        stablemates: dict[str, tuple] = {}
        if rows is None:
            rows = self._db.list_generations()
        row_by_id = {r.get("prompt_id"): r for r in rows}
        items = []
        sent = set()
        for row in rows:
            if not gallery.is_in_progress(row):
                continue
            pid = row["prompt_id"]
            tracked = job_by_pid.get(pid)
            if tracked is not None:
                folder_key, job = tracked
                frame, progress = job.last_preview, job.last_progress
                pass_progress = job.last_pass_progress
                stage = job.last_stage
                foreign = job.foreign_ahead
                starts_at = self._jobs.starts_at(pid)
                started = job.started_at
                cancel = partial(self._on_cancel, pid)
                shield = partial(self._on_shield, pid)
                shielded = job.shielded
                stop_populate = partial(self._populate.stop, folder_key)
                state = job.state
                move_up = (partial(self._jobs.move_up, pid)
                           if self._jobs.can_move_up(pid) else None)
                move_down = (partial(self._jobs.move_down, pid)
                             if self._jobs.can_move_down(pid) else None)
            else:
                folder_key = gallery.settings_folder_key(row, self._image_index())
                frame, progress, cancel, foreign, started = None, None, None, None, None
                starts_at = None
                pass_progress, stage, stop_populate, state = None, "", None, row.get("status")
                shield, shielded = None, bool(row.get("shielded"))
                move_up = move_down = None
            workflow_name = row.get("workflow_name") or ""
            params = gallery.parse_params(row.get("params_json"))
            kind = gallery.job_kind_label(workflow_name)
            source_video = (None if row.get("action")
                            else row_by_id.get(row.get("source_video")))
            workflow = WORKFLOW_REGISTRY.get(workflow_name)
            if kind == gallery.JobKind.ENHANCE:
                reveal = partial(self._go_to_the_image_of, row)
            else:
                reveal = partial(self._on_reveal, folder_key)
            items.append(InFlightItem(
                key=pid,
                caption=gallery.generate_tab_title(workflow_name, params),
                reading=RunReading(
                    status=display_status(state),
                    frame=frame,
                    progress=progress,
                    pass_progress=pass_progress,
                    stage=stage,
                    started_at=started,
                    typical_seconds=self._typical_seconds(workflow_name, typical),
                ),
                reveal=reveal,
                media_type=gallery.media_type_of_row(row),
                cancel=cancel,
                shield=shield,
                shielded=shielded,
                populating=self._populate.is_active(folder_key),
                stop_populate=stop_populate,
                foreign_ahead=foreign,
                starts_at=starts_at,
                job_kind=kind,
                requested=bool(words_of(records.get(pid))),
                batch_modified=pid in records and not words_of(records[pid]),
                source_image=start_frame_of(kind, params),
                source_file=source_file_of(
                    row_by_id.get((records.get(pid) or {}).get("source_prompt_id")),
                    params, kind),
                action=row.get("action") or "",
                source_video_thumbnail=(source_video or {}).get("thumbnail_path"),
                prompt_edited=bool(
                    source_video and workflow
                    and gallery.prompts_differ_from(params, source_video, workflow)),
                folder_thumbnails=self._folder_thumbnails(folder_key, stablemates),
                move_up=move_up,
                move_down=move_down,
            ))
            if row.get("status") == GenerationStatus.RUNNING:
                sent.add(pid)
        return self._in_queue_order(items, sent)

    def _in_queue_order(self, items: list[InFlightItem], sent: set[str]) -> list[InFlightItem]:
        place = {pid: i for i, pid in enumerate(self._jobs.queue_order)}
        items.sort(key=lambda it: (place.get(it.key, len(place)),
                                   not it.reading.rendering))
        training = self._jobs.training
        if training is not None:
            behind_what_comfyui_holds = next(
                (at for at, item in enumerate(items) if item.key not in sent), len(items))
            items.insert(behind_what_comfyui_holds, InFlightItem(
                key=TRAINING_KEY, caption=training.caption,
                reading=training.reading(), reveal=training.reveal, cancel=training.cancel,
                job_kind=gallery.JobKind.TRAINING))
        return items

    def _go_to_the_image_of(self, enhancement: dict) -> None:
        image = gallery.enhance_target_id(enhancement, self._image_rows())
        if image is None:
            logger.info("Nothing to go to for %s: the image it enhances is gone",
                        enhancement.get("prompt_id"))
            return
        self._on_go_to_item(image)

    def _folder_thumbnails(self, folder_key: str, cache: dict) -> tuple:
        if folder_key not in cache:
            group = self._tree.group_for_key(folder_key)
            rows = gallery.rows_under(group) if group is not None else []
            cache[folder_key] = tuple(
                row["thumbnail_path"] for row in rows if row.get("thumbnail_path")
            )[:FOLDER_CELLS]
        return cache[folder_key]

    def _typical_seconds(self, workflow_name: str, cache: dict):
        if workflow_name not in cache:
            cache[workflow_name] = timing.estimate_seconds(
                self._db.recent_durations(workflow_name)
            )
        return cache[workflow_name]


def start_frame_of(kind: str, params: dict) -> str | None:
    return params.get("input_image") if kind in SOURCE_FRAME_KINDS else None


def source_file_of(asked_of: dict | None, params: dict, kind: str) -> str | None:
    thumbnail = (asked_of or {}).get("thumbnail_path")
    if thumbnail:
        return thumbnail
    frame = resolve_input_image_path(start_frame_of(kind, params))
    return str(frame) if frame is not None else None


def requested_of(row: dict, workflow, params: dict) -> dict:
    kind = gallery.job_kind_label(workflow.name)
    made = "A video" if workflow.output_type == MediaType.VIDEO else "An image"
    return {"caption": f"{made} from a Request, still being started",
            "media_type": workflow.output_type, "job_kind": kind, "requested": True,
            "source_image": start_frame_of(kind, params),
            "source_file": source_file_of(row, params, kind)}
