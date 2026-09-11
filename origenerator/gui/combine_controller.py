"""Combine: a video's recipe run again on a dropped picture.

The fifth of the gallery's screen concerns to come out of the view that used to
hold all of them. What lives here is the whole act -- the panel with its two drop
slots, what each slot accepts and what it shows of a dropped item, the lane and
the act picked beside them, and every way a recipe is found and launched: the
dropped video's own, the one pinned in the overlay for an act, or the one a local
model mines out of past clips that fit the picture's situation.

Two things ride with it because nothing else has them. The stand-in row a press
puts in the queue before there is a job: everything between the press and a real
job takes seconds, and a button that seems to do nothing reads as an app that has
died. And the spoken "genau it", which is this same act asked for out loud -- the
act read off the picture's own prompt, the clip handed on the moment it exists,
and the picture held from the moment the word is heard until its row exists, so
saying it twice into that silence does not spend the GPU twice.

What stays with the host is what a launch is *of* and where it lands: the folder
key a config belongs to, the rows the gallery is holding, and the tree move that
shows a launch. :class:`CombineHost` names each of those.
"""
from __future__ import annotations

import json
import logging
from functools import partial
from typing import Protocol

from PyQt6.QtCore import QObject

from origenerator import evolver_export, gallery, recipe_match
from origenerator.config import (
    COMFYUI_OUTPUT_DIR,
    EVOLVER_INBOX_DIR,
    LOCAL_LLM_BASE_URL,
    LOCAL_LLM_MODEL,
    VIDEO_SCENE_MATCH_SYSTEM_PROMPT,
)
from origenerator.generation_config import randomize_seeds
from origenerator.gui.combine_panel import CombinePanel
from origenerator.gui.deferred import defer
from origenerator.gui.export_lane import GENAU as GENAU_LANE
from origenerator.gui.inflight import InFlightItem
from origenerator.gui.reroll_prompt import REROLL_BOTH, REROLL_IMAGE, REROLL_VIDEO
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)

# What a spoken "genau it" says when the picture already has its clip, or has one
# on the way. Said rather than run, and said the same way wherever it is reached
# from: the corner of the surface being spoken to, never a dialog -- that
# question thrown over the picture someone is talking to is the one thing that
# must never appear.
ALREADY_GENAUD = "🎤 already Genau'd"


class CombineHost(Protocol):
    """What a combine needs of the gallery around it, and nothing else."""

    def image_rows(self) -> list[dict]:
        """The image rows the gallery is holding — what a start frame is found
        among, without a query per video."""

    def animated_preview(self, row: dict) -> str | None:
        """A looping preview of a video row, for a slot and for a prepared tab."""

    def folder_key_of(self, row: dict) -> str:
        """The settings-folder key a stored row lands in."""

    def folder_key_for(self, workflow_name: str, params: dict,
                       workflow_version: str | None = None) -> str:
        """The same key, for a caller holding a config rather than a row."""

    def would_reproduce_a_completed_run(self, workflow, params: dict) -> bool:
        """Whether launching this would re-create a byte-identical past run."""

    def off_thread(self, work, done) -> None:
        """Run one slow call away from the UI and hand its result back here —
        asking the model which recipe fits is seconds of network wait."""

    def queue_changed(self) -> None:
        """Redraw the line: a stand-in row went on it or came off it."""

    def reveal_launch(self, key: str) -> None:
        """Show a just-launched combine — its folder if the tree has one, else
        the Recents shelf its card will appear on."""

    def ask_which_seed(self, workflow, *, can_reroll_image: bool) -> str | None:
        """Ask which seed to re-roll rather than reproduce a past run, returning
        ``None`` when the answer is to do nothing."""

    def tell(self, title: str, message: str) -> None:
        """Say something that needs acknowledging, where nobody is watching a
        fullscreen picture."""


class CombineController(QObject):
    """The combine panel, and every way a recipe reaches a dropped picture."""

    def __init__(self, host: CombineHost, *, parent: QObject, db, reroll, client,
                 info_tabs_of, shows):
        super().__init__(parent)
        self._host = host
        self._db = db
        self._reroll = reroll
        self._client = client
        # The tabs are built by the window's own layout, after this: asked for
        # rather than held, so a prepared combination reaches whichever tabs
        # exist by then.
        self._info_tabs_of = info_tabs_of
        self._shows = shows
        # Stand-in queue rows for a Generate pressed but not yet a job, by key
        # (:meth:`_show_launching`), and the counter their keys are drawn from —
        # anything that can't be mistaken for a prompt id.
        self._launching: dict[str, InFlightItem] = {}
        self._launch_seq = 0
        # Pictures a spoken "genau it" is still finding a recipe for: the mined
        # tier asks a local model, which thinks for several seconds, and that is
        # exactly the silence a second command is said into.
        self._genau_resolving: set[str] = set()
        # Combine: drop an image + an i2v video, Generate re-runs that video's
        # recipe on the image. Needs a client to generate, so it hides without one.
        self.panel = CombinePanel(
            self._accepts_image, self._accepts_video, self._slot_preview)
        # Both Generate paths go through a wrapper that puts a stand-in row in the
        # line first: the work between the press and a real job is seconds long,
        # and a button that seems to do nothing reads as an app that has died.
        self.panel.generate_requested.connect(self._on_generate)
        self.panel.category_requested.connect(self._on_generate_category)
        self.panel.open_requested.connect(
            lambda image_id, video_id, category="": self._open_combination(
                image_id, video_id, category, self.panel.selected_intent()))
        self.panel.open_category_requested.connect(self._open_category)
        # Switching lanes re-asks which acts are answerable: an act with plenty of
        # long-form video under it may have no loop at all.
        self.panel.intent_changed.connect(self._on_intent_changed)
        self.panel.setVisible(client is not None)

    # --- what the slots take, and what the session keeps ---------------------

    def _accepts_image(self, prompt_id: str) -> bool:
        """Whether the image slot accepts a dropped generation: an image with a
        file to seed an i2v from (not merely anything that produced a file — a
        video's clip would satisfy that and can't be a start frame)."""
        row = self._db.get_generation(prompt_id)
        return bool(
            row and gallery.media_type_of_row(row) == "image"
            and gallery.output_file_reference(gallery.row_output_files(row)) is not None
        )

    def _rebuildable_video_row(self, row) -> bool:
        """Whether ``row`` is a video whose i2v recipe the app can rebuild — so its
        settings can be re-run on a new image. (``is_image_conditioned`` already
        implies the workflow is registered.) The shared gate under both the video
        drop slot and the category dropdown's candidate pool."""
        return bool(
            row and gallery.media_type_of_row(row) == "video"
            and gallery.is_image_conditioned(row.get("workflow_name") or "")
        )

    def _accepts_video(self, prompt_id: str) -> bool:
        """Whether the video slot accepts a dropped generation (see
        :meth:`_rebuildable_video_row`)."""
        return self._rebuildable_video_row(self._db.get_generation(prompt_id))

    def _slot_preview(self, prompt_id: str) -> tuple[str | None, str | None]:
        """A dropped item's (thumbnail, looping-preview) paths for its slot: a video
        loops its clip, an image shows its still. Either may be ``None`` when absent."""
        row = self._db.get_generation(prompt_id)
        if row is None:
            return (None, None)
        return (row.get("thumbnail_path"), self._host.animated_preview(row))

    def selection(self) -> dict:
        """Everything the combine panel is holding, for session save: the two
        slots, the lane and the act.

        All four, because all four are choices the user made and none is
        recoverable from the others — an act says nothing about which lane
        answers it, and a restart that put the picture back and forgot it was for
        a Genau loop would answer the next Generate out of the wrong recipes.
        """
        return {
            "image": self.panel.image_slot.current_id(),
            "video": self.panel.video_slot.current_id(),
            "intent": self.panel.selected_intent(),
            "category": self.panel.selected_category(),
        }

    def restore(self, saved) -> None:
        """Put the combine panel back the way a session left it, skipping an item
        that has since been deleted or no longer fits its slot, and an act the
        lane can no longer answer.

        The lane goes in before the act: it decides which acts are answerable,
        and ``set_category`` refuses one that is greyed out under it.

        A list of two is what sessions before this wrote — the slots alone — and
        is still read, so an existing ``ui_state.json`` restores what it has.
        """
        if isinstance(saved, (list, tuple)) and len(saved) == 2:
            saved = {"image": saved[0], "video": saved[1]}
        if not isinstance(saved, dict):
            return
        image_id, video_id = saved.get("image"), saved.get("video")
        if image_id and self._accepts_image(image_id):
            self.panel.image_slot.set_item(image_id)
        self.panel.set_intent(saved.get("intent") or recipe_match.PLAYERS)
        self.panel.set_category(saved.get("category") or "")
        if video_id and self._accepts_video(video_id):
            self.panel.video_slot.set_item(video_id)

    def drag_started(self, prompt_id: str) -> None:
        """A generation began dragging — from a browser thumbnail or a generate tab's
        preview: light the combine slot it fits, so the drop target is obvious from
        the very start of the gesture."""
        self.panel.show_drop_candidates(prompt_id)

    def drag_ended(self) -> None:
        self.panel.clear_drop_candidates()

    def rebuildable_videos(self, rows: list[dict]) -> list[dict]:
        """The completed, rebuildable i2v videos among ``rows`` — the pool an act's
        recipe is mined from (each carries the prompt it was made from, which names
        its act)."""
        return [row for row in rows
                if row.get("status") == "completed" and self._rebuildable_video_row(row)]

    def offer_the_acts(self, rows: list[dict]) -> None:
        """Gray out the acts with no video under them: an act with no recipe to
        mine should not be pickable only to answer "no recipe yet"."""
        self.panel.set_available_categories(recipe_match.available_categories(
            self.rebuildable_videos(rows), self.panel.selected_intent()))

    def _on_intent_changed(self, _intent: str) -> None:
        """Re-gray the act list for the lane just chosen."""
        self.offer_the_acts(self._db.list_generations())

    # --- the line's answer to the press, before there is a job ---------------

    def _on_generate(self, image_id: str, video_id: str) -> None:
        """The combine panel's Generate with a dropped video, with the line
        showing it at once.

        The launch itself is left for the next turn of the event loop: reading
        every stored generation to check for a duplicate, building the params and
        posting the prompt all happen on this thread, and nothing painted while
        they did — so the stand-in row would have appeared only once the work it
        was standing in for was already over.
        """
        key = self._show_launching(image_id, video_id=video_id)

        intent = self.panel.selected_intent()

        def run():
            try:
                self._generate_combination(image_id, video_id, intent=intent)
            finally:
                self._drop_launching(key)

        self._after_painting(run)

    def _on_generate_category(self, image_id: str, category: str, intent: str) -> None:
        """The combine panel's Generate with an act picked, with the line showing
        it at once. The act's own resolution is the long part — a question put to
        a local model — and :meth:`generate_category` drops the stand-in when it
        has an answer, however that turns out."""
        key = self._show_launching(image_id, category=category)
        self._after_painting(lambda: self.generate_category(
            image_id, category, intent, launching=key))

    def _after_painting(self, work) -> None:
        """Run ``work`` on the next turn of the event loop, once what has just
        been laid out has actually reached the screen.

        A seam as much as a call, like :meth:`_run_off_thread`: the suite replaces
        this with a straight-through version, so a test can press and inspect in
        one breath rather than pumping an event loop for every launch.
        """
        defer(self, work)

    def _show_launching(self, image_id: str, *, category: str = "",
                        video_id: str | None = None) -> str:
        """Put a stand-in row at the back of the line for a Generate just pressed,
        and return its key.

        It carries everything already known about the run — the frame being
        animated, the act, or the dropped video's clip in gray — so the row that
        replaces it is the same row with its price filled in, rather than a
        different-looking one appearing somewhere else. It offers no Cancel: there
        is nothing on the server to stop yet, and a button that did nothing is what
        this row exists to prevent.

        At the back because that is where it will land: nothing has been submitted,
        so every job already in the line is in front of it.
        """
        self._launch_seq += 1
        key = f"launching-{self._launch_seq}"
        image_row = self._db.get_generation(image_id) or {}
        video_row = self._db.get_generation(video_id) if video_id else None
        self._launching[key] = InFlightItem(
            key=key,
            caption="A video from Combine, still being started",
            status="queued",
            frame=None,
            reveal=lambda: None,  # no folder to open yet: it has no settings
            media_type="video",
            job_kind="I2V",  # the video slot takes nothing else
            recipe_category=category,
            # The same rule the finished row follows: a picked act names itself in
            # the text, and only a dropped video is shown.
            recipe_thumbnail=None if category else (video_row or {}).get("thumbnail_path"),
            source_image=gallery.output_file_reference(
                gallery.row_output_files(image_row)),
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
                         intent: str = recipe_match.PLAYERS, category: str = ""):
        """The ``(workflow, params, video_row, image_row)`` for re-running
        ``video_id``'s recipe on ``image_id`` — the video's workflow, settings and
        seed with only the input image swapped to the dropped one.

        Under ``GENAU`` the recipe is then re-cut to hold one cycle and smoothed
        back out (:func:`~origenerator.gallery.combine.cycle_shaped`). The lane
        used to choose only WHICH recipe was mined, and from there a Genau clip
        was made exactly like any other video; it can't be, because what Genau
        needs of a clip is a property of the clip's own length, and the past clip
        being mined was made before anyone knew that.

        ``None`` when the pair can't be combined: either row is gone, the video
        isn't a rebuildable image-conditioned recipe, or the image has no output
        file to seed from. Shared by the Generate and Open-in-generator paths.
        """
        image_row = self._db.get_generation(image_id)
        video_row = self._db.get_generation(video_id)
        if not image_row or not video_row:
            return None
        workflow_name = video_row.get("workflow_name") or ""
        workflow = WORKFLOW_REGISTRY.get(workflow_name)
        if workflow is None or not gallery.is_image_conditioned(workflow_name):
            return None  # the video must be a rebuildable, image-conditioned recipe
        params = gallery.combined_params(video_row, image_row, workflow)
        if params is None:
            return None  # the dropped image has no output file to seed from
        if intent == recipe_match.GENAU:
            params = gallery.cycle_shaped(params, workflow, category)
        return workflow, params, video_row, image_row

    def _open_combination(self, image_id: str, video_id: str, category: str = "",
                          intent: str = recipe_match.PLAYERS) -> None:
        """Open a dropped image + video's recipe as an editable generate tab instead
        of running it — the combine panel's "Edit…" path. The tab is
        prefilled with the same combination Generate would launch, ready to tweak,
        and shows the pair it was opened with rather than an empty pane."""
        built = self._combined_params(image_id, video_id, intent, category)
        if built is None:
            return
        workflow, params, video_row, image_row = built
        self._open_prepared(workflow, params, image_row, video_row, category, video_id)

    def _open_prepared(self, workflow, params, image_row, video_row,
                       category: str, video_id: str | None) -> None:
        """Hand a built combination to a generate tab: its settings on the form, its
        two halves in the preview, and the mark saying where they came from.

        The preview is the point of the pair being visible at all — nothing has
        been generated from it yet, so the pane would otherwise sit on the line a
        tab pointed at nothing wears, with both things the tab is about on hand.
        A curated act has no ``video_row`` under it, and shows the frame alone.
        """
        panel = self._info_tabs_of().open_config(workflow.name, params)
        if panel is None:
            return
        panel.set_recipe_source(category, video_id)
        panel.show_combination(
            self._still_path(image_row),
            self._host.animated_preview(video_row) if video_row is not None else None,
        )

    def _still_path(self, row: dict) -> str | None:
        """The best picture of ``row`` for a pane to show: its full-size output
        where that is a still, else the stored thumbnail (which a pane this big
        would be enlarging), else nothing."""
        preview = gallery.resolve_preview(row, COMFYUI_OUTPUT_DIR)
        if preview is not None and preview[1] == "image":
            return str(preview[0])
        return row.get("thumbnail_path")

    def _generate_combination(self, image_id: str, video_id: str, send: bool = False,
                              category: str = "",
                              intent: str = recipe_match.PLAYERS) -> None:
        """Generate a new video from a dropped image + a dropped video's recipe.

        Reuses the video's workflow, settings and seed, swapping only the input
        image to the dropped one, and lands the result in the folder for that
        (image × settings) combination. A pinned seed can reproduce an identical
        past run, so a *pressed* combine warns first via the shared "already
        generated" dialog — which, when the dropped image is itself a re-buildable
        generation, offers a fresh video seed (same frame), a fresh image seed
        (re-draw the dropped image), or both. A no-op if either row is gone, the
        video isn't a rebuildable image-conditioned recipe, the image has no
        output file, or that folder is already generating.

        The lane reaches here now: it chose which recipe ``video_id`` names, and
        it also re-cuts that recipe to the length one cycle fits in (see
        :meth:`_combined_params`), which is the one thing a mined clip cannot
        carry — it was made before anyone knew Genau needed it. ``send``
        is the one thing that still rides along — a spoken "genau it" wants its
        clip handed on the moment it exists, and wants no dialog at all: it is
        answered in the show's corner and nothing runs, so the re-roll answers
        (and the frame re-draw under them) belong to the pressed path alone.
        ``category`` names the act the dropdown was set to, when one was picked.
        The frame re-draw is the one answer it does not reach: that launches the
        frame first and the clip second, under an id this never sees, so such a
        clip's row goes without the recipe mark the queue reads.
        """
        built = self._combined_params(image_id, video_id, intent, category)
        if built is None:
            return
        workflow, params, video_row, image_row = built
        # The frame is re-buildable independently of the video seed, so the key —
        # which groups by the image's config, not its filename — is the same one
        # whether we re-roll the seed, the frame, or both. The prospective row is
        # stamped with the CURRENT workflow version (what the launched run will
        # record), not the recipe video's stored one: the settings key folds the
        # version in, and keying by an old recipe's version would park the reveal
        # on a folder the finished row never joins.
        key = self._host.folder_key_of(
            {**dict(video_row), "params_json": json.dumps(params),
             "workflow_version": workflow.version})
        if self._host.would_reproduce_a_completed_run(workflow, params):
            if send:
                # Spoken. The dialog below asks which of two seeds to re-roll,
                # and that question thrown over the fullscreen picture someone
                # is talking to is the one thing that must never appear — so the
                # spoken path gives the same answer the up-front guard gives and
                # stops. This is the case that guard can't see: the identical run
                # was made by hand, not said.
                self._say_already_genaud()
                return
            image_workflow = WORKFLOW_REGISTRY.get(image_row.get("workflow_name") or "")
            can_reroll_image = (
                image_workflow is not None
                and image_row.get("source", "generated") == "generated"
            )
            choice = self._host.ask_which_seed(
                workflow, can_reroll_image=can_reroll_image)
            if choice is None:
                return  # let the user pick a different pair rather than duplicate
            if choice in (REROLL_VIDEO, REROLL_BOTH):
                params = randomize_seeds(params, workflow.seed_keys())
            if choice in (REROLL_IMAGE, REROLL_BOTH):
                # Re-draw the dropped image (a new frame) and run the video on it,
                # carrying whatever video seed we settled on just above.
                if self._reroll.start_reroll_from_image(
                    key, image_row, image_workflow, workflow, params
                ):
                    self._host.reveal_launch(key)
                return
        prompt_id = self._reroll.start_prepared(key, workflow, params)
        if prompt_id:
            self._db.set_recipe_source(prompt_id, category=category,
                                       video_prompt_id=video_id)
            self._mark_for_sending(prompt_id, send)
            self._host.reveal_launch(key)

    def _say_already_genaud(self) -> None:
        """Say this picture has its clip already, where the speaker is looking.

        Only ever reached from a spoken command, which only runs with a show up
        — and where :meth:`_say_no_recipe` falls back to a dialog, this one has
        nothing to fall back to: a modal is precisely what it exists to avoid.
        """
        self._shows.note_voice_run(None, ALREADY_GENAUD)

    # --- finding the recipe an act names --------------------------------------

    def _category_candidates(self) -> list:
        """The recipe pool, read fresh at generate time rather than from the last
        rebuild — the gallery may have gained a video since."""
        return self.rebuildable_videos(self._db.list_generations())

    def _start_scene(self, video_row: dict, image_prompts: dict) -> str:
        """The prompt of ``video_row``'s start frame (its input image) — where the
        situation to match lives — resolved from ``image_prompts`` (prompt_id → prompt,
        built once from the in-memory image rows, so no per-video query). Falls back to
        the video's own prompt when the start frame can't be resolved (e.g. an import)."""
        source_id = gallery.find_source_image_id(video_row, self._host.image_rows())
        if source_id and (image_prompts.get(source_id) or "").strip():
            return image_prompts[source_id]
        return video_row.get("positive_prompt") or ""

    def _resolve_category(self, image_id: str, category: str, intent: str, then) -> None:
        """Find the recipe that fits ``category`` for the dropped image, then call
        ``then(video_id)`` with a rebuildable video's ``prompt_id`` — or ``None``.

        The local LLM picks the recipe whose starting scene matches this image's
        situation (:func:`recipe_match.smart_recipe`); if it's unreachable or finds no
        fit, it falls back to the act's most-used recipe
        (:func:`recipe_match.best_recipe`). ``None`` comes with a hint on screen, so a
        click never silently does nothing.

        Under ``GENAU`` both tiers see only the looping clips, so the hint names that
        narrower pool: the act may have plenty of long-form video and still nothing
        that could be made into a loop.

        The match runs off the UI thread and answers through ``then``, because asking
        the model is an HTTP round trip to something that thinks for several seconds
        — 4 to 9 of them, measured here. Inline, the window froze for exactly that
        long, worst of all on the spoken command, where the window is the picture
        being looked at. Everything the model needs is gathered first, so the pool
        thread touches neither the database nor a widget.
        """
        image_row = self._db.get_generation(image_id)
        if image_row is None:
            then(None)  # nothing to match against, and the caller stops waiting
            return
        image_prompts = {r.get("prompt_id"): r.get("positive_prompt") or ""
                         for r in self._host.image_rows()}
        candidates = [{**row, "start_scene": self._start_scene(row, image_prompts)}
                      for row in self._category_candidates()]
        scene = image_row.get("positive_prompt") or ""

        def match():
            return recipe_match.smart_recipe(
                category, scene, candidates,
                base_url=LOCAL_LLM_BASE_URL, model=LOCAL_LLM_MODEL,
                system_prompt=VIDEO_SCENE_MATCH_SYSTEM_PROMPT, intent=intent,
            ) or recipe_match.best_recipe(category, candidates, intent)

        def resolved(video_id):
            logger.info("combine: category=%s intent=%s image=%s -> recipe from %s",
                        category, intent, image_id, video_id)
            if video_id is None:
                self._say_no_recipe(category, intent)
            then(video_id)

        self._host.off_thread(match, resolved)

    def _say_no_recipe(self, category: str, intent: str) -> None:
        """Say the act has nothing to build a recipe from — in the corner of the
        fullscreen surface being spoken to when one is up, and in a dialog
        otherwise. A dialog thrown over a picture someone is looking at is the one
        place this must never appear."""
        what = ("looping “%s” clip" % category if intent == recipe_match.GENAU
                else "“%s” video" % category)
        if self._shows.showing is not None:
            self._shows.note_voice_run(
                None, f"🎤 no past {what} to base a recipe on yet")
            return
        self._host.tell(
            "No recipe yet",
            f"No past {what} to base a recipe on yet — make one first, "
            "or drop a specific video instead.",
        )

    def _curated_combination(self, image_id: str, category: str,
                             intent: str = recipe_match.PLAYERS):
        """The ``(workflow, params)`` for ``category``'s overlay-curated ``intent``
        recipe on the dropped image — the pinned setup that outranks mining (see
        :func:`recipe_match.curated_recipe`), its seeds freshly rolled.

        ``None`` sends the caller on to mining: the act has no curated entry, the
        entry names an unknown or non-image-conditioned workflow, or the image
        row is gone or has no output file to seed from.
        """
        spec = recipe_match.curated_recipe(category, intent)
        if spec is None:
            return None
        workflow = WORKFLOW_REGISTRY.get(spec.get("workflow") or "")
        if workflow is None or not gallery.is_image_conditioned(workflow.name):
            logger.warning("combine: category=%s curated workflow %r not usable",
                           category, spec.get("workflow"))
            return None
        image_row = self._db.get_generation(image_id)
        if image_row is None:
            return None
        params = gallery.curated_params(spec, image_row, workflow)
        if params is None:
            return None
        if intent == recipe_match.GENAU:
            params = gallery.cycle_shaped(params, workflow, category)
        return workflow, params

    def _generate_curated(self, image_id: str, category: str, intent: str,
                          send: bool) -> bool:
        """Launch ``category``'s curated ``intent`` recipe on the dropped image;
        ``False`` when the act has no usable curated entry, so the caller falls back
        to mining. No reproduce warning: the seeds are fresh every launch."""
        built = self._curated_combination(image_id, category, intent)
        if built is None:
            return False
        workflow, params = built
        logger.info("combine: category=%s intent=%s image=%s -> curated recipe",
                    category, intent, image_id)
        key = self._host.folder_key_for(workflow.name, params, workflow.version)
        prompt_id = self._reroll.start_prepared(key, workflow, params)
        if prompt_id:
            # The act, with no video under it: a curated recipe is pinned in the
            # overlay, so there is no past run for the queue row to show in gray.
            self._db.set_recipe_source(prompt_id, category=category)
            self._mark_for_sending(prompt_id, send)
            self._host.reveal_launch(key)
        return True

    def _mark_for_sending(self, prompt_id: str, send: bool) -> None:
        """Stamp a just-launched run to hand its clip on the moment it exists.

        Only a spoken "genau it" asks for this. Pressing Generate leaves the clip
        in the gallery for Send-to-Genau, because someone at the keyboard can look
        at it first; someone talking to a fullscreen picture cannot.
        """
        if send:
            self._db.mark_genau_requested(prompt_id)

    def generate_category(self, image_id: str, category: str,
                          intent: str = recipe_match.PLAYERS, send: bool = False,
                          launching: str | None = None) -> None:
        """Run the recipe that fits ``category`` on the dropped image: the
        overlay's curated recipe when one is pinned for the act, else the mined
        exemplar handed off to the shared combine launch. ``intent`` chooses which
        lane both tiers answer from; ``send`` hands the finished clip to Genau
        without a second ask.

        ``send`` also holds the picture until the launch is a row, because only a
        spoken "genau it" sets it and only a spoken one can be said again into
        the wait — see :meth:`_already_genaud`.

        ``launching`` is the stand-in row the press already put in the line
        (:meth:`_show_launching`), taken back off however this ends — launched,
        answered by no recipe, or unresolvable. The mined path is where it earns
        its keep: the act is answered by a local model that thinks for several
        seconds, and until it does there is nothing to queue.
        """
        if send:
            self._genau_resolving.add(image_id)
        if self._generate_curated(image_id, category, intent, send):
            self._genau_resolving.discard(image_id)
            self._drop_launching(launching)
            return
        self._resolve_category(
            image_id, category, intent,
            partial(self._combine_resolved, image_id, send, category, intent, launching),
        )

    def _combine_resolved(self, image_id: str, send: bool, category: str,
                          intent: str, launching: str | None,
                          video_id: str | None) -> None:
        """The recipe match came back: run what it found on the image, if it
        found anything. ``category`` is the act it was asked for, which the
        launched row records — the mined video answers it, but only the act says
        what the user actually chose.

        The picture and the stand-in row are both let go of either way — a launch
        is a row from here on, which is where :meth:`_already_genaud` reads it and
        where the line reads the job, and a match that found nothing leaves
        nothing to wait for.
        """
        try:
            if video_id is not None:
                self._generate_combination(image_id, video_id, send, category, intent)
        finally:
            self._genau_resolving.discard(image_id)
            self._drop_launching(launching)

    def _open_category(self, image_id: str, category: str,
                       intent: str = recipe_match.PLAYERS) -> None:
        """Open the recipe that fits ``category`` as an editable generate tab — the
        Open-in-generator counterpart to :meth:`generate_category`, honoring the
        same curated-over-mined order and the same lane.

        A run started from that tab is an ordinary Generate, so a Genau recipe opened
        this way is not auto-sent; the tab's own Send-to-Genau does it once the clip
        is there.
        """
        built = self._curated_combination(image_id, category, intent)
        if built is not None:
            workflow, params = built
            image_row = self._db.get_generation(image_id)
            if image_row is not None:
                self._open_prepared(workflow, params, image_row, None, category, None)
            return
        self._resolve_category(
            image_id, category, intent,
            lambda video_id: video_id is not None
            and self._open_combination(image_id, video_id, category, intent),
        )

    # --- the Genau lane: said out loud, and handed on ------------------------

    def send_to_genau_if_requested(self, row: dict | None) -> None:
        """Hand a just-finished clip to the Genau lane, if that is what it was for.

        The last step of a spoken "genau it": the run was stamped at launch
        (:meth:`_mark_for_sending`), so nothing here has to remember it. Only a
        video with a file on disk that hasn't already gone is sent, and a failure
        is logged rather than shown — the clip is safe in the gallery either way,
        and Send-to-Genau is still there to retry with.

        The folder it goes to is read off the lane rather than spelled again
        here, so a spoken send and a pressed one cannot differ about where a
        clip lands.
        """
        if not row or not row.get("genau_requested_at") or row.get("genau_exported_at"):
            return
        preview = gallery.resolve_preview(row, COMFYUI_OUTPUT_DIR)
        if preview is None or preview[1] != "video":
            return
        try:
            evolver_export.export_video(preview[0],
                                        EVOLVER_INBOX_DIR / GENAU_LANE.source)
        except Exception as e:
            logger.warning("Automatic send to Genau failed for %s: %s",
                           row.get("prompt_id"), e)
            return
        self._db.mark_genau_exported(row["prompt_id"])
        logger.info("genau: sent %s down the Genau lane", preview[0].name)

    def _already_genaud(self, row: dict) -> bool:
        """Whether this picture has been Genau'd — a clip made from it already,
        or one on the way.

        Saying it twice is what someone does when the first time appeared to do
        nothing, and it usually did appear to: the clip queues after whatever
        the machine is on and the picture on screen doesn't change. Answering
        that with a second identical run spends minutes of the one GPU making a
        clip that already exists, and sends both to Genau.

        A run is a row stamped as spoken for (:meth:`_mark_for_sending`) and
        matched to this picture by its start frame — counted whether it is still
        coming (pending, running) or has landed, since both mean this picture
        has its clip. Read from the database rather than the live jobs, so a run
        reconnected after a restart still counts, and one made in a session
        since closed counts forever. A row that errored counts as nothing: it
        made no clip, and asking again is the only way to get one.

        There is also a stretch with no row at all: the mined tier asks the
        local model which recipe fits and that thinks for several seconds, which
        is exactly the silence a second command is said into, so the picture is
        held in :attr:`_genau_resolving` from the moment the command is heard
        until its row exists.
        """
        if row.get("prompt_id") in self._genau_resolving:
            return True
        return any(
            other.get("genau_requested_at")
            and (gallery.is_in_progress(other) or gallery.produced_output(other))
            and gallery.find_source_image_id(other, [row]) is not None
            for other in self._db.list_generations()
        )

    def genau_it(self, image_id: str | None) -> tuple[str | None, str]:
        """Animate an image as a Genau clip: the act read off its own prompt.

        Returns the id it launched on (``None`` when it didn't) and the line the
        speaking surface should say — the same shape as ``fix_parts``, because
        the speaker is looking at the picture, not at the gallery's own caption.

        Nothing is picked and nothing is dropped: the act comes from the image's
        prompt (:func:`recipe_match.category_for_prompt`), and from there this is
        the Genau lane's ordinary category path. An unreadable prompt or an act
        with no loop recipe under it says so rather than animating the wrong
        thing. The run is stamped so its finished clip hands itself on without
        being asked again — the whole point of saying it out loud is that the
        picture is wanted moving *now*, and a second press to release it would be
        one the speaker isn't near a keyboard to make.
        """
        row = self._db.get_generation(image_id) if image_id else None
        if row is None or gallery.media_type_of_row(row) != "image":
            return None, "🎤 only a picture can become a Genau clip"
        if self._already_genaud(row):
            return None, ALREADY_GENAUD
        category = recipe_match.category_for_prompt(row.get("positive_prompt") or "")
        if category is None:
            return None, "🎤 this prompt doesn't say what's happening — no act to animate"
        available = recipe_match.available_categories(
            self.rebuildable_videos(self._db.list_generations()), recipe_match.GENAU,
        )
        if category not in available:
            return None, f"🎤 no looping “{category}” clip to base a recipe on yet"
        logger.info("genau it: image=%s -> category=%s", image_id, category)
        self.generate_category(image_id, category, recipe_match.GENAU, send=True)
        return image_id, f"🎤 animating as a “{category}” loop"
