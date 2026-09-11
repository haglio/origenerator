"""The standalone enhance: what it runs at, what it runs on, and where it shows.

The sixth of the gallery's screen concerns to come out of the view that used to
hold all of them. What lives here is an enhancement's whole life -- the settings
panel and the app-wide settings it holds, which pictures the Enhance button would
act on and why a particular one is passed over, the launch of a batch under the
folder its settings shape, and the run's appearance on every surface that shows
the picture it improves: the tile's scrim, the version list's live row, a tab's
streaming preview, and an open show's corner.

The spoken words that ask for one are here too -- "enhance" over a picture, and
"fix <part>" for the same picture with a detail pass aimed at what was named --
because both are this act with a different gate in front of them, and what they
answer with is what this side knows.

What stays with the host is what an enhancement is *of*: which pictures are
picked, which folder is on screen, and the bank button that offers the act.
:class:`EnhanceHost` names each of those.
"""
from __future__ import annotations

import json
import logging
from typing import NamedTuple, Protocol

from origenerator import gallery
from origenerator.generation_config import randomize_seeds
from origenerator.gui.enhance_panel import EnhancePanel
from origenerator.gui.inflight import EnhancingRun
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.detail_parts import name_parts

logger = logging.getLogger(__name__)

# Said the same way by the button and by the settings panel it would run, because
# both go dark together the moment what's in front of you is a video.
NO_VIDEO_ENHANCER = "Enhancement is for images — there is no video enhancer"
ALREADY_AT_THESE_SETTINGS = (
    "Already enhanced at these settings — change one below to make another"
)


class Offer(NamedTuple):
    """What the Enhance button would do right now, and what it says it would do.

    A record rather than the button itself: what the act is aimed at is this
    side's answer, and lighting a button is the bank's.
    """

    available: bool
    tip: str


class EnhanceHost(Protocol):
    """What an enhancement needs of the gallery around it, and nothing else."""

    def selected_prompt_ids(self) -> list[str]:
        """The thumbnails picked in the middle column."""

    def row_for(self, prompt_id: str) -> dict | None:
        """The generation row ``prompt_id`` names, or ``None``."""

    def image_rows(self) -> list[dict]:
        """Every image row the gallery is holding."""

    def image_config_index(self) -> dict:
        """The settings-signature index a folder key is derived against."""

    def current_group(self):
        """The folder on screen, or ``None`` on a shelf or a search."""

    def typical_run_seconds(self, job) -> float | None:
        """How long a run like this one usually takes, for the live bar."""

    def enhance_offer_changed(self) -> None:
        """Re-aim the Enhance button: what it would act on has changed."""


class EnhanceController:
    """Every standalone enhance: its settings, its launches, and its live runs."""

    def __init__(self, host: EnhanceHost, *, db, reroll, browser, shows,
                 info_tabs_of):
        self._host = host
        self._db = db
        self._reroll = reroll
        self._browser = browser
        self._shows = shows
        # The tabs are built by the window's own layout, after this: asked for
        # rather than held, so a live run reaches whichever tabs exist by then.
        self._info_tabs_of = info_tabs_of
        # What every enhance runs at, app-wide — the panel's value. Restored from
        # the session by :meth:`restore_settings`.
        self._settings = gallery.EnhanceSettings()
        # Which image each live enhance is of, by that image's prompt_id — the
        # stamp its row carries (``enhance_of``), read once per job rather than
        # on every streamed frame. ``None`` for a run from before the stamp was
        # recorded, which is matched by the file it reads instead (see
        # :meth:`_of_row`).
        self._targets: dict[str, str | None] = {}
        # Which image each running enhance is improving, and the set of runs that
        # answer was worked out from — recomputed only when that set changes, not
        # on every frame they stream.
        self._by_prompt: dict[str, object] = {}
        self._signature: tuple = ()
        self.panel = EnhancePanel(self._on_settings_changed)
        self.panel.show_settings(self._settings)

    # --- what it runs at ------------------------------------------------------

    @property
    def settings(self):
        """What the next enhance will run at — read by the tiles' own corners."""
        return self._settings

    def settings_json(self) -> str:
        """The app-wide enhancement settings, for the session to persist."""
        return self._settings.to_json()

    def restore_settings(self, raw: str | None) -> None:
        """Restore the enhancement settings a previous session left."""
        self._settings = gallery.EnhanceSettings.parse(raw)
        self.panel.show_settings(self._settings)
        self._push_settings()

    def _push_settings(self) -> None:
        """Tell every config tab what the ``+ Enhance`` card would run at.

        The panel holds the settings and the tabs hold the images, so the card
        can only know whether it would be making a duplicate once the two meet —
        here, on every edit and every rebuild."""
        for panel in self._info_tabs_of().config_panels():
            panel.set_enhance_settings(self._settings)

    def _on_settings_changed(self, settings) -> None:
        """Take an edit made in the Enhance subpanel.

        Held app-wide rather than per folder: enhancement is whatever you are
        doing at the moment, not a property of where you happen to be standing,
        so switching folders never changes what the next enhance will run at.
        Written through on each edit rather than on an Apply, so an enhance
        launched a moment later uses what is on screen."""
        self._settings = settings
        self._push_settings()
        # Whether a picked image already holds this exact version is what the
        # button is answering, so turning a setting is what brings it back.
        self._host.enhance_offer_changed()
        # Every picture on screen is answering it too, in its own corner.
        self._browser.refresh_enhance_corners()

    def sync_panel(self) -> None:
        """Gray the Enhance settings out where nothing they say could ever run.

        The panel is app-wide and follows you rather than the folder, which is
        why it shows on the shelves as readily as on a settings folder — but a
        video is the one place with no enhancement to configure at all, and live
        settings there advertise an action that isn't on offer. A mixed folder
        keeps them: the images in it are still enhanceable.
        """
        self.panel.set_applicable(not self._showing_only_videos(), NO_VIDEO_ENHANCER)

    def _showing_only_videos(self) -> bool:
        """Whether everything in front of us is video — the picked thumbnails if
        any are picked, else the folder on screen. Nothing in front (a shelf with
        no pick) is not "only videos": there is simply nothing to say."""
        rows = [row for pid in self._host.selected_prompt_ids()
                if (row := self._host.row_for(pid)) is not None]
        if not rows and not self._browser.selected_ids:
            group = self._host.current_group()
            rows = list(getattr(group, "rows", []) or [])
        return _all_video(rows)

    # --- what it would run on -------------------------------------------------

    def offer(self) -> Offer:
        """What the Enhance button would do, aimed the way Delete is: the picked
        thumbnails if any are picked, else every image in this folder still
        waiting for one.

        Picked items are enhanced whether or not they already have been (that is
        what picking them says); a whole folder is only its not-yet-enhanced
        images, so the button doesn't quietly re-run the ones that are done.
        """
        if self._browser.selected_ids:
            ids = self.enhanceable_selection()
            if ids:
                return Offer(True, f"Enhance {len(ids)} item"
                                   f"{'s' if len(ids) != 1 else ''} "
                                   "(upscale + low-denoise re-sample)")
            return Offer(False, NO_VIDEO_ENHANCER if self._selection_is_all_video()
                         else ALREADY_AT_THESE_SETTINGS)
        group = self._host.current_group()
        awaiting = (
            gallery.rows_awaiting_enhancement(group.rows, self._db.list_generations())
            if isinstance(group, gallery.SettingsGroup) else []
        )
        if not awaiting:
            return Offer(False, "Nothing here to enhance")
        return Offer(True, f"Enhance {len(awaiting)} not-yet-enhanced image"
                           f"{'s' if len(awaiting) != 1 else ''} in this folder "
                           "(upscale + low-denoise re-sample)")

    def enhanceable_selection(self) -> list[str]:
        """The picked thumbnails this button would actually run on.

        Two things are dropped. Videos, because there is no video enhancer — the
        workflow under all of this refines a still — and they are picked from
        the same flow and look no different picked, so a picked clip is nothing
        to run rather than a run that fails.

        And an image that already holds a version made at exactly the settings
        on the panel: running it again would spend a generation arriving at the
        picture that is already there. Judged against what the run would *use*
        (:func:`~origenerator.gallery.enhance.level_matching_settings`), so a
        source-matched model resolves to this image's own checkpoint before the
        comparison rather than the panel's raw value. Change any setting and the
        button comes back, which is what makes it read as "you have this one"
        rather than as "no".
        """
        ids = []
        for prompt_id in self._host.selected_prompt_ids():
            row = self._db.get_generation(prompt_id)
            if row is None or not gallery.is_enhanceable_row(row):
                continue
            if gallery.level_matching_settings(row, self._settings) is None:
                ids.append(prompt_id)
        return ids

    def _selection_is_all_video(self) -> bool:
        """Whether every picked thumbnail is a video — which is why Enhance is
        dark, as opposed to its images being enhanced at these settings already."""
        return _all_video(row for pid in self._host.selected_prompt_ids()
                          if (row := self._db.get_generation(pid)) is not None)

    def enhance_the_selection(self) -> None:
        """The bank button's action: enhance the picked thumbnails, or every
        image in this folder that isn't enhanced yet."""
        if self._browser.selected_ids:
            ids = self.enhanceable_selection()
            if ids:
                self.enhance_items(ids)
                self._host.enhance_offer_changed()
            return
        self._enhance_all()

    def _enhance_all(self) -> None:
        """The folder button's action: queue a standalone enhance for every
        image in it that isn't enhanced yet, at the current settings, then
        retire the button."""
        group = self._host.current_group()
        if not isinstance(group, gallery.SettingsGroup):
            return
        self._enqueue(
            gallery.rows_awaiting_enhancement(group.rows, self._db.list_generations())
        )
        self._host.enhance_offer_changed()

    def enhance_items(self, prompt_ids: list[str]) -> None:
        """Queue a standalone enhance for each picked generation (the thumbnail
        context menu's action) — a deliberate pick, so already-enhanced images
        are re-enhanced rather than skipped, landing as a further level beside
        the ones already there."""
        rows = [self._db.get_generation(pid) for pid in prompt_ids]
        self._enqueue([r for r in rows if r is not None])

    def _enqueue(self, rows: list[dict]) -> None:
        """Launch a standalone enhance of each of ``rows``, at the current settings.

        All of them go to the controller at once: ComfyUI runs one prompt at a
        time and the queue strip shows the line, so a batch of enhances is a
        queue the user can watch — and cancel a row out of — rather than a
        backlog held out of sight in here. (This view did hold one, because
        enhances of a single folder's images share a settings key and the
        controller took only one job per folder; it takes them all now, so the
        buffer had nothing left to do but hide the work.)
        """
        index = self._host.image_config_index()
        for row in rows:
            params = gallery.enhance_params_for(row, self._settings)
            if params is None:
                logger.warning("Enhance skipped for %s: no output file to enhance",
                               row.get("prompt_id"))
                continue
            self._launch(row, params, index)

    def _launch(self, row: dict, params: dict, index=None) -> bool:
        """Hand one standalone enhance to the controller, under the folder its
        settings shape — a batch shares ``index`` so it isn't rebuilt per row.

        Returns whether the run started. Unlaunchable (no client, or the
        submit was refused) is logged rather than dropped in silence: a
        request the user made and never saw run is the one failure they
        cannot diagnose from the screen.
        """
        workflow = WORKFLOW_REGISTRY[gallery.ENHANCE_WORKFLOW]
        key = gallery.settings_folder_key(
            {"workflow_name": workflow.name, "workflow_version": workflow.version,
             "params_json": json.dumps(params)},
            index if index is not None else self._host.image_config_index(),
        )
        prepared = randomize_seeds(params, workflow.seed_keys())
        prompt_id = self._reroll.start_prepared(key, workflow, prepared)
        if prompt_id:
            # Which image the run is of, by id: the params name only the file it
            # reads, and a file name can belong to more than one row. Stamped on
            # the row for the fold and for a restart, and remembered here for
            # the tile, the version list and the show while it runs — after the
            # launch's own reconcile, which read the row before the stamp.
            self._db.set_enhance_target(prompt_id, row.get("prompt_id"))
            self._targets[prompt_id] = row.get("prompt_id")
            self.reconcile()
            logger.info("Enhance launched for %s on %s at %s, under %s",
                        row.get("prompt_id"), params.get("input_image"),
                        gallery.describe_enhance_params(params), key)
            return True
        logger.warning("Enhance of %s dropped: could not launch under %s",
                       params.get("input_image"), key)
        return False

    def enhance_when_wanted(self, row: dict | None) -> None:
        """Enhance a just-finished image while the Auto tick is on.

        The subpanel's standing instruction, app-wide: with it ticked the app
        turns out finished images rather than raw ones, without pressing Enhance
        All after every run. The gate is Enhance All's own —
        :func:`~origenerator.gallery.enhance.rows_awaiting_enhancement` — so a
        video, an already-enhanced image (inline or folded), and an image whose
        enhance is still cooking are all passed over. That last part is what
        stops the loop: the enhance this queues folds back onto the row it came
        from and arrives here already enhanced."""
        if row is None or not self._settings.auto:
            return
        awaiting = gallery.rows_awaiting_enhancement([row], self._db.list_generations())
        if awaiting:
            self._enqueue(awaiting)

    # --- said out loud ---------------------------------------------------------

    def enhance_it(self, prompt_id: str | None) -> tuple[str | None, str]:
        """Enhance the picture on screen: the id it launched on (``None`` when it
        didn't) and the line the speaking surface should say.

        Only an image that has received no enhancement gets one, the same gate a
        fullscreen hold's Down uses — spoken over a show, this is a gesture made
        with no view of the Enhance panel, and an image already carrying an
        enhancement someone chose must not be re-derived at whatever the settings
        happen to say now. Re-enhancing stays a deliberate act made in front of
        the settings it will use (the thumbnail menu, the ``+ Enhance`` card).
        """
        row = self._db.get_generation(prompt_id) if prompt_id else None
        if row is None or not gallery.is_enhanceable_row(row):
            return None, "🎤 only a finished image can be enhanced"
        if gallery.is_enhanced_row(row):
            return None, "🎤 this one is enhanced already"
        params = gallery.enhance_params_for(row, self._settings)
        if params is None:
            return None, "🎤 this one has no file to enhance"
        return self._launch_spoken(row, params, "enhance", "enhancing…")

    def fix_parts(self, prompt_id: str | None, parts) -> tuple[str | None, str]:
        """Launch a targeted fix if the image wants one: the id it launched on
        (``None`` when it didn't) and the line the surface should say about it.

        The run is the image's latest enhancement done again with a detail pass
        aimed at each part named (:func:`~origenerator.gallery.enhance.
        fix_params_for`) — so the answer to a bad hand on an already-enhanced
        image is the same image, same settings, hand redrawn.

        Said back in the parts it is actually redrawing, which is not always the
        parts asked for: one with nothing installed to find it is dropped rather
        than taking the rest of the command down with it, and the caption is
        where that shows. Refused outright only when none of them can run."""
        asked = name_parts(parts)
        row = self._db.get_generation(prompt_id) if prompt_id else None
        if row is None or not gallery.is_enhanceable_row(row):
            return None, f"🎤 only a finished image can get a {asked} fix"
        params = gallery.fix_params_for(row, parts, self._settings)
        if params is None:
            return None, (f"🎤 no {asked} detector installed "
                          "(ComfyUI models/ultralytics/bbox)")
        if gallery.level_matching_params(row, params) is not None:
            return None, f"🎤 already has this {asked} fix"
        fixing = name_parts(
            [part for part in parts if part.name in params["enhance_detail_fixes"]])
        return self._launch_spoken(row, params, f"{fixing} fix", f"fixing {fixing}…")

    def _launch_spoken(self, row: dict, params: dict, what: str,
                       doing: str) -> tuple[str | None, str]:
        """The tail both spoken enhancements share: refuse one already cooking,
        else launch and say so.

        A targeted fix and a plain "enhance" differ in what they refuse and in
        what they run; from here on they are one act. ``what`` names the run in
        a refusal ("teeth fix", "enhance"), ``doing`` is what the surface says
        while it runs.
        """
        if self.run_of(row) is not None:
            return None, "🎤 an enhance of this image is already running"
        logger.info("Voice %s on %s at %s", what, row.get("prompt_id"),
                    gallery.describe_enhance_params(params))
        if not self._launch(row, params):
            return None, f"🎤 couldn't launch the {what} — see the log"
        return row["prompt_id"], f"🎤 {doing}"

    def enhance_from_slideshow(self, prompt_id: str) -> bool:
        """Holding a slide asked for it to be enhanced. Returns whether a run
        started — the slideshow shows its corner note only if one did.

        The same ask as a spoken "enhance" over the same picture, so the same
        decision makes it (:meth:`enhance_it`); a hold has no corner line to
        fill, so its answer is dropped. The decision is on this side rather than
        in the slideshow because it is this side that holds the levels — and a
        video has none to receive."""
        return self.enhance_it(prompt_id)[0] is not None

    # --- the runs in flight, and where each one shows -------------------------

    def _jobs(self) -> list:
        """Every standalone enhance in flight, across every folder."""
        return [job for job in self._reroll.all_jobs
                if job.workflow.name == gallery.ENHANCE_WORKFLOW]

    def _target_of(self, job) -> str | None:
        """The prompt_id of the image a live enhance ``job`` is of — the stamp
        its row carries (:meth:`Database.set_enhance_target`), read once and
        kept — or ``None`` for a run from before the stamp was recorded."""
        if job.prompt_id not in self._targets:
            row = self._db.get_generation(job.prompt_id)
            self._targets[job.prompt_id] = (row or {}).get("enhance_of")
        return self._targets[job.prompt_id]

    def _of_row(self, job, row: dict) -> bool:
        """Whether a live enhance ``job`` is an enhance of ``row`` — by the image's
        id where the run recorded one, else by the file it reads. The one
        question every surface showing a run on its image asks
        (:func:`gallery.enhance_run_targets_row`)."""
        return gallery.enhance_run_targets_row(
            self._target_of(job), job.params.get("input_image"), row)

    def _job_for(self, row: dict, running=None):
        """The standalone enhance being made of this row's image, or ``None``.

        The one walk under every surface that shows a run on the picture it
        improves. There were three of it, each with its own copy of which job
        counts and its own restatement of why a queued one has no frame; the two
        answers they gave differ only in the shape the surface wants, which is
        what :meth:`run_of` and :meth:`_pending_for` do with what this finds.

        Every live job is searched, not each folder's leading one: a batch of
        enhances goes out whole and its jobs share a settings key, so all but the
        first would read as not-cooking off the folder-facing view. ``running``
        takes a listing the caller already holds -- the reconcile reads one per
        pass -- and everything else asks for a fresh one, which is what a delete
        cancelling the runs under it needs.
        """
        for job in (self._jobs() if running is None else running):
            if self._of_row(job, row):
                return job
        return None

    def run_of(self, row: dict) -> EnhancingRun | None:
        """The standalone enhance being made of this image right now, as the
        image's tile sees it, or ``None``.

        The browser pane's tiles ask as they are built, so a folder generating
        with the Auto switch on reads honestly: the base render is out, on
        screen, and something better is on the way. Without it the folder looks
        like it is turning out plain images and ignoring the switch."""
        job = self._job_for(row)
        return self._as_run(job) if job is not None else None

    def _as_run(self, job) -> EnhancingRun:
        """One enhance in flight, as every surface showing it reads it.

        The frame is the job's own latest, which a run that hasn't started has
        none of: a batch's queued jobs show as queued rather than borrowing the
        picture of the one being rendered. "Queued" covers both waits the same
        way, whether the job is still in this app's line or already sitting on
        ComfyUI, since neither has a frame to show.
        """
        rendering = job.state == "running"
        return EnhancingRun(
            status="running" if rendering else "queued",
            frame=job.last_preview,
            progress=job.last_progress,
            pass_progress=job.last_pass_progress,
            stage=job.last_stage,
            started_at=job.started_at,
            typical_seconds=self._host.typical_run_seconds(job),
        )

    def reconcile(self) -> None:
        """Show the enhancement being made wherever the image it improves is.

        The info pane's version list leads with a live row while one is cooking,
        the tab's own preview streams the same frames, and the image's tile in
        the middle column streams them under its "Enhancing…" scrim — the same
        in-flight treatment work gets everywhere else in the app. The jobs are
        the gallery's, so the match is made here: every running standalone
        enhance against every tab's displayed row. Cheap enough to re-run on
        each frame; the panel updates its row in place.

        Every job of every folder, for the same reason :meth:`run_of` reads them
        all: a batch of enhances shares one settings key, and a tab showing the
        third image of it must find its own run rather than the first.
        """
        running = self._jobs()
        for panel in self._info_tabs_of().config_panels():
            row = panel.displayed_row()
            panel.set_pending_enhancement(
                self._pending_for(row, running) if row else None
            )
        self._reconcile_tiles(running)
        self.tell_the_shows()

    def tell_the_shows(self) -> None:
        """Tell an open show how the enhancements in flight are going.

        A show is where a batch of them gets asked for — every held slide is a
        run — so it is the surface most likely to be looking at a picture whose
        turn has not come. The show cannot tell on its own: a hold hears only
        that a run started, not where in the line it landed. Told, its corner
        says whether the version is being made or waiting to be.

        Keyed by the mapping the tiles are drawn from, which covers every image
        in the library rather than the open folder's — a show of a shelf plays
        items from anywhere. The status is read off the job rather than its row:
        the row says "running" from the moment the job is handed to ComfyUI, and
        the wait on ComfyUI's own queue is exactly the stretch this names.
        """
        self._shows.note_enhancing({
            prompt_id: "running" if job.state == "running" else "queued"
            for prompt_id, job in self._by_prompt.items()
        })

    def _reconcile_tiles(self, running) -> None:
        """Stream each running enhance onto the tile of the image it is enhancing.

        Which image a job targets is worked out only when the set of running
        enhances changes, not on every streamed frame: the match walks every
        image row, and the frames arrive several times a second. The set is
        told by the runs themselves and what each is of, so a run cancelled and
        launched again on the same image is read afresh rather than off the
        job that is gone.
        """
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
        self._browser.show_enhancing({
            prompt_id: self._as_run(job)
            for prompt_id, job in self._by_prompt.items()
        })

    def _pending_for(self, row: dict, running) -> tuple | None:
        """``(status, frame, settings)`` of a standalone enhance running on
        ``row``'s own image, or ``None`` — the version list's live row.

        The settings ride along so the live row can name what is being made the
        way a finished level names what made it: the panel may have moved on
        since the run was launched, so the job's own params are the only honest
        answer. Everything else about which job it is, and why a queued one shows
        no frame, is :meth:`_job_for`'s and :meth:`_as_run`'s.
        """
        job = self._job_for(row, running)
        if job is None:
            return None
        run = self._as_run(job)
        return run.status, run.frame, gallery.describe_enhance_params(job.params)

    def forget(self, prompt_id: str) -> None:
        """A run that is over is nobody's enhance any more."""
        self._targets.pop(prompt_id, None)

    # --- stopping one ----------------------------------------------------------

    def jobs_targeting(self, rows) -> list:
        """Every standalone enhance in flight whose image is one of ``rows``.

        :meth:`run_of`'s question asked the other way round — over a set of
        images rather than one — for the two callers that act on a whole
        selection: the tile menu's Cancel, and the delete about to take those
        images out from under their runs.
        """
        running = self._jobs()
        return [job for job in running
                if any(self._job_for(row, [job]) is not None for row in rows if row)]

    def cancel_for_delete(self, rows) -> None:
        """Stop every standalone enhance still being made of ``rows`` — the items
        a delete is about to take.

        Wired into :class:`GalleryActions` beside the media release, so it runs
        for every delete there is: a picked tile, a whole folder, a rejected
        experiment, a slideshow's Up key.

        Canceling frees the queue — a video-length wait can sit after an
        enhance nobody wants any more — and takes the run's transient row with
        it, so no enhanced file lands with no original to be a version of.
        """
        for job in self.jobs_targeting(rows):
            logger.info("Canceling the enhance of %s: its image is being deleted",
                        job.params.get("input_image"))
            self._reroll.cancel_job(job.prompt_id)

    def cancel_for(self, rows) -> None:
        """Throw away the enhancements being made of ``rows``, keeping the images.

        The tile menu's Cancel. Everything the delete path's cancel does, minus
        the delete: the runs stop, their transient rows go with them, and the
        images they were being made of are left exactly as they were — the
        picture on screen is the one that was already there.

        Not a re-roll's cancel, which is why it doesn't go through the gallery's
        own: an auto-generating folder takes that as a discarded seed and
        launches the next one, and nobody asking to stop an enhancement is
        asking for a fresh variation. The redraw afterwards is what takes the
        scrim off the tile and the pending row out of the info pane.
        """
        jobs = self.jobs_targeting(rows)
        for job in jobs:
            logger.info("Canceling the enhance of %s: asked to, from its tile",
                        job.params.get("input_image"))
            self._reroll.cancel_job(job.prompt_id)
        if jobs:
            self.reconcile()


def _all_video(rows) -> bool:
    """Whether ``rows`` is a non-empty set of videos — the one case with nothing
    to enhance at all, as opposed to nothing picked."""
    rows = list(rows)
    return bool(rows) and all(gallery.media_type_of_row(row) == "video" for row in rows)
