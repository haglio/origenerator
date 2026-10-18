# ruff: noqa: PLC0415 -- inside the functions, so naming this module costs nothing
"""Open the window for settling what each animation runs, on its own
(:mod:`origenerator.own_window`) like the sorting one."""
from __future__ import annotations

import json


def _launcher(db, client, enhance_settings):
    """Queue one video of a sample's own picture with the prompts as edited: the
    same recipe, its seeds re-rolled so it cannot reproduce the sample."""
    from origenerator import gallery
    from origenerator.generation_config import randomize_seeds
    from origenerator.gui.enhance_controller import launch_enhancements
    from origenerator.gui.job_queue import JobQueue
    from origenerator.media import MediaType
    from origenerator.workflows import WORKFLOW_REGISTRY

    jobs = JobQueue(db, client)

    def image_index():
        return gallery.build_image_config_index(
            [row for row in db.list_generations()
             if gallery.media_type_of_row(row) == MediaType.IMAGE])

    def enhance(picture: dict) -> None:
        params = gallery.enhance_params_for(picture, enhance_settings)
        if params is not None:
            launch_enhancements(jobs, db, [(picture, params)], image_index())

    def fold(_key: str, prompt_id: str, _origin: str) -> None:
        row = db.get_generation(prompt_id)
        if row is not None and row.get("workflow_name") == gallery.ENHANCE_WORKFLOW:
            gallery.fold_enhancement(db, row)

    jobs.enhance_pictures_with(enhance)
    jobs.finished.connect(fold)

    def submit(sample: dict, positive: str, negative: str) -> str:
        workflow = WORKFLOW_REGISTRY.get(sample.get("workflow_name") or "")
        if workflow is None:
            return "That clip's workflow is not one this app still has."
        params = dict(gallery.parse_params(sample.get("params_json")))
        params.update(positive_prompt=positive, negative_prompt=negative)
        params = randomize_seeds(params, workflow.seed_keys())
        index = image_index()
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
    from origenerator.app_state import AppState
    from origenerator.comfyui_client import ComfyUIClient
    from origenerator.config import (
        COMFYUI_HOST,
        COMFYUI_OUTPUT_DIR,
        COMFYUI_PORT,
        DB_PATH,
        THUMB_DIR,
        UI_STATE_PATH,
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
        _launcher(db, ComfyUIClient(host=COMFYUI_HOST, port=COMFYUI_PORT),
                  gallery.EnhanceSettings.parse(AppState(UI_STATE_PATH).get("enhance_settings"))),
    )


def main() -> int:
    from origenerator.own_window import open_on_its_own

    return open_on_its_own("Checking animations", the_animation_window,
                           launcher="check_animations.vbs")


if __name__ == "__main__":
    raise SystemExit(main())
