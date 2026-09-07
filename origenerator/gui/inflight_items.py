"""The queue's view-model: every generation in flight, as a card.

Not rendering, and it had grown into the pane's largest function by nearly three
to one -- it joins the generations table, the requests table, the controller's
live jobs and its held set and queue order, the auto-generate loop, the folder
tree and a thumbnail index, and builds a twenty-field record per running row.
The pane held it only because that is where the first consumer lived; three
surfaces read these items now.

Everything it reaches for is handed in, so the whole join can be exercised with
plain dictionaries and no widget -- which is what the pane's own suite could not
do while this sat inside it.
"""
from __future__ import annotations

from collections.abc import Callable

from origenerator import gallery, timing
from origenerator.gui.inflight import InFlightItem
from origenerator.gui.orientation import row_orientation
from origenerator.gui.queue_thumbs import FOLDER_CELLS
from origenerator.workflows.derived_size import resolve_input_image_path

# The kinds whose start frame is what the run is *of*, rather than one input
# among several: a video animating a picture, and an enhancement of one.
SOURCE_FRAME_KINDS = ("I2V", "Enhance")


class InFlightItems:
    """The queue's cards, built from the tables and the controller under them.

    ``on_cancel`` and ``on_reveal`` are what a card's buttons do -- the pane
    passes its own signals -- so nothing here needs to be a widget.
    """

    def __init__(self, *, db, reroll, auto, tree, image_rows: Callable[[], list],
                 on_cancel: Callable[[str], None], on_reveal: Callable[[str], None]):
        self._db = db
        self._reroll = reroll
        self._auto = auto
        self._tree = tree
        self._image_rows = image_rows
        self._on_cancel = on_cancel
        self._on_reveal = on_reveal

    def build(self, rows=None, requests=None) -> list[InFlightItem]:
        """Every queued/running generation as a card model, in the order the queue
        will work through them.

        The database's running/pending rows are the source of truth for what's in
        flight — every generation is a gallery re-roll (a tab's Generate launches
        one too) — so a card shows even when no live job object is tracking a row
        (after a restart that hasn't re-adopted it, say). A re-roll tracked this
        session grafts on its live frame, progress, cancel and start time from its
        :class:`GenerationJob`; an untracked running row shows a plain card.

        The queue's own line orders them (:attr:`RerollController.queue_order`):
        nothing a row records says whether an image jumped ahead of a video, or
        whether a drag moved one. A row the line holds no job for — one a restart
        hasn't re-adopted — sorts to the back rather than jumping the queue on
        screen.

        The strip's rows carry more than the shelf's cards do — a price, a kind, a
        picture of what the job is made from or of the folder it will land in —
        and all of it is read off the row and the tree already in hand, so a poll
        costs one listing whatever the queue is showing. ``rows``/``requests``
        take a listing the caller already read (the poll reads its own on the
        pool); left off, both tables are read here.
        """
        reroll_by_pid = {job.prompt_id: (key, job)
                         for key, jobs in self._reroll.jobs_by_folder.items()
                         for job in jobs}
        # The jobs the queue is holding back rather than waiting on the GPU for,
        # so a row can say why the line isn't moving.
        held = {job.prompt_id for job in self._reroll.held_jobs()}
        # Which of these were asked for, and of what. One listing rather than a
        # lookup per job: the table is small and the queue rarely is.
        requested = {r["prompt_id"]: r["source_prompt_id"]
                     for r in (self._db.list_requests()
                               if requests is None else requests)}
        image_index = None  # built lazily, only to place an untracked row's folder
        typical: dict[str, float | None] = {}  # workflow -> its usual run time
        stablemates: dict[str, tuple] = {}  # folder key -> thumbnails already in it
        if rows is None:
            rows = self._db.list_generations()
        # Every row's thumbnail, so a combine's run can show the video its
        # settings came from. Off the listing already in hand rather than a query
        # per job: the recipe video is an ordinary finished row somewhere in it.
        thumb_by_id = {r.get("prompt_id"): r.get("thumbnail_path") for r in rows}
        items = []
        for row in rows:
            if row.get("status") not in ("running", "pending"):
                continue
            pid = row["prompt_id"]
            tracked = reroll_by_pid.get(pid)
            if tracked is not None:
                folder_key, job = tracked
                frame, progress = job.last_preview, job.last_progress
                pass_progress = job.last_pass_progress  # the band along the bar's foot
                stage = job.last_stage                   # and what it is doing
                foreign = job.foreign_ahead  # another app's jobs in front of it, if any
                started = job.started_at  # None until ComfyUI actually starts it
                cancel = lambda p=pid: self._on_cancel(p)
                stop_auto = lambda k=folder_key: self._auto.stop(k)
                # A story's lines are spoken before the job is sent: the row
                # already says running, and the card says what the wait is.
                speaking = job.state == "speaking"
            else:  # a running row no live job holds — no live frame, progress, or cancel
                if image_index is None:
                    image_index = gallery.build_image_config_index(self._image_rows())
                folder_key = gallery.settings_folder_key(row, image_index)
                frame, progress, cancel, foreign, started = None, None, None, None, None
                pass_progress, stage, stop_auto, speaking = None, "", None, False
            workflow_name = row.get("workflow_name") or ""
            params = gallery.parse_params(row.get("params_json"))
            kind = gallery.job_kind_label(workflow_name)
            items.append(InFlightItem(
                key=pid,
                caption=gallery.config_tab_title(workflow_name, params),
                status=("speaking" if speaking
                        else "running" if row.get("status") == "running" else "queued"),
                frame=frame,
                reveal=lambda k=folder_key: self._on_reveal(k),
                media_type=gallery.media_type_of_row(row),  # image/video corner badge
                orientation=row_orientation(row),  # the side its picture will land on
                progress=progress,
                pass_progress=pass_progress,
                stage=stage,
                cancel=cancel,
                # Its folder auto-looping makes that button "Next seed": the press
                # discards this run and the loop launches another. A menu can
                # offer the real stop beside it, which is what stop_auto is for.
                auto_generating=self._auto.is_active(folder_key),
                stop_auto=stop_auto,
                foreign_ahead=foreign,
                held=pid in held,
                started_at=started,
                typical_seconds=self._typical_seconds(workflow_name, typical),
                job_kind=kind,
                requested=pid in requested,
                # Only where the start frame is what the run is *of*: a video
                # animating a picture, and an enhancement of one. An image
                # workflow that happens to take an input (the pose transfer's
                # structure image) is still an image being made, and its row is
                # placed the way every other image's is — by the folder it joins.
                source_image=(params.get("input_image")
                              if kind in SOURCE_FRAME_KINDS else None),
                # What to stand under the wait: the image this run was
                # requested of, else the frame it animates or enhances.
                source_picture=self._source_picture(
                    requested.get(pid), thumb_by_id, params, kind),
                # What the Combine panel was asked for, when this run came from
                # it: the act off its dropdown, else the video whose settings the
                # run follows — shown gray beside the frame, being the recipe
                # rather than the result. Never both. An act names what the video
                # will do, which is the whole of what was chosen; the clip its
                # recipe was mined out of is an answer to a question the user
                # never asked, and a picture of a video they did not pick reads
                # as a job that is that video. A dropped video *is* the choice,
                # so there the picture is the only thing saying which.
                recipe_category=row.get("recipe_category") or "",
                recipe_thumbnail=(None if row.get("recipe_category")
                                  else thumb_by_id.get(row.get("recipe_video_id"))),
                folder_thumbnails=self._folder_thumbnails(folder_key, stablemates),
            ))
        place = {pid: i for i, pid in enumerate(self._reroll.queue_order)}
        items.sort(key=lambda it: (place.get(it.key, len(place)),
                                   it.status != "running"))
        return items

    @staticmethod
    def _source_picture(requested_of, thumb_by_id: dict, params: dict,
                        kind: str) -> str | None:
        """A file showing what a queued run came from, or ``None``.

        The image a request was made of comes first: a folder-wide request
        queues a run per image and every one of them animates nothing, so the
        thing it was asked about is the only picture it has. Failing that, the
        start frame an i2v or an enhance is built on.
        """
        asked_of = thumb_by_id.get(requested_of) if requested_of else None
        if asked_of:
            return asked_of
        if kind not in SOURCE_FRAME_KINDS:
            return None
        frame = resolve_input_image_path(params.get("input_image"))
        return str(frame) if frame is not None else None

    def _folder_thumbnails(self, folder_key: str, cache: dict) -> tuple:
        """A few thumbnails already in the folder a queued job is headed for.

        What a queued job with no picture of its own can be recognized by: its
        output doesn't exist yet, but the folder it will join is full of what the
        same settings made last time. Newest first, since ``list_generations``
        hands them back that way and the newest are what the user was just looking
        at.

        Read off the folder tree the gallery already built rather than by keying
        every row again — the tree is rebuilt when the rows change, and this runs
        on every poll. A folder with nothing in it yet (the first run of a new
        recipe, or an enhancement, whose product folds into the row it enhanced
        rather than landing anywhere) has no node in the tree at all and answers
        with nothing, which the row draws as no block rather than an empty grid.
        ``cache`` memoizes for the length of one pass, since an auto-generate loop
        fills the line with jobs from a single folder.
        """
        if folder_key not in cache:
            group = self._tree.group_for_key(folder_key)
            rows = gallery.rows_under(group) if group is not None else []
            # Only what is finished and has a picture — the job asking, and
            # every other row still in the line, is exactly what has none.
            cache[folder_key] = tuple(
                row["thumbnail_path"] for row in rows if row.get("thumbnail_path")
            )[:FOLDER_CELLS]
        return cache[folder_key]

    def _typical_seconds(self, workflow_name: str, cache: dict):
        """What a whole run of ``workflow_name`` usually takes, for the running
        bar's countdown — memoized into ``cache`` for the length of one pass,
        since this list is rebuilt on every poll."""
        if workflow_name not in cache:
            cache[workflow_name] = timing.estimate_seconds(
                self._db.recent_durations(workflow_name)
            )
        return cache[workflow_name]
