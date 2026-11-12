from __future__ import annotations

import logging
from typing import Any, NamedTuple

from origenerator import action_settings, animation_paths, animation_settings, gallery
from origenerator.action_vocabulary import vocabulary
from origenerator.animation_names import Animation
from origenerator.generation_state import GenerationStatus
from origenerator.media import MediaType
from origenerator.published_actions import give_the_launch_its_actions
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)


class CombineRun(NamedTuple):
    workflow: Any
    params: dict
    video_id: str | None = None


def rebuildable_video(row: dict | None) -> bool:
    return bool(row and gallery.media_type_of_row(row) == MediaType.VIDEO
                and gallery.is_image_conditioned(row.get("workflow_name") or ""))


def rebuildable_videos(rows: list[dict]) -> list[dict]:
    return [row for row in rows
            if row.get("status") == GenerationStatus.COMPLETED and rebuildable_video(row)]


def offered_actions(videos: list[dict], lane: str, checked: tuple[str, ...],
                    state: str) -> set[str]:
    offered = set(action_settings.available_categories(videos, lane, checked))
    if state:
        offered &= set(animation_paths.actions_for(state, lane))
        offered |= _accepted_over(state, lane, checked)
    return offered


def _accepted_over(state: str, lane: str, checked: tuple[str, ...]) -> set[str]:
    return {action for action in vocabulary(MediaType.VIDEO).buttons
            if animation_settings.settings_for(lane, Animation(action, checked).name, state)
            is not None}


def readied(settings: dict, reference: str) -> CombineRun | None:
    workflow = WORKFLOW_REGISTRY.get(settings.get("workflow") or "")
    if workflow is None or not gallery.is_image_conditioned(workflow.name):
        logger.warning("combine: workflow %r not usable", settings.get("workflow"))
        return None
    params = gallery.written_params(settings, reference, workflow)
    return None if params is None else CombineRun(workflow, params)


def curated(reference: str, name: str, lane: str, state: str) -> CombineRun | None:
    settings = (animation_settings.settings_for(lane, name, state)
                or action_settings.pinned_settings(name, lane))
    if settings is None:
        return None
    return readied(action_settings.in_its_lane(settings, lane), reference)


def after_video(video: dict | None, reference: str | None) -> CombineRun | None:
    workflow = WORKFLOW_REGISTRY.get((video or {}).get("workflow_name") or "")
    if workflow is None or not gallery.is_image_conditioned(workflow.name):
        return None
    params = gallery.combined_params(video, reference, workflow)
    return None if params is None else CombineRun(workflow, params, video["prompt_id"])


def as_action(reference: str, name: str, lane: str, state: str,
              videos: list[dict]) -> CombineRun | None:
    run = curated(reference, name, lane, state)
    if run is not None:
        logger.info("combine: %s in the %s lane -> pinned settings", name, lane)
        return run
    video_id = action_settings.most_used_video(name, videos, lane)
    logger.info("combine: %s in the %s lane -> settings from %s", name, lane, video_id)
    return after_video(next((video for video in videos if video["prompt_id"] == video_id), None),
                       reference)


def launch(jobs, db, key: str, run: CombineRun, *, name: str = "",
           checked: tuple[str, ...] = ()) -> str | None:
    prompt_id = jobs.start_prepared(key, run.workflow, run.params)
    if prompt_id:
        db.set_settings_source(prompt_id, category=name, video_prompt_id=run.video_id)
        give_the_launch_its_actions(db, prompt_id, name, checked)
    return prompt_id
