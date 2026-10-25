"""Combine: a video's settings run again on a dropped picture.

The fifth of the gallery's screen concerns to come out of the view that used to
hold all of them. What lives here is the whole act -- the panel with its two drop
slots, what a dropped item lends each and how it shows there, the lane and
the act picked beside them, and every way settings are found and launched: the
dropped video's own, the settings assigned for an act, the act's most-used past
video, or the lane's own workflow as it starts.

Two things ride with it because nothing else has them. The stand-in row a press
puts in the queue before there is a job: everything between the press and a real
job takes seconds, and a button that seems to do nothing reads as an app that has
died. And the spoken "animate as", which is this same act asked for out loud: the
clip handed on the moment it exists, and a second ask over the same picture
refused, so saying it twice does not spend the GPU twice.

What stays with the host is what a launch is *of* and where it lands: the folder
key a config belongs to, the pictures the gallery is holding, and the tree move
that shows a launch. :class:`CombineHost` names each of those.
"""
from __future__ import annotations

import json
import logging
from typing import Protocol

from PyQt6.QtCore import QObject

from origenerator import (
    act_settings,
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
from origenerator.gui.combine_panel import CombinePanel
from origenerator.gui.deferred import defer
from origenerator.gui.file_pick import FILE_FILTERS, pick_a_file
from origenerator.gui.generation_job import JobState
from origenerator.gui.inflight import InFlightItem, RunReading
from origenerator.gui.notice_overlay import ERROR, NOTICE, WARNING
from origenerator.gui.zone_items import FilesOnly
from origenerator.item_names import ItemNames
from origenerator.media import MediaType, media_type_from_filename
from origenerator.video_history import video_history
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)

ALREADY_GENAUD = "already Genau'd"
ALREADY_MAKING_ONE = "already making it — handing that one over"

# What a picture can be animated as is read off what it SHOWS, and a picture
# nobody has said that about yet can be animated as nothing at all. Said
# rather than guessed: the guess would be an act the picture cannot do, which
# is minutes of the one machine spent on a clip that was never going to work.
NOT_A_PICTURE = "only a picture can be animated"

NO_PAST_VIDEO = "No past video yet"


class CombineHost(Protocol):
    """What a combine needs of the gallery around it, and nothing else."""

    def image_config_index(self) -> dict:
        """Which picture made each file the gallery holds."""

    def animated_preview(self, row: dict) -> str | None:
        """A looping preview of a video row, for a slot and for a prepared tab."""

    def folder_key_of(self, row: dict) -> str:
        """The settings-folder key a stored row lands in."""

    def folder_key_for(self, workflow_name: str, params: dict,
                       workflow_version: str | None = None) -> str:
        """The same key, for a caller holding a config rather than a row."""

    def queue_changed(self) -> None:
        """Redraw the line: a stand-in row went on it or came off it."""

    def reveal_launch(self, key: str) -> None:
        """Show a just-launched combine — its folder if the tree has one, else
        the Recents collection its card will appear on."""

    def follow_link(self, prompt_id: str) -> None:
        """Go to a generation a slot is holding."""

    def tell(self, title: str, message: str) -> None:
        """Say something that needs acknowledging, where nobody is watching a
        fullscreen picture."""


class CombineController(QObject):
    """The combine panel, and every way settings reach a dropped picture."""

    def __init__(self, host: CombineHost, *, parent: QObject, db, jobs, client,
                 info_tabs_of, slideshows, inbox: evolver_export.EvolverInbox | None = None,
                 names: ItemNames | None = None):
        super().__init__(parent)
        self._host = host
        self._db = db
        self._jobs = jobs
        self._names = names or ItemNames(db)
        self._files = FilesOnly(places=OUTPUT_PLACES, input_dir=COMFYUI_INPUT_DIR)
        # Where a clip is handed to Evolver. Asked for rather than performed
        # here: the destination is one object's to know, and a test points it at
        # a directory of its own instead of patching a constant this module
        # imported (origenerator.evolver_export).
        self._inbox = inbox or evolver_export.default_inbox()
        self._client = client
        # The tabs are built by the window's own layout, after this: asked for
        # rather than held, so a prepared combination reaches whichever tabs
        # exist by then.
        self._info_tabs_of = info_tabs_of
        self._slideshows = slideshows
        # Stand-in queue rows for a Generate pressed but not yet a job, by key
        # (:meth:`_show_launching`), and the counter their keys are drawn from —
        # anything that can't be mistaken for a prompt id.
        self._launching: dict[str, InFlightItem] = {}
        self._launch_seq = 0
        # Combine: drop an image + an i2v video, Generate re-runs that video's
        # settings on the image. Needs a client to generate, so it hides without one.
        self.panel = CombinePanel(
            self._picture_lent_by, self._video_lent_by, self._slot_preview,
            self._video_history, named=self._names.prompt_id_of, name_of=self._name_of,
            browse_picture=self._browse_picture, leads_to=self._item_held)
        self.panel.video_used.connect(self._db.record_combine_video_use)
        # Both Generate paths go through a wrapper that puts a stand-in row in the
        # line first: the work between the press and a real job is seconds long,
        # and a button that seems to do nothing reads as an app that has died.
        self.panel.combine_requested.connect(self._on_request)
        self._animation_settings = None
        self.panel.animation_settings_requested.connect(self._on_animation_settings)
        self.panel.item_activated.connect(self._host.follow_link)
        # Switching lanes re-asks which acts are answerable: an act with plenty of
        # long-form video under it may have no loop at all.
        self.panel.intent_changed.connect(self._on_intent_changed)
        # A picture dropped in narrows the acts too, so the list is re-asked
        # for the moment one lands rather than only when the lane changes.
        self.panel.image_slot.changed.connect(self.picture_dropped)
        self.panel.video_slot.changed.connect(self.reconcile_generating)
        if client is None:
            self.panel.hide()

    def _on_animation_settings(self) -> None:
        from origenerator.own_window import show_or_say  # noqa: PLC0415 -- Qt only

        if self._animation_settings is not None and self._animation_settings.isVisible():
            self._animation_settings.raise_()
            self._animation_settings.activateWindow()
            return
        built = the_animation_window()
        if not show_or_say("Checking animations", built, parent=self.panel):
            self._animation_settings = built

    # --- what the slots take, and what the session keeps ---------------------

    def _accepts_image(self, image_id: str) -> bool:
        """Whether the image slot can hold this: a generation that is a picture
        with a file to seed an i2v from (a video's clip can't be a start frame),
        or a picture file from outside the gallery."""
        return self._picture_reference(image_id) is not None

    def _picture_reference(self, image_id: str) -> str | None:
        """What a graph loads the held picture by, ``None`` for what is no picture."""
        row = self._db.get_generation(image_id)
        if row is not None:
            if gallery.media_type_of_row(row) != MediaType.IMAGE:
                return None
            return gallery.output_file_reference(gallery.row_output_files(row))
        path = self._files.path_of(image_id)
        if path is None or media_type_from_filename(path.name) != MediaType.IMAGE:
            return None
        return str(path)

    def _picture_still(self, image_id: str) -> str | None:
        row = self._db.get_generation(image_id)
        return self._still_path(row) if row is not None else self._picture_reference(image_id)

    def _item_held(self, held: str) -> str | None:
        return held if self._db.get_generation(held) is not None else None

    def _name_of(self, held: str) -> str:
        if self._item_held(held) is not None:
            return self._names.of(held)
        return self._files.name_of(held)

    def _browse_picture(self) -> None:
        path = pick_a_file(self.panel, "Image", FILE_FILTERS[MediaType.IMAGE])
        if path:
            self.panel.image_slot.set_item(path)

    def _picture_lent_by(self, prompt_id: str) -> str | None:
        row = self._db.get_generation(prompt_id)
        if row is not None and gallery.media_type_of_row(row) == MediaType.VIDEO:
            prompt_id = gallery.source_image_id_in(row, self._host.image_config_index())
        return prompt_id if prompt_id and self._accepts_image(prompt_id) else None

    def _rebuildable_video_row(self, row) -> bool:
        """Whether ``row`` is a video whose i2v settings the app can rebuild — so its
        settings can be re-run on a new image. (``is_image_conditioned`` already
        implies the workflow is registered.) The shared gate under both the video
        drop slot and the category dropdown's candidate pool."""
        return bool(
            row and gallery.media_type_of_row(row) == MediaType.VIDEO
            and gallery.is_image_conditioned(row.get("workflow_name") or "")
        )

    def _accepts_video(self, prompt_id: str) -> bool:
        return self._rebuildable_video_row(self._db.get_generation(prompt_id))

    def _video_lent_by(self, prompt_id: str) -> str | None:
        return prompt_id if self._accepts_video(prompt_id) else None

    def _slot_preview(self, prompt_id: str) -> tuple[str | None, str | None]:
        """A dropped item's (thumbnail, looping-preview) paths for its slot: a video
        loops its clip, an image shows its still. Either may be ``None`` when absent."""
        row = self._db.get_generation(prompt_id)
        if row is None:
            return self._files.preview(prompt_id)
        return (row.get("thumbnail_path"), self._host.animated_preview(row))

    def _video_history(self, intent: str) -> list[str]:
        return video_history(self._db.custom_combinations(), intent,
                             self._db.list_combine_video_uses())

    def selection(self) -> dict:
        return {
            "image": self.panel.image_slot.current_id(),
            "videos": self.panel.dropped_videos(),
            "intent": self.panel.selected_intent(),
            "category": self.panel.selected_category(),
        }

    def restore(self, saved) -> None:
        """Put the combine panel back the way a session left it, skipping an item
        that has since been deleted or no longer fits its slot, and an act the
        lane can no longer answer.

        The lane goes in before the act: it decides which acts are answerable,
        and ``set_category`` refuses one that is grayed out under it.

        A list of two is what sessions before this wrote — the slots alone — and
        is still read, so an existing ``ui_state.json`` restores what it has.
        """
        if isinstance(saved, (list, tuple)) and len(saved) == 2:
            saved = {"image": saved[0], "video": saved[1]}
        if not isinstance(saved, dict):
            return
        image_id = saved.get("image")
        if image_id and self._accepts_image(image_id):
            self.panel.image_slot.set_item(image_id)
        self.panel.set_intent(saved.get("intent") or act_settings.VIDEO)
        videos = saved.get("videos")
        if not isinstance(videos, dict):
            videos = {self.panel.selected_intent(): saved.get("video")}
        self.panel.set_dropped_videos({lane: video for lane, video in videos.items()
                                       if video and self._accepts_video(video)})
        self.panel.set_category(saved.get("category") or "")

    def rebuildable_videos(self, rows: list[dict]) -> list[dict]:
        """The completed, rebuildable i2v videos among ``rows`` — the pool an act's
        settings are mined from, each carrying the act it was launched as."""
        return [row for row in rows
                if row.get("status") == GenerationStatus.COMPLETED
                and self._rebuildable_video_row(row)]

    def offer_the_acts(self, rows: list[dict]) -> None:
        """Gray out the acts this press could not answer: those with no video to
        mine settings from, and -- once a picture is in the slot -- those
        :mod:`origenerator.animation_paths` says it cannot start from. A picture
        nobody has sorted yet narrows nothing."""
        lane = self.panel.selected_intent()
        offered = act_settings.available_categories(
            self.rebuildable_videos(rows), lane)
        state = self._state_of(self.panel.image_slot.current_id())
        if state:
            offered &= set(animation_paths.acts_for(state, lane))
        self.panel.set_available_categories(offered)

    def _state_of(self, image_id: str | None) -> str:
        """What the picture in the slot was sorted as showing, ``""`` for an
        empty slot or a picture nobody has sorted yet."""
        row = self._db.get_generation(image_id) if image_id else None
        return (row or {}).get("picture_state") or ""

    def picture_dropped(self) -> None:
        """The picture in the slot changed: re-ask which acts it can start from."""
        self.offer_the_acts(self._db.list_generations())
        self.reconcile_generating()

    def _on_intent_changed(self, _intent: str) -> None:
        """Re-gray the act list for the lane just chosen."""
        self.offer_the_acts(self._db.list_generations())
        self.reconcile_generating()

    def reconcile_generating(self) -> None:
        image_id = self.panel.image_slot.current_id()
        video_id = self.panel.video_slot.current_id()
        built = (self._combined_params(image_id, video_id, self.panel.selected_intent())
                 if image_id and video_id else None)
        self.panel.note_folder_generating(
            built is not None and self._jobs.job_for(self._folder_of(built)) is not None)

    # --- the line's answer to the press, before there is a job ---------------

    def _on_request(self, request) -> None:
        """Answer one press of the panel: run the chosen settings now, or hand them to
        a generate tab to change first (:class:`CombineRequest`)."""
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
        """The combine panel's Generate with a dropped video, with the line
        showing it at once.

        The launch itself is left for the next turn of the event loop: reading
        every stored generation to check for a duplicate, building the params and
        posting the prompt all happen on this thread, and nothing painted while
        they did — so the stand-in row would have appeared only once the work it
        was standing in for was already over.
        """
        key = self._show_launching(image_id, video_id=video_id, intent=intent)

        def run():
            try:
                self._generate_combination(image_id, video_id, intent=intent)
            finally:
                self._drop_launching(key)

        self._after_painting(run)

    def _on_generate_category(self, image_id: str, category: str, intent: str) -> None:
        """The combine panel's Generate with an act picked, with the line showing
        it at once; :meth:`generate_category` drops the stand-in however the
        launch turns out."""
        key = self._show_launching(image_id, category=category)
        self._after_painting(lambda: self.generate_category(
            image_id, category, intent, launching=key))

    def _after_painting(self, work) -> None:
        """Run ``work`` on the next turn of the event loop, once what has just
        been laid out has actually reached the screen.

        A seam as much as a call: the suite replaces this with a straight-through
        version, so a test can press and inspect in
        one breath rather than pumping an event loop for every launch.
        """
        defer(self, work)

    def _show_launching(self, image_id: str, *, category: str = "",
                        video_id: str | None = None,
                        intent: str = act_settings.VIDEO) -> str:
        """Put a stand-in row at the back of the line for a Generate just pressed,
        and return its key. It carries everything already known about the run, so
        the row that replaces it is the same row with its price filled in, and it
        offers no Cancel: there is nothing on the server to stop yet."""
        self._launch_seq += 1
        key = f"launching-{self._launch_seq}"
        video_row = self._db.get_generation(video_id) if video_id else None
        built = (self._combined_params(image_id, video_id, intent)
                 if video_id and not category else None)
        edited = False
        if built is not None:
            workflow, params, _video_row, _image_row = built
            edited = gallery.prompts_differ_from(params, video_row, workflow)
        self._launching[key] = InFlightItem(
            key=key,
            caption="A video from Combine, still being started",
            reading=RunReading(status=JobState.QUEUED),
            reveal=lambda: None,  # no folder to open yet: it has no settings
            media_type=MediaType.VIDEO,
            job_kind=gallery.JobKind.VIDEO,
            act=category,
            # The same rule the finished row follows: a picked act names itself in
            # the text, and only a dropped video is shown.
            source_video_thumbnail=None if category else (video_row or {}).get("thumbnail_path"),
            prompt_edited=edited,
            source_image=self._picture_reference(image_id),
            starting=True,
        )
        self._host.queue_changed()
        return key

    def _drop_launching(self, key: str | None) -> None:
        """Take a stand-in row back off the line — what it stood for is a real row
        now, or never became one. A no-op for a key already gone, so an exit path
        that drops it twice costs nothing."""
        if key is not None and self._launching.pop(key, None) is not None:
            self._host.queue_changed()

    def launching_rows(self) -> list[InFlightItem]:
        """Every Generate pressed but not yet turned into a job, for the line."""
        return list(self._launching.values())

    # --- building and launching a combination --------------------------------

    def _combined_params(self, image_id: str, video_id: str,
                         intent: str = act_settings.VIDEO, category: str = ""):
        """The ``(workflow, params, video_row, image_row)`` for re-running
        ``video_id``'s settings on ``image_id`` — the video's workflow and params,
        fresh seeds, and the dropped picture as the input image; ``image_row``
        is ``None`` for a picture browsed from outside the gallery.

        Under ``GENAU`` the settings are then re-cut to hold one cycle and smoothed
        back out (:func:`~origenerator.gallery.combine.cycle_shaped`). The lane
        used to choose only WHICH settings were mined, and from there a Genau flick
        was made exactly like any other video; it can't be, because what Genau
        needs of a clip is a property of the clip's own length, and the past clip
        being mined was made before anyone knew that.

        ``None`` when the pair can't be combined: the video row is gone or isn't
        a rebuildable image-conditioned video, or there is no picture file to
        seed from. Shared by the Generate and Open-in-generator paths.
        """
        image_row = self._db.get_generation(image_id)
        video_row = self._db.get_generation(video_id)
        if not video_row:
            return None
        workflow_name = video_row.get("workflow_name") or ""
        workflow = WORKFLOW_REGISTRY.get(workflow_name)
        if workflow is None or not gallery.is_image_conditioned(workflow_name):
            return None  # the video must be rebuildable and image-conditioned
        params = gallery.combined_params(video_row, self._picture_reference(image_id), workflow)
        if params is None:
            return None  # no picture file to seed from
        if intent == act_settings.GENAU:
            params = gallery.cycle_shaped(params, workflow, category)
        return workflow, params, video_row, image_row

    def _open_combination(self, image_id: str, video_id: str,
                          intent: str = act_settings.VIDEO) -> None:
        """Open a dropped image + video's settings as an editable generate tab instead
        of running it — the combine panel's "Edit individual…" path. The tab is
        prefilled with the same combination Generate would launch, ready to tweak,
        and shows the pair it was opened with rather than an empty pane."""
        built = self._combined_params(image_id, video_id, intent)
        if built is None:
            return
        workflow, params, video_row, _image_row = built
        self._open_prepared(workflow, params, self._picture_still(image_id), video_row,
                            "", video_id, intent)

    def _open_prepared(self, workflow, params, still: str | None, video_row,
                       category: str, video_id: str | None, intent: str) -> None:
        """Hand a built combination to a generate tab: its settings on the form, its
        two halves in the preview, and the mark saying where they came from,
        which the links under the form show.

        The preview is the point of the pair being visible at all — nothing has
        been generated from it yet, so the pane would otherwise sit on the line a
        tab pointed at nothing wears, with both things the tab is about on hand.
        A curated act has no ``video_row`` under it, and shows the frame alone.
        """
        panel = self._info_tabs_of().open_config(workflow.name, params)
        if panel is None:
            return
        panel.set_settings_source(category, video_id, intent)
        panel.show_combination(Combination(
            still, self._host.animated_preview(video_row) if video_row is not None else None))

    def _still_path(self, row: dict) -> str | None:
        """The best picture of ``row`` for a pane to show: its full-size output
        where that is a still, else the stored thumbnail (which a pane this big
        would be enlarging), else nothing."""
        preview = gallery.resolve_preview(row, OUTPUT_PLACES)
        if preview is not None and preview[1] == MediaType.IMAGE:
            return str(preview[0])
        return row.get("thumbnail_path")

    def _generate_combination(self, image_id: str, video_id: str, send: bool = False,
                              category: str = "",
                              intent: str = act_settings.VIDEO) -> None:
        """Generate a new video from a dropped image + a dropped video's settings,
        landing it in the folder for that (image × settings) combination.

        ``send`` hands the clip to Genau the moment it exists, as a spoken
        animation asks, and takes no dialog at all, because such a command is
        answered in the slideshow's notice. ``category`` names the act the dropdown was
        set to, when one was picked.
        """
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
            self._slideshows.note_voice_run(None, ALREADY_MAKING_ONE, kind=NOTICE)
        self._host.reveal_launch(key)
        return True

    # --- finding the settings an act names ------------------------------------

    def _category_candidates(self) -> list:
        """The pool of past videos, read fresh at generate time rather than from the last
        rebuild — the gallery may have gained a video since."""
        return self.rebuildable_videos(self._db.list_generations())

    def _most_used_video(self, image_id: str, category: str, intent: str) -> str | None:
        """The ``prompt_id`` of the act's most-used rebuildable video, or ``None``
        with a hint on screen so a press never silently does nothing."""
        if self._picture_reference(image_id) is None:
            return None
        video_id = act_settings.most_used_video(category, self._category_candidates(), intent)
        logger.info("combine: category=%s intent=%s image=%s -> settings from %s",
                    category, intent, image_id, video_id)
        if video_id is None:
            self._say_no_past_video(category, intent)
        return video_id

    def _say_no_past_video(self, category: str, intent: str) -> None:
        """Say the act has no past video to take settings from — in the notice of the
        fullscreen surface being spoken to when one is up, and in a dialog
        otherwise. A dialog thrown over a picture someone is looking at is the one
        place this must never appear."""
        said = act_settings.no_past_video(category, intent)
        if self._slideshows.showing is not None:
            self._slideshows.note_voice_run(None, said, kind=WARNING)
            return
        self._host.tell(NO_PAST_VIDEO, f"{act_settings.as_sentence(said)} — make one first, "
                                       "or drop a specific video instead.")

    def _curated_combination(self, image_id: str, category: str,
                             intent: str = act_settings.VIDEO):
        """The ``(workflow, params)`` for ``category``'s ``intent`` settings on the
        dropped image: those assigned for it, else the overlay's pin
        (:func:`act_settings.pinned_settings`), with fresh seeds and, in the
        Genau lane, re-cut to one cycle.

        ``None`` when neither is there, the one there names an unknown or
        non-image-conditioned workflow, or the image row is gone or has no output
        file to seed from.
        """
        reference = self._picture_reference(image_id)
        if reference is None:
            return None
        settings = (animation_settings.settings_for(intent, category, self._state_of(image_id))
                    or act_settings.pinned_settings(category, intent))
        built = (self._readied(act_settings.in_its_lane(settings, intent), reference)
                 if settings is not None else None)
        if built is None or intent != act_settings.GENAU:
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
        """Launch ``category``'s curated ``intent`` settings on the dropped image;
        ``False`` when the act has no usable curated entry, so the caller falls back
        to mining."""
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
            # The act, with no video under it: curated settings are pinned in the
            # overlay, so there is no past run for the queue row to show in gray.
            self._db.set_settings_source(prompt_id, category=category)
            self._mark_for_sending(prompt_id, send)
            self._host.reveal_launch(key)
        return True

    def _mark_for_sending(self, prompt_id: str, send: bool) -> None:
        """Stamp a just-launched run to hand its clip on the moment it exists.

        Only a spoken animation asks for this. Pressing Generate leaves the clip
        in the gallery for Send-to-Genau, because someone at the keyboard can look
        at it first.
        """
        if send:
            self._db.mark_genau_requested(prompt_id)

    def generate_category(self, image_id: str, category: str,
                          intent: str = act_settings.VIDEO, send: bool = False,
                          launching: str | None = None) -> None:
        """Run the settings that fit ``category`` on the dropped image: the
        settings assigned for it, else the act's most-used past video. ``intent``
        chooses the lane both answer from; ``send`` hands the finished clip to
        Genau without a second ask.

        ``launching`` is the stand-in row the press already put in the line
        (:meth:`_show_launching`), taken back off however this ends.
        """
        try:
            if not self._generate_curated(image_id, category, intent, send):
                video_id = self._most_used_video(image_id, category, intent)
                if video_id is not None:
                    self._generate_combination(image_id, video_id, send, category, intent)
        finally:
            self._drop_launching(launching)

    def _open_category(self, image_id: str, category: str,
                       intent: str = act_settings.VIDEO) -> None:
        """Open the settings assigned for ``category`` from this picture as an
        editable generate tab: "Edit individual…". With nothing assigned it opens
        the lane's own workflow as it starts, never a past video's settings.

        A run started from that tab is an ordinary Generate, so Genau settings opened
        this way is not auto-sent; the tab's own Send-to-Genau does it once the clip
        is there.
        """
        reference = self._picture_reference(image_id)
        if reference is None:
            return
        built = (self._curated_combination(image_id, category, intent)
                 or self._readied(act_settings.starting_settings(intent), reference))
        if built is not None:
            workflow, params = built
            self._open_prepared(workflow, params, self._picture_still(image_id), None,
                                category, None, intent)

    # --- the Genau lane: said out loud, and handed on ------------------------

    def send_to_genau_if_requested(self, row: dict | None) -> None:
        """Hand a just-finished clip to the Genau lane, if that is what it was for.

        The run was stamped at launch (:meth:`_mark_for_sending`). Only a video
        with a file on disk that has not already gone is sent, and a failure is
        logged rather than shown: the clip is safe in the gallery either way. The
        lane names the folder, so a spoken send and a pressed one land alike.
        """
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
        """Whether this picture has been Genau'd — a clip made from it already, or
        one on the way. Saying it twice is what someone does when the first time
        appeared to do nothing, and a second identical run spends minutes of the
        one GPU on a clip that already exists.

        A run is a row stamped as spoken for (:meth:`_mark_for_sending`) and
        matched to this picture by its start frame, counted whether it is still
        coming or has landed, and read from the database so one reconnected after
        a restart still counts. A row that errored counts as nothing.
        """
        return any(
            other.get("genau_requested_at")
            and (gallery.is_in_progress(other) or gallery.produced_output(other))
            and gallery.find_source_image_id(other, [row]) is not None
            for other in self._db.list_generations()
        )

    def animate_it(self, image_id: str | None, asked) -> tuple[str | None, str, str]:
        """Animate a picture as the act an "animate as" named, in the lane it
        named: the id it launched on (``None`` when it didn't), the line the
        speaking surface should say, and its kind.

        An act left unsaid is settled by what the picture shows, through
        :func:`~origenerator.animate_command.what_to_animate`. From there it is the
        ordinary category path: the loop lane is stamped to hand its clip on and
        guarded against being said twice (:meth:`_already_genaud`), and the
        full-length lane is left in the gallery.
        """
        row = self._db.get_generation(image_id) if image_id else None
        if row is None or gallery.media_type_of_row(row) != MediaType.IMAGE:
            return None, NOT_A_PICTURE, WARNING
        loop = asked.lane == act_settings.GENAU
        if loop and self._already_genaud(row):
            return None, ALREADY_GENAUD, WARNING
        answer = what_to_animate(asked, row.get("picture_state") or "")
        if answer.act is None:
            return None, answer.said, ERROR if answer.unsupported else WARNING
        act = answer.act
        available = act_settings.available_categories(
            self.rebuildable_videos(self._db.list_generations()), asked.lane)
        if act not in available:
            return None, act_settings.no_past_video(act, asked.lane), WARNING
        logger.info("animate as: image=%s lane=%s -> act=%s", image_id, asked.lane, act)
        self.generate_category(image_id, act, asked.lane, send=loop)
        return image_id, f"animating as “{act}”", NOTICE


def _the_row_this_run_will_make(video_row: dict, params: dict, workflow) -> dict:
    return {**dict(video_row), "params_json": json.dumps(params),
            "workflow_version": workflow.version}
