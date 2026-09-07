"""The queue's cards, built with no widget anywhere.

Which is what the move buys: this is a join over four sources — the generations
table, the requests table, the controller's live jobs with its held set and
queue order, the auto-generate loop, the folder tree — and it used to be the
largest function inside a 1,400-line rendering class, reachable only by building
one.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import json

import pytest

from origenerator.gui.inflight_items import InFlightItems


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

    def list_generations(self):
        return list(self._rows)

    def list_requests(self):
        return list(self._requests)

    def recent_durations(self, workflow_name):
        return [30.0, 32.0, 34.0] if workflow_name == "sdxl_t2i" else []


class FakeJob:
    def __init__(self, prompt_id, *, state="running", started_at=None):
        self.prompt_id = prompt_id
        self.state = state
        self.started_at = started_at
        self.last_preview = b"frame" if state == "running" else None
        self.last_progress = (5, 20) if state == "running" else None
        self.last_pass_progress = None
        self.last_stage = "Render" if state == "running" else ""
        self.foreign_ahead = None
        self.params = {}


class FakeReroll:
    def __init__(self, jobs_by_folder=None, held=(), order=()):
        self.jobs_by_folder = jobs_by_folder or {}
        self.queue_order = list(order)
        self._held = list(held)

    def held_jobs(self):
        return list(self._held)


class FakeAuto:
    def __init__(self, looping=()):
        self._looping = set(looping)

    def is_active(self, key):
        return key in self._looping

    def stop(self, key):
        self._looping.discard(key)


class FakeTree:
    def __init__(self, groups=None):
        self.groups = groups or {}

    def group_for_key(self, key):
        return self.groups.get(key)


@pytest.fixture
def build():
    def make(rows=(), *, requests=(), jobs_by_folder=None, held=(), order=(),
             looping=(), image_rows=(), groups=None, cancelled=None, revealed=None):
        model = InFlightItems(
            db=FakeDb(rows, requests),
            reroll=FakeReroll(jobs_by_folder, held, order),
            auto=FakeAuto(looping),
            tree=FakeTree(groups),
            image_rows=lambda: list(image_rows),
            on_cancel=(cancelled if cancelled is not None else lambda _p: None),
            on_reveal=(revealed if revealed is not None else lambda _k: None),
        )
        return model.build()
    return make


def test_only_the_rows_still_being_made_get_a_card(build):
    items = build([_row("g1", status="completed"), _row("g2", status="pending"),
                   _row("g3", status="running"), _row("g4", status="error")])

    assert {item.key for item in items} == {"g2", "g3"}


def test_a_running_row_no_live_job_holds_still_gets_a_plain_card(build):
    # After a restart that has not re-adopted its runs, the database is the only
    # thing that knows the work exists -- a card with no frame, no progress and
    # nothing to cancel is still the honest answer.
    items = build([_row("g1", status="running")])

    card, = items
    assert (card.frame, card.progress, card.cancel) == (None, None, None)
    assert card.status == "running"


def test_a_tracked_run_grafts_its_live_reading_onto_the_row(build):
    job = FakeJob("g1")
    items = build([_row("g1", status="running")],
                  jobs_by_folder={"image/sdxl_t2i/aaa": [job]})

    card, = items
    assert (card.frame, card.progress, card.stage) == (b"frame", (5, 20), "Render")
    assert card.cancel is not None


def test_a_run_whose_lines_are_being_spoken_says_so_rather_than_running(build):
    # A story's lines are read aloud before the job is sent, so the row already
    # says running while the wait is something else entirely.
    job = FakeJob("g1", state="speaking")
    items = build([_row("g1", status="running")],
                  jobs_by_folder={"image/sdxl_t2i/aaa": [job]})

    assert items[0].status == "speaking"


def test_the_queues_own_line_orders_the_cards(build):
    # Nothing a row records says whether an image jumped ahead of a video, or
    # whether a drag moved one.
    rows = [_row("g1"), _row("g2"), _row("g3")]
    items = build(rows, order=["g3", "g1", "g2"])

    assert [item.key for item in items] == ["g3", "g1", "g2"]


def test_a_row_the_line_holds_no_job_for_sorts_to_the_back(build):
    items = build([_row("g1"), _row("unadopted")], order=["g1"])

    assert [item.key for item in items] == ["g1", "unadopted"]


def test_a_held_run_says_the_line_is_not_waiting_on_the_gpu_for_it(build):
    job = FakeJob("g1", state="queued")
    items = build([_row("g1")], jobs_by_folder={"image/sdxl_t2i/aaa": [job]},
                  held=[job])

    assert items[0].held


def test_a_looping_folders_run_offers_next_seed_rather_than_stop(build):
    key = "image/sdxl_t2i/aaa"
    items = build([_row("g1", status="running")],
                  jobs_by_folder={key: [FakeJob("g1")]}, looping=[key])

    assert items[0].auto_generating
    assert items[0].stop_auto is not None


def test_a_cards_cancel_and_reveal_are_the_callers_own(build):
    cancelled, revealed = [], []
    key = "image/sdxl_t2i/aaa"
    items = build([_row("g1", status="running")],
                  jobs_by_folder={key: [FakeJob("g1")]},
                  cancelled=cancelled.append, revealed=revealed.append)

    items[0].cancel()
    items[0].reveal()
    assert (cancelled, revealed) == (["g1"], [key])


def test_a_run_asked_for_of_a_picture_stands_under_that_picture(build):
    # A folder-wide request queues a run per image and every one of them animates
    # nothing, so the thing it was asked about is the only picture it has.
    rows = [_row("asked-of"), _row("g1")]
    items = build(rows, requests=[{"prompt_id": "g1", "source_prompt_id": "asked-of"}])

    card = next(item for item in items if item.key == "g1")
    assert card.requested
    assert card.source_picture == "asked-of.jpg"


def test_a_queued_run_with_no_picture_shows_what_its_folder_already_holds(build):
    # Its output does not exist yet, but the folder it will join is full of what
    # the same settings made last time.
    key = "image/sdxl_t2i/aaa"
    items = build([_row("g1")], jobs_by_folder={key: [FakeJob("g1", state="queued")]})

    # A folder with nothing in it yet -- the first run of a new recipe -- has no
    # node in the tree at all, and draws no block rather than an empty grid.
    assert items[0].folder_thumbnails == ()


def test_a_workflows_recent_runs_are_what_the_countdown_reads(build):
    items = build([_row("g1", status="running")])

    assert items[0].typical_seconds == pytest.approx(32.0)
