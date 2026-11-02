from __future__ import annotations

import json
import logging
from typing import NamedTuple, Protocol

from PyQt6.QtWidgets import QMessageBox

from origenerator import config, enhance_presets, fix_training, gallery, lora_training
from origenerator.file_refs import frame_name
from origenerator.generation_config import randomize_seeds
from origenerator.generation_state import GenerationSource
from origenerator.gui.enhance_pane import EnhancePane
from origenerator.gui.enhance_versions import RunningEnhancement
from origenerator.gui.generation_job import display_status
from origenerator.gui.inflight import RunReading
from origenerator.gui.message import ERROR, INFO, WARNING
from origenerator.gui.training_run import TrainingRun
from origenerator.media import MediaType
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.detail_parts import detector_folder, name_parts, part_named

logger = logging.getLogger(__name__)

NO_VIDEO_ENHANCER = "Enhancement is for images — there is no video enhancer"
ALREADY_AT_THESE_SETTINGS = (
    "Already enhanced at these settings — change one to make another"
)
_WHAT_AN_ENHANCE_DOES = "(upscale + light redraw)"


def _folder_of(workflow, params: dict, image_index: dict) -> str:
    return gallery.settings_folder_key(
        {"workflow_name": workflow.name, "workflow_version": workflow.version,
         "params_json": json.dumps(params)},
        image_index,
    )


def launch_enhancements(jobs, db, asks, image_index, *, source=GenerationSource.GENERATED
                        ) -> list[tuple[dict, dict, str, str | None]]:
    workflow = WORKFLOW_REGISTRY[gallery.ENHANCE_WORKFLOW]
    by_folder: dict[str, list[tuple[dict, dict]]] = {}
    for row, params in asks:
        if _made_or_on_its_way(jobs, row, params):
            logger.info("Not enhancing %s again: it has, or has on its way, an enhancement "
                        "at these settings", row.get("prompt_id"))
            continue
        by_folder.setdefault(_folder_of(workflow, params, image_index), []).append((row, params))
    launched = []
    for key, entries in by_folder.items():
        batch = [randomize_seeds(params, workflow.seed_keys()) for _row, params in entries]
        for (row, params), prompt_id in zip(entries, jobs.start_batch(key, workflow, batch,
                                                                      source=source), strict=True):
            if prompt_id:
                db.set_enhance_target(prompt_id, row.get("prompt_id"))
            launched.append((row, params, key, prompt_id))
    return launched


def _made_or_on_its_way(jobs, row: dict, params: dict) -> bool:
    if gallery.version_matching_params(row, params) is not None:
        return True
    image = frame_name(params.get("input_image"))
    return any(job.workflow.name == gallery.ENHANCE_WORKFLOW
               and frame_name(job.params.get("input_image")) == image
               and gallery.same_enhancement(job.params, params)
               for job in jobs.all_jobs)


class Offer(NamedTuple):
    available: bool
    tip: str


class EnhanceHost(Protocol):
    def selected_prompt_ids(self) -> list[str]:
        pass

    def row_for(self, prompt_id: str) -> dict | None:
        pass

    def image_rows(self) -> list[dict]:
        pass

    def image_config_index(self) -> dict:
        pass

    def current_group(self):
        pass

    def typical_run_seconds(self, job) -> float | None:
        pass

    def enhance_offer_changed(self) -> None:
        pass


class EnhanceController:
    def __init__(self, host: EnhanceHost, *, db, jobs, gallery_pane, slideshows,
                 info_tabs_of):
        self._host = host
        self._db = db
        self._jobs = jobs
        self._gallery_pane = gallery_pane
        self._slideshows = slideshows
        self._generate_pane_of = info_tabs_of
        self._settings = gallery.EnhanceSettings()
        self._targets: dict[str, str | None] = {}
        self._by_prompt: dict[str, object] = {}
        self._signature: tuple = ()
        self.pane = EnhancePane(self._on_settings_changed)
        self.pane.enhance_requested.connect(self.enhance_the_selection)
        self.pane.fix_training_requested.connect(self._train_fix)
        self.pane.show_settings(self._settings)
        self.pane.show_presets(enhance_presets.load(self._db.list_generations))
        self.pane.preset_saved.connect(lambda name: self.pane.show_presets(
            enhance_presets.save(name, self._settings.params)))
        self.pane.preset_renamed.connect(lambda index, name: self.pane.show_presets(
            enhance_presets.rename(index, name)))
        self._training: TrainingRun | None = None

    def _train_fix(self, name: str) -> None:
        if self._training is not None:
            return
        part = part_named(name)
        folder = fix_training.photos_folder(part)
        folder.mkdir(parents=True, exist_ok=True)
        if not fix_training.training_photos(part):
            QMessageBox.information(self.pane, "Train",
                                    f"Put photos of {name} in {folder}, then press Train again.")
            return
        if config.LORA_TRAINING_PYTHON is None or config.LORA_TRAINING_SCRIPTS is None:
            QMessageBox.information(
                self.pane, "Train", "No training program is set up: content.local.json "
                "names no lora_training_python and lora_training_scripts.")
            return
        job = fix_training.training_job(part,
                                        fix_training.model_to_train_for(self._settings.params))
        self._watch(job).begin()

    def take_up_trainings(self) -> None:
        lora_training.take_up(fix_training, adopt=self._adopt, take=self._take)

    def _adopt(self, job: dict, trainer) -> None:
        if self._training is None:
            self._watch(job).adopt(trainer)

    def _watch(self, job: dict) -> TrainingRun:
        name = job["part"]
        self._training = TrainingRun(job, self._jobs, fix_training,
                                     reveal=lambda: self.pane.open_fix_prompts(name),
                                     parent=self.pane)
        self._training.progress.connect(lambda text: self.pane.show_fix_training(name, text))
        self._training.finished.connect(lambda lora: self._training_ended(job, lora))
        self._training.failed.connect(lambda why: self._training_ended(job, None, why))
        self._training.canceled.connect(lambda: self._training_ended(job, None))
        return self._training

    def _training_ended(self, job: dict, lora: str | None, why: str = "") -> None:
        self._training = None
        self.pane.show_fix_training(job["part"], None)
        if lora:
            self._take(job, lora)
        elif why:
            QMessageBox.warning(self.pane, "Train", why)

    def _take(self, job: dict, lora: str) -> None:
        self.pane.use_fix_lora(job["part"], lora)
        trainer = lora_training.trainer_of(job)
        if trainer is not None:
            fix_training.note_duration(lora_training.time_taken(job, trainer))
        lora_training.mark_taken(job)

    @property
    def settings(self):
        return self._settings

    def settings_json(self) -> str:
        return self._settings.to_json()

    def restore_settings(self, raw: str | None) -> None:
        self._settings = gallery.EnhanceSettings.parse(raw)
        self.pane.show_settings(self._settings)
        self._push_settings()

    def _push_settings(self) -> None:
        for pane in self._generate_pane_of().generate_tabs():
            pane.set_enhance_settings(self._settings)

    def _on_settings_changed(self, settings) -> None:
        self._settings = settings
        self._push_settings()
        self._host.enhance_offer_changed()
        self._gallery_pane.refresh_corners()

    def sync_pane(self, offer: Offer) -> None:
        picked = [row for pid in self._host.selected_prompt_ids()
                  if (row := self._host.row_for(pid)) is not None]
        folder = None if picked or self._gallery_pane.selected_ids else self._host.current_group()
        in_front = picked or list(getattr(folder, "rows", []) or [])
        self.pane.set_applicable(not _all_video(in_front), NO_VIDEO_ENHANCER)
        self.pane.show_offer(offer.available, offer.tip)
        self.pane.show_images_in_front(picked, folder)

    def offer(self) -> Offer:
        if self._gallery_pane.selected_ids:
            ids = self.enhanceable_selection()
            if ids:
                return Offer(True, f"Enhance {len(ids)} item"
                                   f"{'s' if len(ids) != 1 else ''} "
                                   f"{_WHAT_AN_ENHANCE_DOES}")
            return Offer(False, NO_VIDEO_ENHANCER if self._selection_is_all_video()
                         else ALREADY_AT_THESE_SETTINGS)
        group = self._host.current_group()
        awaiting = (
            self._awaiting(group.rows) if isinstance(group, gallery.SettingsGroup) else []
        )
        if not awaiting:
            return Offer(False, "Nothing here to enhance")
        return Offer(True, f"Enhance {len(awaiting)} not-yet-enhanced image"
                           f"{'s' if len(awaiting) != 1 else ''} in this folder "
                           f"{_WHAT_AN_ENHANCE_DOES}")

    def _awaiting(self, rows) -> list[dict]:
        return gallery.rows_awaiting_enhancement(
            rows, self._db.rows_made_by(gallery.ENHANCE_WORKFLOW))

    def enhanceable_selection(self) -> list[str]:
        return [prompt_id for prompt_id in self._host.selected_prompt_ids()
                if (row := self._db.get_generation(prompt_id)) is not None
                and self.would_enhance(row)]

    def would_enhance(self, row: dict) -> bool:
        return (gallery.is_enhanceable_row(row)
                and gallery.version_matching_settings(row, self._settings) is None)

    def _selection_is_all_video(self) -> bool:
        return _all_video(row for pid in self._host.selected_prompt_ids()
                          if (row := self._db.get_generation(pid)) is not None)

    def enhance_the_selection(self) -> None:
        if self._gallery_pane.selected_ids:
            ids = self.enhanceable_selection()
            if ids:
                self.enhance_items(ids)
                self._host.enhance_offer_changed()
            return
        self._enhance_all()

    def _enhance_all(self) -> None:
        group = self._host.current_group()
        if not isinstance(group, gallery.SettingsGroup):
            return
        self._enqueue(self._awaiting(group.rows))
        self._host.enhance_offer_changed()

    def enhance_items(self, prompt_ids: list[str]) -> None:
        rows = [self._db.get_generation(pid) for pid in prompt_ids]
        self._enqueue([r for r in rows if r is not None])

    def _enqueue(self, rows: list[dict]) -> None:
        asks = []
        for row in rows:
            params = gallery.enhance_params_for(row, self._settings)
            if params is None:
                logger.warning("Enhance skipped for %s: no output file to enhance",
                               row.get("prompt_id"))
                continue
            asks.append((row, params))
        for launched in launch_enhancements(self._jobs, self._db, asks,
                                            self._host.image_config_index()):
            self._note_launch(*launched)

    def _launch(self, row: dict, params: dict) -> bool:
        launched = launch_enhancements(self._jobs, self._db, [(row, params)],
                                       self._host.image_config_index())
        return bool(launched) and self._note_launch(*launched[0])

    def _note_launch(self, row: dict, params: dict, key: str, prompt_id: str | None) -> bool:
        if prompt_id:
            self._targets[prompt_id] = row.get("prompt_id")
            self.put_what_is_locked_first()
            self.reconcile()
            logger.info("Enhance launched for %s on %s at %s, under %s",
                        row.get("prompt_id"), params.get("input_image"),
                        gallery.describe_enhance_params(params), key)
            return True
        logger.warning("Enhance of %s dropped: could not launch under %s",
                       params.get("input_image"), key)
        return False

    def enhance_when_wanted(self, row: dict | None) -> None:
        if row is None or not self._settings.auto:
            return
        awaiting = self._awaiting([row])
        if awaiting:
            self._enqueue(awaiting)

    def enhance_it(self, prompt_id: str | None) -> tuple[str | None, str, str]:
        row = self._db.get_generation(prompt_id) if prompt_id else None
        if row is None or not gallery.is_enhanceable_row(row):
            return None, "only a finished image can be enhanced", WARNING
        if gallery.is_enhanced_row(row):
            return None, "this one is enhanced already", WARNING
        params = gallery.enhance_params_for(row, self._settings)
        if params is None:
            return None, "this one has no file to enhance", WARNING
        return self._launch_spoken(row, params, "enhance", "enhancing…")

    def fix_parts(self, prompt_id: str | None, parts) -> tuple[str | None, str, str]:
        asked = name_parts(parts)
        row = self._db.get_generation(prompt_id) if prompt_id else None
        if row is None or not gallery.is_enhanceable_row(row):
            return None, f"only a finished image can get a {asked} fix", WARNING
        params = gallery.fix_params_for(row, parts, self._settings)
        if params is None:
            folders = " or ".join(sorted({detector_folder(part) for part in parts}))
            return None, f"no {asked} detector installed (ComfyUI {folders})", WARNING
        if gallery.version_matching_params(row, params) is not None:
            return None, f"{asked} already fixed as hard as a fix goes", WARNING
        fixing = name_parts(
            [part for part in parts if part.name in params["enhance_detail_fixes"]])
        return self._launch_spoken(row, params, f"{fixing} fix", f"fixing {fixing}…")

    def _launch_spoken(self, row: dict, params: dict, what: str,
                       doing: str) -> tuple[str | None, str, str]:
        if self.run_of(row) is not None:
            return None, "an enhance of this image is already running", WARNING
        logger.info("Voice %s on %s at %s", what, row.get("prompt_id"),
                    gallery.describe_enhance_params(params))
        if not self._launch(row, params):
            return None, f"couldn't launch the {what} — see the log", ERROR
        return row["prompt_id"], doing, INFO

    def enhance_from_slideshow(self, prompt_id: str) -> bool:
        if self.enhance_it(prompt_id)[0] is not None:
            return True
        self.put_what_is_locked_first()
        self.reconcile()
        return False

    def put_what_is_locked_first(self) -> None:
        locked = [row for prompt_id in self._slideshows.locked_prompt_ids()
                  if (row := self._host.row_for(prompt_id)) is not None]
        self._jobs.put_first(job.prompt_id for job in self.jobs_targeting(locked))

    def _enhances_in_flight(self) -> list:
        return [job for job in self._jobs.all_jobs
                if job.workflow.name == gallery.ENHANCE_WORKFLOW]

    def _target_of(self, job) -> str | None:
        if job.prompt_id not in self._targets:
            row = self._db.get_generation(job.prompt_id)
            self._targets[job.prompt_id] = (row or {}).get("enhance_of")
        return self._targets[job.prompt_id]

    def _of_row(self, job, row: dict) -> bool:
        return gallery.enhance_run_targets_row(
            self._target_of(job), job.params.get("input_image"), row)

    def _job_for(self, row: dict, running=None):
        for job in (self._enhances_in_flight() if running is None else running):
            if self._of_row(job, row):
                return job
        return None

    def run_of(self, row: dict) -> RunReading | None:
        job = self._job_for(row)
        return self._as_run(job) if job is not None else None

    def _as_run(self, job) -> RunReading:
        return RunReading(
            status=display_status(job.state),
            frame=job.last_preview,
            progress=job.last_progress,
            pass_progress=job.last_pass_progress,
            stage=job.last_stage,
            started_at=job.started_at,
            typical_seconds=self._host.typical_run_seconds(job),
        )

    def reconcile(self) -> None:
        running = self._enhances_in_flight()
        for pane in self._generate_pane_of().generate_tabs():
            row = pane.displayed_row()
            pane.set_pending_enhancement(
                self._pending_for(row, running) if row else None
            )
        self._reconcile_tiles(running)
        self.tell_the_slideshows()

    def tell_the_slideshows(self) -> None:
        self._slideshows.note_enhancing(
            {prompt_id: "running" if job.state == "running" else "queued"
             for prompt_id, job in self._by_prompt.items()},
            {prompt_id: job.last_preview for prompt_id, job in self._by_prompt.items()
             if job.state == "running" and job.last_preview})

    def _reconcile_tiles(self, running) -> None:
        live = {job.prompt_id for job in running}
        self._targets = {pid: target for pid, target in self._targets.items()
                         if pid in live}
        signature = tuple(sorted(
            (job.prompt_id, self._target_of(job) or job.params.get("input_image") or "")
            for job in running
        ))
        if signature != self._signature:
            self._signature = signature
            self._by_prompt = {
                row["prompt_id"]: job
                for job in running
                for row in self._host.image_rows()
                if self._of_row(job, row)
            }
        self._gallery_pane.show_enhancing({
            prompt_id: self._as_run(job)
            for prompt_id, job in self._by_prompt.items()
        })

    def _pending_for(self, row: dict, running) -> RunningEnhancement | None:
        job = self._job_for(row, running)
        if job is None:
            return None
        run = self._as_run(job)
        return RunningEnhancement(run.status, run.frame,
                                  gallery.describe_enhance_params(job.params))

    def forget(self, prompt_id: str) -> None:
        self._targets.pop(prompt_id, None)

    def jobs_targeting(self, rows) -> list:
        running = self._enhances_in_flight()
        return [job for job in running
                if any(self._job_for(row, [job]) is not None for row in rows if row)]

    def cancel_for_delete(self, rows) -> None:
        for job in self.jobs_targeting(rows):
            logger.info("Canceling the enhance of %s: its image is being deleted",
                        job.params.get("input_image"))
            self._jobs.cancel_job(job.prompt_id)

    def cancel_for(self, rows) -> None:
        jobs = self.jobs_targeting(rows)
        for job in jobs:
            logger.info("Canceling the enhance of %s: asked to, from its tile",
                        job.params.get("input_image"))
            self._jobs.cancel_job(job.prompt_id)
        if jobs:
            self.reconcile()


def _all_video(rows) -> bool:
    rows = list(rows)
    return bool(rows) and all(gallery.media_type_of_row(row) == MediaType.VIDEO for row in rows)
