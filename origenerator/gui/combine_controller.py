from __future__ import annotations

import json
import logging
from typing import Protocol

from PyQt6.QtCore import QObject

from origenerator import (
    action_settings,
    animation_paths,
    animation_settings,
    evolver_export,
    gallery,
)
from origenerator.animate_command import what_to_animate
from origenerator.check_animations import the_animation_window
from origenerator.config import COMFYUI_INPUT_DIR, OUTPUT_PLACES
from origenerator.export_lane import GENAU as GENAU_LANE
from origenerator.generation_state import GenerationStatus
from origenerator.gui.combination import Combination
from origenerator.gui.combine import Combine
from origenerator.gui.deferred import defer
from origenerator.gui.file_pick import FILE_FILTERS, pick_a_file
from origenerator.gui.message import ERROR, INFO, WARNING
from origenerator.gui.recent_videos import RecentVideo
from origenerator.gui.starting_rows import StartingRows
from origenerator.gui.zone_items import FilesOnly
from origenerator.item_names import ItemNames
from origenerator.media import MediaType, media_type_from_filename
from origenerator.video_history import video_history
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)

ALREADY_GENAUD = "already Genau'd"
ALREADY_MAKING_ONE = "already making it — handing that one over"

NOT_AN_IMAGE = "only an image can be animated"

NO_PAST_VIDEO = "No past video yet"


class CombineHost(Protocol):
    def image_config_index(self) -> dict: ...

    def animated_preview(self, row: dict) -> str | None: ...

    def folder_key_of(self, row: dict) -> str: ...

    def folder_key_for(self, workflow_name: str, params: dict,
                       workflow_version: str | None = None) -> str: ...

    def reveal_launch(self, key: str) -> None: ...

    def follow_link(self, prompt_id: str) -> None: ...

    def tell(self, title: str, message: str) -> None: ...


class CombineController(QObject):
    def __init__(self, host: CombineHost, *, parent: QObject, db, jobs, client,
                 info_tabs_of, slideshows, starting: StartingRows,
                 inbox: evolver_export.EvolverInbox | None = None,
                 names: ItemNames | None = None):
        super().__init__(parent)
        self._host = host
        self._db = db
        self._jobs = jobs
        self._starting = starting
        self._names = names or ItemNames(db)
        self._files = FilesOnly(places=OUTPUT_PLACES, input_dir=COMFYUI_INPUT_DIR)
        self._inbox = inbox or evolver_export.default_inbox()
        self._client = client
        self._generate_pane_of = info_tabs_of
        self._slideshows = slideshows
        self.widget = Combine(
            self._image_lent_by, self._video_lent_by, self._zone_preview,
            self._video_history, named=self._names.prompt_id_of, name_of=self._name_of,
            browse_image=self._browse_image, leads_to=self._item_held)
        self.widget.video_used.connect(self._db.record_combine_video_use)
        self.widget.combine_requested.connect(self._on_request)
        self._animation_settings = None
        self.widget.animation_settings_requested.connect(self._on_animation_settings)
        self.widget.item_activated.connect(self._host.follow_link)
        self.widget.intent_changed.connect(self._on_intent_changed)
        self.widget.image_zone.changed.connect(self.image_dropped)
        self.widget.video_zone.changed.connect(self.reconcile_generating)
        if client is None:
            self.widget.hide()

    def _on_animation_settings(self) -> None:
        from origenerator.own_window import show_or_say  # noqa: PLC0415 -- Qt only

        if self._animation_settings is not None and self._animation_settings.isVisible():
            self._animation_settings.raise_()
            self._animation_settings.activateWindow()
            return
        built = the_animation_window()
        if not show_or_say("Checking animations", built, parent=self.widget):
            self._animation_settings = built

    def _accepts_image(self, image_id: str) -> bool:
        return self._image_reference(image_id) is not None

    def _image_reference(self, image_id: str) -> str | None:
        row = self._db.get_generation(image_id)
        if row is not None:
            return gallery.input_image_reference(row)
        path = self._files.path_of(image_id)
        if path is None or media_type_from_filename(path.name) != MediaType.IMAGE:
            return None
        return str(path)

    def _image_still(self, image_id: str) -> str | None:
        row = self._db.get_generation(image_id)
        return self._still_path(row) if row is not None else self._image_reference(image_id)

    def _item_held(self, held: str) -> str | None:
        return held if self._db.get_generation(held) is not None else None

    def _name_of(self, held: str) -> str:
        if self._item_held(held) is not None:
            return self._names.of(held)
        return self._files.name_of(held)

    def _browse_image(self) -> None:
        path = pick_a_file(self.widget, "Image", FILE_FILTERS[MediaType.IMAGE])
        if path:
            self.widget.image_zone.set_item(path)

    def _image_lent_by(self, prompt_id: str) -> str | None:
        lent = gallery.image_lent_by(prompt_id, self._db.get_generation,
                                     self._host.image_config_index())
        return lent["prompt_id"] if lent is not None else None

    def _rebuildable_video_row(self, row) -> bool:
        return bool(
            row and gallery.media_type_of_row(row) == MediaType.VIDEO
            and gallery.is_image_conditioned(row.get("workflow_name") or "")
        )

    def _accepts_video(self, prompt_id: str) -> bool:
        return self._rebuildable_video_row(self._db.get_generation(prompt_id))

    def _video_lent_by(self, prompt_id: str) -> str | None:
        return prompt_id if self._accepts_video(prompt_id) else None

    def _zone_preview(self, prompt_id: str) -> tuple[str | None, str | None]:
        row = self._db.get_generation(prompt_id)
        if row is None:
            return self._files.preview(prompt_id)
        return (row.get("thumbnail_path"), self._host.animated_preview(row))

    def _video_history(self, intent: str) -> list[RecentVideo]:
        videos = [row for row in self.rebuildable_videos(self._db.list_generations())
                  if gallery.produced_output(row)]
        return [RecentVideo(row["prompt_id"], row.get("thumbnail_path"))
                for row in video_history(videos, intent, self._db.custom_combinations(),
                                         self._db.list_combine_video_uses())]

    def reread_names(self) -> None:
        self.widget.reread_names()

    def selection(self) -> dict:
        return {
            "image": self.widget.image_zone.current_id(),
            "videos": self.widget.dropped_videos(),
            "intent": self.widget.selected_intent(),
            "category": self.widget.selected_category(),
        }

    def restore(self, saved) -> None:
        match saved:
            case [image, video]:
                saved = {"image": image, "video": video}
        if not isinstance(saved, dict):
            return
        image_id = saved.get("image")
        if image_id and self._accepts_image(image_id):
            self.widget.image_zone.set_item(image_id)
        self.widget.set_intent(saved.get("intent") or action_settings.VIDEO)
        videos = saved.get("videos")
        if not isinstance(videos, dict):
            videos = {self.widget.selected_intent(): saved.get("video")}
        self.widget.set_dropped_videos({lane: video for lane, video in videos.items()
                                       if video and self._accepts_video(video)})
        self.widget.set_category(saved.get("category") or "")

    def rebuildable_videos(self, rows: list[dict]) -> list[dict]:
        return [row for row in rows
                if row.get("status") == GenerationStatus.COMPLETED
                and self._rebuildable_video_row(row)]

    def offer_the_actions(self, rows: list[dict]) -> None:
        lane = self.widget.selected_intent()
        offered = action_settings.available_categories(
            self.rebuildable_videos(rows), lane)
        state = self._state_of(self.widget.image_zone.current_id())
        if state:
            offered &= set(animation_paths.actions_for(state, lane))
        self.widget.set_available_categories(offered)

    def _state_of(self, image_id: str | None) -> str:
        row = self._db.get_generation(image_id) if image_id else None
        return (row or {}).get("image_state") or ""

    def image_dropped(self) -> None:
        self.offer_the_actions(self._db.list_generations())
        self.reconcile_generating()

    def _on_intent_changed(self, _intent: str) -> None:
        self.offer_the_actions(self._db.list_generations())
        self.reconcile_generating()

    def reconcile_generating(self) -> None:
        image_id = self.widget.image_zone.current_id()
        video_id = self.widget.video_zone.current_id()
        built = (self._combined_params(image_id, video_id, self.widget.selected_intent())
                 if image_id and video_id else None)
        self.widget.note_folder_generating(
            built is not None and self._jobs.job_for(self._folder_of(built)) is not None)

    def _on_request(self, request) -> None:
        if request.edit_first:
            if request.category:
                self._open_category(request.image_id, request.category, request.intent)
            else:
                self._open_combination(request.image_id, request.video_id,
                                       intent=request.intent)
        elif request.category:
            self._on_generate_category(request.image_id, request.category, request.intent)
        else:
            self._on_generate(request.image_id, request.video_id, request.intent)

    def _on_generate(self, image_id: str, video_id: str, intent: str) -> None:
        key = self._show_starting(image_id, video_id=video_id, intent=intent)

        def run():
            try:
                self._generate_combination(image_id, video_id, intent=intent)
            finally:
                self._starting.drop(key)

        self._after_painting(run)

    def _on_generate_category(self, image_id: str, category: str, intent: str) -> None:
        key = self._show_starting(image_id, category=category)
        self._after_painting(lambda: self.generate_category(
            image_id, category, intent, starting=key))

    def _after_painting(self, work) -> None:
        defer(self, work)

    def _show_starting(self, image_id: str, *, category: str = "",
                        video_id: str | None = None,
                        intent: str = action_settings.VIDEO) -> str:
        video_row = self._db.get_generation(video_id) if video_id else None
        built = (self._combined_params(image_id, video_id, intent)
                 if video_id and not category else None)
        edited = False
        if built is not None:
            workflow, params, _video_row, _image_row = built
            edited = gallery.prompts_differ_from(params, video_row, workflow)
        return self._starting.show(
            caption="A video from Combine, still being started",
            media_type=MediaType.VIDEO,
            job_kind=gallery.JobKind.VIDEO,
            action=category,
            source_video_thumbnail=None if category else (video_row or {}).get("thumbnail_path"),
            prompt_edited=edited,
            source_image=self._image_reference(image_id),
        )

    def _combined_params(self, image_id: str, video_id: str,
                         intent: str = action_settings.VIDEO, category: str = ""):
        image_row = self._db.get_generation(image_id)
        video_row = self._db.get_generation(video_id)
        if not video_row:
            return None
        workflow_name = video_row.get("workflow_name") or ""
        workflow = WORKFLOW_REGISTRY.get(workflow_name)
        if workflow is None or not gallery.is_image_conditioned(workflow_name):
            return None
        params = gallery.combined_params(video_row, self._image_reference(image_id), workflow)
        if params is None:
            return None
        if intent == action_settings.GENAU:
            params = gallery.cycle_shaped(params, workflow, category)
        return workflow, params, video_row, image_row

    def _open_combination(self, image_id: str, video_id: str,
                          intent: str = action_settings.VIDEO) -> None:
        built = self._combined_params(image_id, video_id, intent)
        if built is None:
            return
        workflow, params, video_row, _image_row = built
        self._open_prepared(workflow, params, self._image_still(image_id), video_row, ("", video_id, intent))

    def _open_prepared(self, workflow, params, still: str | None, video_row, settings_source: tuple) -> None:
        Combine = self._generate_pane_of().open_config(workflow.name, params)
        if Combine is None:
            return
        Combine.set_settings_source(*settings_source)
        Combine.show_combination(Combination(
            still, self._host.animated_preview(video_row) if video_row is not None else None))

    def _still_path(self, row: dict) -> str | None:
        preview = gallery.resolve_preview(row, OUTPUT_PLACES)
        if preview is not None and preview[1] == MediaType.IMAGE:
            return str(preview[0])
        return row.get("thumbnail_path")

    def _generate_combination(self, image_id: str, video_id: str, send: bool = False,
                              category: str = "",
                              intent: str = action_settings.VIDEO) -> None:
        built = self._combined_params(image_id, video_id, intent, category)
        if built is None:
            return
        workflow, params, _video_row, _image_row = built
        key = self._folder_of(built)
        if self._already_making_one(key, send):
            return
        prompt_id = self._jobs.start_prepared(key, workflow, params)
        if prompt_id:
            self._db.set_settings_source(prompt_id, category=category,
                                         video_prompt_id=video_id)
            if not category:
                self._db.record_combine_video_use(intent, video_id, prompt_id)
            self._mark_for_sending(prompt_id, send)
            self._host.reveal_launch(key)

    def _folder_of(self, built) -> str:
        workflow, params, video_row, _image_row = built
        return self._host.folder_key_of(_the_row_this_run_will_make(video_row, params, workflow))

    def _already_making_one(self, key: str, send: bool) -> bool:
        going = self._jobs.job_for(key)
        if going is None:
            return False
        if send:
            self._mark_for_sending(going.prompt_id, send)
            self._slideshows.note_voice_run(None, ALREADY_MAKING_ONE, kind=INFO)
        self._host.reveal_launch(key)
        return True

    def _category_candidates(self) -> list:
        return self.rebuildable_videos(self._db.list_generations())

    def _most_used_video(self, image_id: str, category: str, intent: str) -> str | None:
        if self._image_reference(image_id) is None:
            return None
        video_id = action_settings.most_used_video(category, self._category_candidates(), intent)
        logger.info("combine: category=%s intent=%s image=%s -> settings from %s",
                    category, intent, image_id, video_id)
        if video_id is None:
            self._say_no_past_video(category, intent)
        return video_id

    def _say_no_past_video(self, category: str, intent: str) -> None:
        said = action_settings.no_past_video(category, intent)
        if self._slideshows.showing is not None:
            self._slideshows.note_voice_run(None, said, kind=WARNING)
            return
        self._host.tell(NO_PAST_VIDEO, f"{action_settings.as_sentence(said)} — make one first, "
                                       "or drop a specific video instead.")

    def _curated_combination(self, image_id: str, category: str,
                             intent: str = action_settings.VIDEO):
        reference = self._image_reference(image_id)
        if reference is None:
            return None
        settings = (animation_settings.settings_for(intent, category, self._state_of(image_id))
                    or action_settings.pinned_settings(category, intent))
        built = (self._readied(action_settings.in_its_lane(settings, intent), reference)
                 if settings is not None else None)
        if built is None or intent != action_settings.GENAU:
            return built
        workflow, params = built
        return workflow, gallery.cycle_shaped(params, workflow, category)

    def _readied(self, settings: dict, reference: str):
        workflow = WORKFLOW_REGISTRY.get(settings.get("workflow") or "")
        if workflow is None or not gallery.is_image_conditioned(workflow.name):
            logger.warning("combine: workflow %r not usable", settings.get("workflow"))
            return None
        params = gallery.written_params(settings, reference, workflow)
        return None if params is None else (workflow, params)

    def _generate_curated(self, image_id: str, category: str, intent: str,
                          send: bool) -> bool:
        built = self._curated_combination(image_id, category, intent)
        if built is None:
            return False
        workflow, params = built
        logger.info("combine: category=%s intent=%s image=%s -> pinned settings",
                    category, intent, image_id)
        key = self._host.folder_key_for(workflow.name, params, workflow.version)
        if self._already_making_one(key, send):
            return True
        prompt_id = self._jobs.start_prepared(key, workflow, params)
        if prompt_id:
            self._db.set_settings_source(prompt_id, category=category)
            self._mark_for_sending(prompt_id, send)
            self._host.reveal_launch(key)
        return True

    def _mark_for_sending(self, prompt_id: str, send: bool) -> None:
        if send:
            self._db.mark_genau_requested(prompt_id)

    def generate_category(self, image_id: str, category: str,
                          intent: str = action_settings.VIDEO, send: bool = False,
                          starting: str | None = None) -> None:
        try:
            if not self._generate_curated(image_id, category, intent, send):
                video_id = self._most_used_video(image_id, category, intent)
                if video_id is not None:
                    self._generate_combination(image_id, video_id, send, category, intent)
        finally:
            self._starting.drop(starting)

    def _open_category(self, image_id: str, category: str,
                       intent: str = action_settings.VIDEO) -> None:
        reference = self._image_reference(image_id)
        if reference is None:
            return
        built = (self._curated_combination(image_id, category, intent)
                 or self._readied(action_settings.starting_settings(intent), reference))
        if built is not None:
            workflow, params = built
            self._open_prepared(workflow, params, self._image_still(image_id), None, (category, None, intent))

    def send_to_genau_if_requested(self, row: dict | None) -> None:
        if not row or not row.get("genau_requested_at") or row.get("genau_exported_at"):
            return
        preview = gallery.resolve_preview(row, OUTPUT_PLACES)
        if preview is None or preview[1] != MediaType.VIDEO:
            return
        try:
            GENAU_LANE.send(preview[0], row["prompt_id"], db=self._db,
                            inbox=self._inbox, places=OUTPUT_PLACES)
        except Exception as e:
            logger.warning("Automatic send to Genau failed for %s: %s",
                           row.get("prompt_id"), e)
            return
        logger.info("genau: sent %s down the Genau lane", preview[0].name)

    def _already_genaud(self, row: dict) -> bool:
        return any(
            other.get("genau_requested_at")
            and (gallery.is_in_progress(other) or gallery.produced_output(other))
            and gallery.find_source_image_id(other, [row]) is not None
            for other in self._db.list_generations()
        )

    def animate_it(self, image_id: str | None, asked) -> tuple[str | None, str, str]:
        row = self._db.get_generation(image_id) if image_id else None
        if row is None or gallery.media_type_of_row(row) != MediaType.IMAGE:
            return None, NOT_AN_IMAGE, WARNING
        loop = asked.lane == action_settings.GENAU
        if loop and self._already_genaud(row):
            return None, ALREADY_GENAUD, WARNING
        answer = what_to_animate(asked, row.get("image_state") or "")
        if answer.action is None:
            return None, answer.said, ERROR if answer.unsupported else WARNING
        action = answer.action
        available = action_settings.available_categories(
            self.rebuildable_videos(self._db.list_generations()), asked.lane)
        if action not in available:
            return None, action_settings.no_past_video(action, asked.lane), WARNING
        logger.info("animate as: image=%s lane=%s -> action=%s", image_id, asked.lane, action)
        self.generate_category(image_id, action, asked.lane, send=loop)
        return image_id, f"animating as “{action}”", INFO


def _the_row_this_run_will_make(video_row: dict, params: dict, workflow) -> dict:
    return {**dict(video_row), "params_json": json.dumps(params),
            "workflow_version": workflow.version}
