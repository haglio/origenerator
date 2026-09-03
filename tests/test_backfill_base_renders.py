"""Re-deriving the base render for images the inline enhance tail finished.

Those rows kept one file and no "before". The base is recoverable because it is
reproducible: the same seed and recipe with the tail off reproduces the pixels
that pass made, and attaching it gives the row the ``Original`` / ``Enhance 1``
pair it should have had. The work rides the absence the background experimenter
uses, since it is a full render per row and there are a great many of them.
"""

import json

from origenerator import base_backfill, gallery
from origenerator.app_state import AppState
from origenerator.base_backfill import (
    SOURCE, TARGET_KEY, UNTIMED_SECONDS, attach_base, base_params_for,
    cancel_base_renders, fold_base_render, fold_completed_base_renders,
    queue_base_renders, render_base_now, rows_missing_their_base, typical_seconds,
)
from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gui.generation_job import GenerationJob
from origenerator.gui.main_window import OrigeneratorWindow
from origenerator.workflows import WORKFLOW_REGISTRY
from tools import backfill_base_renders as backfill_tool

_SDXL = WORKFLOW_REGISTRY["sdxl_t2i"]


def _add(db, prompt_id, *, params, files, original_files=None, workflow="sdxl_t2i",
         source="generated", status="completed"):
    db.insert_generation(
        prompt_id=prompt_id, workflow_name=workflow, workflow_version="v004",
        positive_prompt=params.get("positive_prompt", ""), seed=params.get("seed"),
        params_json=json.dumps(params), workflow_json="{}", source=source,
    )
    fields = {"status": status}
    if files is not None:
        fields["output_files"] = json.dumps(files)
    if original_files is not None:
        fields["original_files"] = json.dumps(original_files)
    db.update_generation(prompt_id, **fields)
    return db.get_generation(prompt_id)


def _file(name):
    return {"filename": name, "subfolder": "image", "type": "output"}


def _baked(db, prompt_id="baked", seed=1, filename=None):
    return _add(db, prompt_id,
                params=dict(_SDXL.default_params(), enhance=True, seed=seed),
                files=[_file(filename or f"sdxl_t2i_{prompt_id}.png")])


# --- which rows need one ---------------------------------------------------


def test_it_picks_exactly_the_rows_that_lost_their_base(tmp_path):
    db = Database(tmp_path / "t.db")
    _baked(db, "baked")
    _add(db, "plain", params=dict(_SDXL.default_params(), enhance=False, seed=2),
         files=[_file("sdxl_t2i_b.png")])
    _add(db, "layered", params=dict(_SDXL.default_params(), enhance=False, seed=3),
         files=[_file("image_enhance_1.png"), _file("sdxl_t2i_c.png")],
         original_files=[_file("sdxl_t2i_c.png")])

    assert [r["prompt_id"] for r in rows_missing_their_base(db.list_generations())] \
        == ["baked"]


def test_an_unrebuildable_import_is_left_alone(tmp_path):
    # No registered template, so there is no recipe to re-run — and guessing one
    # would produce a "base" that is not this image's base at all.
    db = Database(tmp_path / "t.db")
    _add(db, "import", params={"enhance": True}, files=[_file("mystery.png")],
         workflow="unknown")
    assert rows_missing_their_base(db.list_generations()) == []


def test_a_re_render_in_flight_is_not_itself_something_to_repair(tmp_path):
    db = Database(tmp_path / "t.db")
    _baked(db, "baked")
    _add(db, "repair", params=dict(_SDXL.default_params(), enhance=False,
                                   **{TARGET_KEY: "baked"}),
         files=None, source=SOURCE, status="running")
    assert [r["prompt_id"] for r in rows_missing_their_base(db.list_generations())] \
        == ["baked"]


# --- what one runs at ------------------------------------------------------


def test_the_rerun_is_the_recorded_recipe_with_the_tail_off(tmp_path):
    db = Database(tmp_path / "t.db")
    row = _add(db, "baked",
               params=dict(_SDXL.default_params(), enhance=True, seed=4242,
                           steps=37, cfg=6.5, positive_prompt="a lantern"),
               files=[_file("sdxl_t2i_a.png")])

    params = base_params_for(row, _SDXL)

    assert params["enhance"] is False   # the one thing that changes
    # Everything the pixels depend on is reproduced exactly, the seed above all.
    assert params["seed"] == 4242
    assert params["steps"] == 37
    assert params["cfg"] == 6.5
    assert params["positive_prompt"] == "a lantern"
    assert params[TARGET_KEY] == "baked"   # and it knows what it repairs


def test_the_target_key_cannot_split_a_folder(tmp_path):
    # It rides in the params, so it has to be invisible to the grouping: the
    # gallery only ever asks a workflow for the keys it declares.
    db = Database(tmp_path / "t.db")
    row = _baked(db, "baked")
    before = gallery.settings_folder_key(row)
    repaired = dict(row, params_json=json.dumps(base_params_for(row, _SDXL)))
    assert gallery.settings_folder_key(repaired) == before


# --- the absence batch -----------------------------------------------------


def test_an_absence_queues_a_batch_and_stops_at_the_limit(tmp_path):
    db = Database(tmp_path / "t.db")
    for i in range(5):
        _baked(db, f"baked{i}", seed=i)
    launched = []

    queued = queue_base_renders(
        db.list_generations(),
        lambda wf, params: launched.append(params[TARGET_KEY]) or "p",
        limit=3,
    )

    assert queued == 3 and len(launched) == 3


def test_a_refused_launch_is_not_counted(tmp_path):
    db = Database(tmp_path / "t.db")
    _baked(db, "baked")
    assert queue_base_renders(db.list_generations(), lambda wf, p: None) == 0


def test_a_row_already_being_repaired_is_not_queued_again(tmp_path):
    # Two short absences in a row must not put the same repair in twice.
    db = Database(tmp_path / "t.db")
    _baked(db, "baked")
    _add(db, "repair", params={TARGET_KEY: "baked"}, files=None,
         source=SOURCE, status="running")

    assert queue_base_renders(db.list_generations(), lambda wf, p: "p") == 0


# --- folding what the absence finished -------------------------------------


def test_attaching_the_base_gives_the_row_its_two_levels(tmp_path):
    db = Database(tmp_path / "t.db")
    _baked(db, "baked", filename="sdxl_t2i_a.png")

    assert attach_base(db, "baked", [_file("sdxl_t2i_a_base.png")]) is True

    upgraded = db.get_generation("baked")
    # The enhanced file keeps its place at the head — it is still what the row
    # shows — and the base joins behind it as the original.
    assert [f["filename"] for f in gallery.row_output_files(upgraded)] == \
        ["sdxl_t2i_a.png", "sdxl_t2i_a_base.png"]
    assert [lvl.label for lvl in gallery.enhance_levels(upgraded)] == \
        ["Enhance 1", "Original"]
    assert gallery.original_files_of(upgraded)[0]["filename"] == "sdxl_t2i_a_base.png"


def test_a_repaired_row_is_not_offered_again(tmp_path):
    # Interrupting is safe: each row is attached as it lands, and the next
    # absence picks up only what is left.
    db = Database(tmp_path / "t.db")
    _baked(db, "baked", filename="sdxl_t2i_a.png")
    attach_base(db, "baked", [_file("sdxl_t2i_a_base.png")])
    assert rows_missing_their_base(db.list_generations()) == []


def test_folding_drops_the_repair_row_it_came_from(tmp_path):
    db = Database(tmp_path / "t.db")
    _baked(db, "baked", filename="sdxl_t2i_a.png")
    repair = _add(db, "repair", params={TARGET_KEY: "baked"},
                  files=[_file("sdxl_t2i_a_base.png")], source=SOURCE)

    assert fold_base_render(db, repair) == "baked"

    assert db.get_generation("repair") is None   # a repair leaves no trace
    assert gallery.original_files_of(db.get_generation("baked"))


def test_a_repair_whose_target_is_gone_is_left_alone(tmp_path):
    # Deleted while the absence ran: leave the row rather than half-migrate it,
    # so it can be found and cleared by hand.
    db = Database(tmp_path / "t.db")
    repair = _add(db, "repair", params={TARGET_KEY: "vanished"},
                  files=[_file("orphan_base.png")], source=SOURCE)
    assert fold_base_render(db, repair) is None
    assert db.get_generation("repair") is not None


def test_the_startup_sweep_folds_the_finished_and_leaves_the_running(tmp_path):
    db = Database(tmp_path / "t.db")
    _baked(db, "one", filename="sdxl_t2i_one.png")
    _baked(db, "two", filename="sdxl_t2i_two.png")
    _add(db, "done", params={TARGET_KEY: "one"},
         files=[_file("sdxl_t2i_one_base.png")], source=SOURCE)
    _add(db, "running", params={TARGET_KEY: "two"}, files=None,
         source=SOURCE, status="running")

    assert fold_completed_base_renders(db) == 1

    assert db.get_generation("done") is None
    assert db.get_generation("running")["status"] == "running"
    assert gallery.original_files_of(db.get_generation("one"))
    assert not gallery.original_files_of(db.get_generation("two"))


# --- and clearing the rest when the app opens ------------------------------


class _FakeClient:
    def __init__(self, running=()):
        self._running = set(running)
        self.cancelled, self.interrupts = [], 0

    def fetch_running(self):
        return self._running

    def cancel_prompt(self, prompt_id):
        self.cancelled.append(prompt_id)

    def interrupt(self):
        self.interrupts += 1


def test_opening_the_app_drops_what_the_absence_had_not_reached(tmp_path):
    db = Database(tmp_path / "t.db")
    _baked(db, "one")
    _add(db, "queued", params={TARGET_KEY: "one"}, files=None,
         source=SOURCE, status="pending")
    _add(db, "done", params={TARGET_KEY: "one"},
         files=[_file("sdxl_t2i_one_base.png")], source=SOURCE)
    client = _FakeClient()

    assert cancel_base_renders(db, client) == 1

    assert client.cancelled == ["queued"]
    assert db.get_generation("queued") is None
    assert db.get_generation("done") is not None  # a finished repair still folds


def test_one_caught_mid_render_is_interrupted_too(tmp_path):
    # Dequeuing alone would leave it holding the GPU the user just came back for.
    db = Database(tmp_path / "t.db")
    _baked(db, "one")
    _add(db, "running", params={TARGET_KEY: "one"}, files=None,
         source=SOURCE, status="running")
    client = _FakeClient(running={"running"})

    assert cancel_base_renders(db, client) == 1
    assert client.interrupts == 1


def test_a_repair_never_grows_a_folder_of_its_own(tmp_path):
    # It is a repair of an existing image, not an image: a half-finished one
    # must never show as a duplicate tile beside what it repairs.
    db = Database(tmp_path / "t.db")
    _baked(db, "one")
    _add(db, "running", params=dict(_SDXL.default_params(), enhance=False,
                                    **{TARGET_KEY: "one"}),
         files=None, source=SOURCE, status="running")
    _add(db, "landed", params=dict(_SDXL.default_params(), enhance=False,
                                   **{TARGET_KEY: "one"}),
         files=[_file("sdxl_t2i_one_base.png")], source=SOURCE)

    tree = gallery.build_gallery_tree(db.list_generations())
    shown = [r["prompt_id"] for media in tree for r in gallery.rows_under(media)]
    assert shown == ["one"]


# --- how much of the backlog one absence takes ------------------------------

def _timed(db, prompt_id, *, seconds, workflow="sdxl_t2i"):
    """A finished generation the library has a duration for — what the batch
    prices its repairs from."""
    row = _add(db, prompt_id, params={"seed": 1}, files=[_file(f"{prompt_id}.png")],
               workflow=workflow)
    db.update_generation(prompt_id, duration_seconds=seconds)
    return row


def test_the_batch_is_priced_from_what_the_renders_actually_take(tmp_path):
    # Sized in GPU minutes, not rows: the first version handed out six per
    # absence believing one repair was a night's work, which would have drained
    # a 147-row backlog of eight-second images over twenty-five evenings.
    db = Database(tmp_path / "t.db")
    for i in range(40):
        _baked(db, f"baked{i}", seed=i)
    _timed(db, "timed", seconds=60)  # a minute a render, as this library records it
    launched = []

    queued = queue_base_renders(
        db.list_generations(), lambda wf, p: launched.append(p[TARGET_KEY]) or "p",
        budget_minutes=5,
    )

    assert queued == 5 and len(launched) == 5


def test_an_untimed_workflow_is_priced_high_rather_than_guessed_low(tmp_path):
    # Nothing timed here at all: queue few. Too large a batch is thrown away by
    # the next launch; too small a one only costs another absence.
    db = Database(tmp_path / "t.db")
    for i in range(40):
        _baked(db, f"baked{i}", seed=i)

    queued = queue_base_renders(db.list_generations(), lambda wf, p: "p",
                                budget_minutes=5)

    assert queued == 5 * 60 / UNTIMED_SECONDS


def test_one_repair_always_goes_however_slow(tmp_path):
    # A budget under the cost of a single render still moves the backlog by one,
    # or a library of slow renders would never repair anything at all.
    db = Database(tmp_path / "t.db")
    _baked(db, "baked")
    _timed(db, "timed", seconds=600)

    assert queue_base_renders(db.list_generations(), lambda wf, p: "p",
                              budget_minutes=1) == 1


def test_typical_seconds_is_the_median_of_what_was_recorded(tmp_path):
    db = Database(tmp_path / "t.db")
    for i, seconds in enumerate((5, 6, 7, 8, 400)):  # one cold-start outlier
        _timed(db, f"t{i}", seconds=seconds)

    rows = db.list_generations()
    assert typical_seconds(rows, "sdxl_t2i") == 7
    assert typical_seconds(rows, "wan22_i2v") == UNTIMED_SECONDS


# --- the batch a real close actually hands over -----------------------------

def test_the_close_batch_reaches_the_queue(qtbot, tmp_path, monkeypatch):
    # The batch runs only from a closing window, where an exception is shown to
    # nobody — so the wiring between the view and the queue is checked here
    # rather than left to the one place it can fail in silence. It failed
    # exactly that way: the launch adapter named ``gallery.BASE_RENDER_SOURCE``,
    # which the package never exported, so every close raised before the session
    # was saved. Three days of closes queued no repair at all and lost the open
    # tabs, the gallery folder and the window's place, with nothing in the log.
    #
    # Everything but the socket is the real path: the submit is stubbed,
    # because a job the server refuses is dropped from the line, which would
    # leave this passing or failing on whether a ComfyUI happened to be up.
    monkeypatch.setattr(GenerationJob, "start", lambda self: None)
    db = Database(tmp_path / "t.db")
    for i in range(3):
        _baked(db, f"baked{i}", seed=i)
    window = OrigeneratorWindow(ComfyUIClient(), db, AppState(tmp_path / "ui.json"))
    qtbot.addWidget(window)

    assert window._gallery_view.queue_base_renders_for_absence() == 3

    repairs = [r for r in db.list_generations() if r.get("source") == SOURCE]
    assert {gallery.parse_params(r["params_json"])[TARGET_KEY] for r in repairs} == \
        {"baked0", "baked1", "baked2"}


def test_a_broken_close_chore_still_leaves_the_session_saved(qtbot, tmp_path,
                                                             monkeypatch):
    # What a close is actually for is the session — the open tabs, the folder,
    # the window's place on its monitor. An errand for the coming absence that
    # raises must cost its own batch and nothing else.
    def boom():
        raise AttributeError("module 'origenerator.gallery' has no attribute 'X'")

    db = Database(tmp_path / "t.db")
    state_path = tmp_path / "ui.json"
    window = OrigeneratorWindow(ComfyUIClient(), db, AppState(state_path))
    qtbot.addWidget(window)
    monkeypatch.setattr(window._gallery_view, "queue_base_renders_for_absence", boom)
    window._gallery_view.select_generation("xyz")

    window.close()

    assert json.loads(state_path.read_text())["gallery_selection"] == "xyz"


# --- the tool: the same repair, run to completion in one sitting -------------

class _PollingClient:
    """A ComfyUI that takes a payload and hands back history after ``after`` polls."""

    def __init__(self, *, after=1, history=None, submit_error=None):
        self.submitted = []
        self._after = after
        self._history = {} if history is None else history
        self._submit_error = submit_error
        self.polls = 0

    def submit_job(self, payload, prompt_id):
        if self._submit_error is not None:
            raise self._submit_error
        self.submitted.append((payload, prompt_id))

    def fetch_history(self, prompt_id):
        self.polls += 1
        return self._history if self.polls >= self._after else {}


def _base_params():
    return dict(_SDXL.default_params(), seed=7)


def _clock():
    """A monotonic clock a sleep can wind forward, so a wait costs no real time."""
    now = [0.0]

    def monotonic():
        return now[0]

    def sleep(seconds):
        now[0] += seconds

    return monotonic, sleep


def test_a_repair_run_now_submits_the_base_recipe_and_returns_its_files(tmp_path,
                                                                        monkeypatch):
    monkeypatch.setattr(
        base_backfill, "extract_completion",
        lambda *a, **k: ([_file("base.png")], None, 4.0))
    client = _PollingClient(history={"anything": True})
    monotonic, sleep = _clock()

    files = render_base_now(client, _SDXL, _base_params(), now=monotonic, sleep=sleep)

    assert files == [_file("base.png")]
    assert len(client.submitted) == 1


def test_a_repair_run_now_waits_for_history_rather_than_reading_an_empty_one(
        tmp_path, monkeypatch):
    # ComfyUI answers /history with nothing at all until the prompt finishes, so
    # an empty answer is "not yet", never "produced nothing".
    monkeypatch.setattr(
        base_backfill, "extract_completion",
        lambda *a, **k: ([_file("base.png")], None, 4.0))
    client = _PollingClient(after=3, history={"anything": True})
    monotonic, sleep = _clock()

    files = render_base_now(client, _SDXL, _base_params(), now=monotonic, sleep=sleep)

    assert files == [_file("base.png")] and client.polls == 3


def test_a_repair_that_never_finishes_gives_up_rather_than_waiting_forever():
    # One still, however slow the model. A render that has not landed by then is
    # a ComfyUI that is wedged or working on something else entirely.
    client = _PollingClient(after=10**9)
    monotonic, sleep = _clock()

    files = render_base_now(client, _SDXL, _base_params(), now=monotonic, sleep=sleep)

    assert files == []
    assert monotonic() >= base_backfill.RENDER_TIMEOUT_SECONDS


def _repairable_db(tmp_path):
    """A database holding one enhanced image whose base render was thrown away."""
    db = Database(tmp_path / "repair.db")
    _add(db, "gone", params=dict(_SDXL.default_params(), seed=3, enhance=True),
         files=[_file("enhanced.png")])
    return db


def test_the_tool_reports_what_it_would_do_and_touches_nothing(tmp_path, capsys):
    db = _repairable_db(tmp_path)

    assert backfill_tool.main(["--db", str(tmp_path / "repair.db")]) == 0

    said = capsys.readouterr().out
    assert "1 enhanced image(s) with no base render kept" in said
    assert "sdxl_t2i: 1" in said and "--apply" in said
    assert not gallery.original_files_of(db.get_generation("gone"))


def test_the_tool_folds_each_repair_into_the_row_it_belongs_to(tmp_path, monkeypatch):
    db = _repairable_db(tmp_path)
    monkeypatch.setattr(backfill_tool, "ComfyUIClient", lambda: object())
    monkeypatch.setattr(backfill_tool, "render_base_now",
                        lambda client, workflow, params: [_file("base.png")])

    code = backfill_tool.main(["--apply", "--db", str(tmp_path / "repair.db")])

    assert code == 0
    originals = gallery.original_files_of(db.get_generation("gone"))
    assert [f["filename"] for f in originals] == ["base.png"]


def test_the_tool_reports_a_repair_that_produced_nothing_rather_than_folding_it(
        tmp_path, monkeypatch, capsys):
    # A wedged ComfyUI must not leave the row looking repaired, and the exit
    # code has to say so: this is run unattended over a long backlog.
    db = _repairable_db(tmp_path)
    monkeypatch.setattr(backfill_tool, "ComfyUIClient", lambda: object())
    monkeypatch.setattr(backfill_tool, "render_base_now",
                        lambda client, workflow, params: [])

    code = backfill_tool.main(["--apply", "--db", str(tmp_path / "repair.db")])

    assert code == 1
    assert "produced nothing" in capsys.readouterr().out
    assert not gallery.original_files_of(db.get_generation("gone"))


def test_the_tool_stops_at_the_limit_it_is_given(tmp_path, capsys):
    db = _repairable_db(tmp_path)
    _add(db, "gone2", params=dict(_SDXL.default_params(), seed=4, enhance=True),
         files=[_file("enhanced2.png")])

    backfill_tool.main(["--db", str(tmp_path / "repair.db"), "--limit", "1"])

    assert "1 enhanced image(s)" in capsys.readouterr().out
