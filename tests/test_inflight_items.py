from __future__ import annotations

import json

import pytest

from origenerator import gallery
from origenerator.gallery import JobKind
from origenerator.gui.generation_job import JobState
from origenerator.gui.inflight import RunReading
from origenerator.gui.inflight_items import (
    TRAINING_KEY,
    InFlightCallbacks,
    InFlightItems,
    InFlightSources,
    requested_of,
)
from origenerator.workflows import WORKFLOW_REGISTRY


def _row(prompt_id, *, status="pending", workflow="sdxl_t2i", params=None, **extra):
    return {
        "prompt_id": prompt_id,
        "workflow_name": workflow,
        "workflow_version": "v004",
        "status": status,
        "media_type": "image",
        "params_json": json.dumps(params or {"positive_prompt": "a tabby", "seed": 1}),
        "thumbnail_path": f"{prompt_id}.jpg",
        **extra,
    }


class FakeDb:
    def __init__(self, rows=(), requests=()):
        self._rows = list(rows)
        self._requests = list(requests)
        self.asked = []

    def list_generations(self):
        self.asked.append("list_generations")
        return list(self._rows)

    def list_requests(self):
        self.asked.append("list_requests")
        return list(self._requests)

    def recent_durations(self, workflow_name):
        self.asked.append("recent_durations")
        return [30.0, 32.0, 34.0] if workflow_name == "sdxl_t2i" else []


class FakeJob:
    def __init__(self, prompt_id, *, state="running", started_at=None, starts_at=None):
        self.prompt_id = prompt_id
        self.state = state
        self.started_at = started_at
        self.last_preview = b"frame" if state == "running" else None
        self.last_progress = (5, 20) if state == "running" else None
        self.last_pass_progress = None
        self.last_stage = "Render" if state == "running" else ""
        self.foreign_ahead = None
        self.params = {}
        self.shielded = False
        self.queue_says_it_starts_at = starts_at


class FakeJobQueue:
    def __init__(self, jobs_by_folder=None, order=(), training=None, stuck=()):
        self.jobs_by_folder = jobs_by_folder or {}
        self.queue_order = list(order)
        self.training = training
        self.stuck = set(stuck)
        self.moved = []

    def can_move_up(self, prompt_id):
        return (prompt_id, "up") not in self.stuck

    def can_move_down(self, prompt_id):
        return (prompt_id, "down") not in self.stuck

    def move_up(self, prompt_id):
        self.moved.append((prompt_id, "up"))

    def move_down(self, prompt_id):
        self.moved.append((prompt_id, "down"))

    def starts_at(self, prompt_id):
        return next((job.queue_says_it_starts_at for jobs in self.jobs_by_folder.values()
                     for job in jobs if job.prompt_id == prompt_id), None)


class FakeTraining:
    caption = "Hands fix 1.0 LoRA"

    def __init__(self):
        self.canceled = self.revealed = 0
        self.read = RunReading(status=JobState.RUNNING, progress=(30, 2000), stage="Training")

    def reading(self):
        return self.read

    def cancel(self):
        self.canceled += 1

    def reveal(self):
        self.revealed += 1


class FakeAuto:
    def __init__(self, populating=()):
        self._populating = set(populating)

    def is_active(self, key):
        return key in self._populating

    def stop(self, key):
        self._populating.discard(key)


class FakeTree:
    def __init__(self, groups=None):
        self.groups = groups or {}
        self.asked = []

    def group_for_key(self, key):
        self.asked.append(key)
        return self.groups.get(key)


@pytest.fixture
def build():
    def make(rows=(), *, sources=None, image_rows=(), image_index=None, callbacks=None):
        model = InFlightItems(
            sources or _sources(rows),
            image_rows=lambda: list(image_rows),
            image_index=lambda: (gallery.build_image_config_index(list(image_rows))
                                 if image_index is None else image_index),
            callbacks=callbacks or _callbacks(),
        )
        return model.build()
    return make


def _sources(rows=(), requests=(), jobs=None, populating=(), groups=None):
    return InFlightSources(
        db=FakeDb(rows, requests), jobs=jobs or FakeJobQueue(),
        populate=FakeAuto(populating), tree=FakeTree(groups))


def _callbacks(cancelled=None, revealed=None, went_to=None, shielded=None):
    return InFlightCallbacks(
        cancel=(cancelled if cancelled is not None else lambda _p: None),
        reveal=(revealed if revealed is not None else lambda _k: None),
        go_to_item=(went_to if went_to is not None else lambda _p: None),
        shield=(shielded if shielded is not None else lambda _p, _on: None))


def test_only_the_rows_still_being_made_get_a_tile(build):
    items = build([_row("g1", status="completed"), _row("g2", status="pending"),
                   _row("g3", status="running"), _row("g4", status="error")])

    assert {item.key for item in items} == {"g2", "g3"}


def test_a_running_row_no_live_job_holds_is_placed_by_the_gallery_s_own_index(
        build, monkeypatch):
    monkeypatch.setattr(gallery, "build_image_config_index",
                        lambda rows: pytest.fail(
                            "the index was built again: at every look at the queue, that cost a "
                            "double-click a fifth of a second"))

    items = build([_row("g1", status="running")], image_index={})

    assert [item.key for item in items] == ["g1"]


def test_a_running_row_no_live_job_holds_still_gets_a_plain_tile(build):
    items = build([_row("g1", status="running")])

    tile, = items
    assert (tile.reading.frame, tile.reading.progress, tile.cancel, tile.shield,
            tile.stop_populate) == (None, None, None, None, None)
    assert tile.reading.status == "running"


def test_a_tracked_run_grafts_its_live_reading_onto_the_row(build):
    job = FakeJob("g1")
    items = build(sources=_sources([_row("g1", status="running")], jobs=FakeJobQueue(jobs_by_folder={"image/sdxl_t2i/aaa": [job]})))

    tile, = items
    assert (tile.reading.frame, tile.reading.progress, tile.reading.stage) == (b"frame", (5, 20), "Render")
    assert tile.cancel is not None


def test_a_video_waiting_out_the_minute_after_an_image_carries_when_it_starts(build):
    job = FakeJob("g1", state="queued", starts_at=1060.0)
    items = build(sources=_sources([_row("g1", status="pending")], jobs=FakeJobQueue(jobs_by_folder={"video/wan22_i2v/aaa": [job]})))

    tile, = items
    assert tile.starts_at == 1060.0


def test_a_run_whose_lines_are_being_spoken_says_so_rather_than_running(build):
    job = FakeJob("g1", state="speaking")
    items = build(sources=_sources([_row("g1", status="running")], jobs=FakeJobQueue(jobs_by_folder={"image/sdxl_t2i/aaa": [job]})))

    assert items[0].reading.status == "speaking"


def test_a_run_comfyui_holds_but_has_not_started_says_queued(build):
    job = FakeJob("g1", state="queued")
    items = build(sources=_sources([_row("g1", status="running")], jobs=FakeJobQueue(jobs_by_folder={"video/wan22_i2v/aaa": [job]})))

    assert items[0].reading.status == "queued", (
        "a row says running from the moment its run is sent, though ComfyUI may still hold it in line")


def test_a_tile_moves_its_job_up_and_down_the_queues_own_line(build):
    jobs = FakeJobQueue({"image/sdxl_t2i/aaa": [FakeJob("g1"), FakeJob("g2", state="queued")]},
                        order=["g1", "g2"], stuck={("g1", "up"), ("g2", "down")})
    head, behind = build(sources=_sources([_row("g1", status="running"), _row("g2")], jobs=jobs))

    behind.move_up()
    head.move_down()

    assert jobs.moved == [("g2", "up"), ("g1", "down")]
    assert (head.move_up, behind.move_down) == (None, None)


def test_a_run_no_live_job_holds_cannot_be_moved(build):
    item, = build([_row("g1", status="running")])

    assert (item.move_up, item.move_down) == (None, None)


def test_the_queues_own_line_orders_the_tiles(build):
    rows = [_row("g1"), _row("g2"), _row("g3")]
    items = build(sources=_sources(rows, jobs=FakeJobQueue(order=["g3", "g1", "g2"])))

    assert [item.key for item in items] == ["g3", "g1", "g2"], (
        "no row records a job moved up or dragged, so only the queue's own line knows the order")


def test_a_row_the_line_holds_no_job_for_sorts_to_the_back(build):
    items = build(sources=_sources([_row("g1"), _row("unadopted")], jobs=FakeJobQueue(order=["g1"])))

    assert [item.key for item in items] == ["g1", "unadopted"], (
        "a row a restart has not taken back would otherwise jump the queue on screen")


def test_a_training_holding_the_line_waits_after_what_comfyui_holds_and_before_the_rest(build):
    training = FakeTraining()

    items = build(sources=_sources([_row("g1", status="running"), _row("g2", status="pending")], jobs=FakeJobQueue(order=["g1", "g2"], training=training)))

    assert [item.key for item in items] == ["g1", TRAINING_KEY, "g2"]
    item = items[1]
    assert (item.job_kind, item.move_up, item.move_down, item.reading) == (
        JobKind.TRAINING, None, None, training.read)
    assert "Hands" in item.caption
    item.cancel()
    item.reveal()
    assert (training.canceled, training.revealed) == (1, 1)


def test_a_trainings_row_offers_no_shield_since_nothing_is_sent_while_it_runs(build):
    items = build(sources=_sources([], jobs=FakeJobQueue(training=FakeTraining())))

    assert (items[0].shield, items[0].shielded) == (None, False)


def test_an_populating_folders_run_offers_next_seed_rather_than_stop(build):
    key = "image/sdxl_t2i/aaa"
    items = build(sources=_sources([_row("g1", status="running")], populating=[key], jobs=FakeJobQueue(jobs_by_folder={key: [FakeJob("g1")]})))

    assert items[0].populating
    assert items[0].stop_populate is not None


def test_a_tiles_cancel_and_reveal_are_the_callers_own(build):
    cancelled, revealed = [], []
    key = "image/sdxl_t2i/aaa"
    items = build(sources=_sources([_row("g1", status="running")], jobs=FakeJobQueue(jobs_by_folder={key: [FakeJob("g1")]})), callbacks=_callbacks(cancelled=cancelled.append, revealed=revealed.append))

    items[0].cancel()
    items[0].reveal()
    assert (cancelled, revealed) == (["g1"], [key])


def test_an_enhancements_tile_goes_nowhere_once_its_image_is_gone(build):
    went_to, revealed = [], []
    enhancement = _row("e1", workflow="image_enhance", enhance_of="deleted",
                       params={"input_image": "sdxl_t2i_deleted.png [output]"})
    items = build([enhancement], callbacks=_callbacks(went_to=went_to.append, revealed=revealed.append))

    items[0].reveal()

    assert (went_to, revealed) == ([], [])


def test_a_tiles_shield_is_its_jobs_and_is_set_through_the_caller(build):
    shielded = []
    job = FakeJob("g1")
    job.shielded = True
    items = build(sources=_sources([_row("g1", status="running")], jobs=FakeJobQueue(jobs_by_folder={"image/sdxl_t2i/aaa": [job]})), callbacks=_callbacks(shielded=lambda prompt_id, on: shielded.append((prompt_id, on))))

    assert items[0].shielded
    items[0].shield(False)
    assert shielded == [("g1", False)]


def test_a_run_a_folders_modify_batch_queued_stands_under_the_image_it_rewrites(build):
    rows = [_row("asked-of"), _row("g1")]
    items = build(sources=_sources(rows, requests=[{"prompt_id": "g1", "source_prompt_id": "asked-of",
                                   "heard": ""}]))

    tile = next(item for item in items if item.key == "g1")
    assert tile.batch_modified
    assert not tile.requested
    assert tile.source_file == "asked-of.jpg"


def test_a_run_a_typed_request_queued_is_marked_as_one(build):
    rows = [_row("asked-of"), _row("g1")]
    items = build(sources=_sources(rows, requests=[{"prompt_id": "g1", "source_prompt_id": "asked-of",
                                   "heard": "", "asked": "two women"}]))

    tile = next(item for item in items if item.key == "g1")
    assert tile.requested
    assert not tile.batch_modified


def test_a_run_a_request_queued_is_marked_as_one(build):
    rows = [_row("asked-of"), _row("g1")]
    items = build(sources=_sources(rows, requests=[{"prompt_id": "g1", "source_prompt_id": "asked-of",
                                   "heard": "Request, no hat, over."}]))

    tile = next(item for item in items if item.key == "g1")
    assert tile.requested
    assert not tile.batch_modified


def test_the_row_standing_in_for_a_request_is_the_row_its_run_will_get(build):
    asked_of = _row("asked-of", status="completed")
    items = build(sources=_sources([asked_of, _row("g1")], requests=[{
        "prompt_id": "g1", "source_prompt_id": "asked-of", "heard": "Request, no hat, over."}]))
    tile = next(item for item in items if item.key == "g1")

    standing = requested_of(asked_of, WORKFLOW_REGISTRY["sdxl_t2i"], {})

    drawn = ("media_type", "job_kind", "requested", "source_image", "source_file")
    assert {name: standing[name] for name in drawn} == {
        name: getattr(tile, name) for name in drawn}


def test_a_run_made_from_a_dropped_video_shows_that_videos_thumbnail(build):
    source = _row("src", status="completed", thumbnail_path="src.jpg")
    items = build([source, _row("g1", source_video="src")])

    tile = next(item for item in items if item.key == "g1")
    assert tile.source_video_thumbnail == "src.jpg"
    assert tile.action == ""


def test_a_run_made_from_a_chosen_action_shows_no_source_video(build):
    source = _row("src", status="completed", thumbnail_path="src.jpg")
    items = build([source, _row("g1", source_video="src", action="dancing")])

    tile = next(item for item in items if item.key == "g1")
    assert tile.action == "dancing"
    assert tile.source_video_thumbnail is None


def test_a_queued_run_whose_folder_holds_nothing_yet_shows_no_thumbnails(build):
    key = "image/sdxl_t2i/aaa"
    items = build(sources=_sources([_row("g1")], jobs=FakeJobQueue(jobs_by_folder={key: [FakeJob("g1", state="queued")]})))

    assert items[0].folder_thumbnails == (), (
        "no block, rather than an empty grid")


def test_a_workflows_recent_runs_are_what_the_countdown_reads(build):
    items = build([_row("g1", status="running")])

    assert items[0].reading.typical_seconds == pytest.approx(32.0)


def _three_runs_of_one_folder():
    key = "image/sdxl_t2i/aaa"
    pids = ("g1", "g2", "g3")
    return _sources([_row(pid, status="running") for pid in pids],
                    jobs=FakeJobQueue(jobs_by_folder={key: [FakeJob(pid) for pid in pids]}))


def test_a_pass_lists_each_table_once_however_many_runs_the_queue_shows(build):
    sources = _three_runs_of_one_folder()

    build(sources=sources)

    assert sorted(name for name in sources.db.asked if name.startswith("list_")) == [
        "list_generations", "list_requests"], (
        "the tiles are rebuilt at every poll and a table is small where the queue rarely is, so "
        "a pass costs one listing of each table rather than a lookup per run")


def test_a_pass_reads_a_workflows_usual_time_once_for_all_its_runs(build):
    sources = _three_runs_of_one_folder()

    build(sources=sources)

    assert sources.db.asked.count("recent_durations") == 1, (
        "the line often holds many runs of one workflow, so its usual time is worked out once "
        "a pass")


def test_a_pass_gathers_a_folders_thumbnails_once_for_all_its_runs(build):
    sources = _three_runs_of_one_folder()

    build(sources=sources)

    assert sources.tree.asked == list(sources.jobs.jobs_by_folder), (
        "Auto-generate fills the line with runs of one folder, so its thumbnails are gathered "
        "once a pass")
