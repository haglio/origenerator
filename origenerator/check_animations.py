# ruff: noqa: PLC0415 -- inside the functions, so naming this module costs nothing
"""Open the window for settling what each animation runs, on its own
(:mod:`origenerator.own_window`) like the sorting one."""
from __future__ import annotations

import json


def _launcher(db, client):
    """Queue one video of a sample's own picture with the prompts as edited: the
    same recipe, its seeds re-rolled so it cannot reproduce the sample."""
    from origenerator import gallery
    from origenerator.generation_config import randomize_seeds
    from origenerator.gui.job_queue import JobQueue
    from origenerator.workflows import WORKFLOW_REGISTRY

    jobs = JobQueue(db, client)

    def submit(sample: dict, positive: str, negative: str) -> str:
        workflow = WORKFLOW_REGISTRY.get(sample.get("workflow_name") or "")
        if workflow is None:
            return "That clip's workflow is not one this app still has."
        params = dict(gallery.parse_params(sample.get("params_json")))
        params.update(positive_prompt=positive, negative_prompt=negative)
        params = randomize_seeds(params, workflow.seed_keys())
        index = gallery.build_image_config_index(
            [row for row in db.list_generations()
             if gallery.media_type_of_row(row) == gallery.MediaType.IMAGE])
        key = gallery.settings_folder_key(
            {"workflow_name": workflow.name, "params_json": json.dumps(params),
             "workflow_version": workflow.version}, index)
        started = jobs.start_prepared(key, workflow, params)
        if not started:
            return "ComfyUI would not take it — see the log."
        return "Queued. Come back to this one once it has finished."

    return submit


def the_animation_window():
    from origenerator import animation_samples, gallery, recipe_match
    from origenerator.animation_check_session import AnimationCheckSession
    from origenerator.animation_recipes import AcceptedRecipes
    from origenerator.comfyui_client import ComfyUIClient
    from origenerator.config import (
        COMFYUI_FOLDERS,
        COMFYUI_HOST,
        COMFYUI_OUTPUT_DIR,
        COMFYUI_PORT,
        DB_PATH,
        THUMB_DIR,
    )
    from origenerator.db import Database
    from origenerator.gui.animation_check_window import AnimationCheckWindow
    from origenerator.media import MediaType

    db = Database(DB_PATH)
    rows = db.list_generations()
    pictures = [row for row in rows
                if gallery.media_type_of_row(row) == MediaType.IMAGE]

    def look(sample: dict):
        """The picture this clip was made from, and the clip's own loop."""
        source = gallery.find_source_image_id(sample, pictures)
        row = db.get_generation(source) if source else None
        still = gallery.resolve_preview(row, COMFYUI_OUTPUT_DIR) if row else None
        return (str(still[0]) if still and still[1] == MediaType.IMAGE else None,
                gallery.animated_preview_path(sample, COMFYUI_OUTPUT_DIR, THUMB_DIR))

    return AnimationCheckWindow(
        AnimationCheckSession(
            list(animation_samples.paths_in_order(rows)),
            animation_samples.samples_by_path(rows),
            AcceptedRecipes(),
            pinned=recipe_match.curated_recipe),
        look,
        _launcher(db, ComfyUIClient(host=COMFYUI_HOST, port=COMFYUI_PORT, folders=COMFYUI_FOLDERS)),
    )


def main() -> int:
    from origenerator.own_window import open_on_its_own

    return open_on_its_own("Checking animations", the_animation_window,
                           launcher="check_animations.vbs")


if __name__ == "__main__":
    raise SystemExit(main())
