from __future__ import annotations

import json

from origenerator import base_backfill, downtime, gallery
from origenerator.app_state import AppState
from origenerator.base_backfill import (
    TARGET_KEY,
    UNTIMED_SECONDS,
    attach_base,
    base_params_for,
    cancel_base_renders,
    fold_base_render,
    fold_completed_base_renders,
    queue_base_renders,
    render_base_now,
    rows_missing_their_base,
    typical_seconds,
)
from origenerator.branch_session import ENV_FLAG
from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database, NewGeneration
from origenerator.generation_state import GenerationSource
from origenerator.gui.core import Core
from origenerator.gui.gallery_view import GalleryView
from origenerator.gui.generation_job import GenerationJob
from origenerator.gui.job_queue import JobQueue
from origenerator.workflows import WORKFLOW_REGISTRY
from tests.comfyui_folders import SUITE_FOLDERS
from tools import backfill_base_renders as backfill_tool

_SDXL = WORKFLOW_REGISTRY["sdxl_t2i"]


def _add(db, prompt_id, *, params, files, **row):
    db.insert_generation(NewGeneration(
        prompt_id=prompt_id, workflow_name=row.get("workflow", "sdxl_t2i"),
        workflow_version="v004",
        positive_prompt=params.get("positive_prompt", ""), seed=params.get("seed"),
        params_json=json.dumps(params), workflow_json="{}",
        source=row.get("source", "generated"),
    ))
    fields = {"status": row.get("status", "completed")}
    if files is not None:
        fields["output_files"] = json.dumps(files)
    if row.get("original_files") is not None:
        fields["original_files"] = json.dumps(row["original_files"])
    db.update_generation(prompt_id, **fields)
    return db.get_generation(prompt_id)


def _file(name):
    return {"filename": name, "subfolder": "image", "type": "output"}


def _baked(db, prompt_id="baked", seed=1, filename=None):
    return _add(db, prompt_id,
                params=dict(_SDXL.default_params(), enhance=True, seed=seed),
                files=[_file(filename or f"sdxl_t2i_{prompt_id}.png")])



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
    db = Database(tmp_path / "t.db")
    _add(db, "import", params={"enhance": True}, files=[_file("mystery.png")],
         workflow="unknown")
    assert rows_missing_their_base(db.list_generations()) == [], (
        "an import has no settings to re-run, and guessed ones would render a base "
        "that is not this image's")


def test_a_re_render_in_flight_is_not_itself_something_to_repair(tmp_path):
    db = Database(tmp_path / "t.db")
    _baked(db, "baked")
    _add(db, "repair", params=dict(_SDXL.default_params(), enhance=False,
                                   **{TARGET_KEY: "baked"}),
         files=None, source=GenerationSource.BASE_RENDER, status="running")
    assert [r["prompt_id"] for r in rows_missing_their_base(db.list_generations())] \
        == ["baked"]



def test_the_rerun_is_the_recorded_settings_with_the_tail_off(tmp_path):
    db = Database(tmp_path / "t.db")
    row = _add(db, "baked",
               params=dict(_SDXL.default_params(), enhance=True, seed=4242,
                           steps=37, cfg=6.5, positive_prompt="a lantern"),
               files=[_file("sdxl_t2i_a.png")])

    params = base_params_for(row, _SDXL)

    assert params["enhance"] is False
    assert params["seed"] == 4242, (
        "the same seed and settings with the enhance tail off give back the very pixels "
        "the base pass made, which is what makes the re-run a repair")
    assert params["steps"] == 37
    assert params["cfg"] == 6.5
    assert params["positive_prompt"] == "a lantern"
    assert params[TARGET_KEY] == "baked"


def test_the_target_key_cannot_split_a_folder(tmp_path):
    db = Database(tmp_path / "t.db")
    row = _baked(db, "baked")
    before = gallery.settings_folder_key(row)
    repaired = dict(row, params_json=json.dumps(base_params_for(row, _SDXL)))
    assert gallery.settings_folder_key(repaired) == before



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

    assert queued == 3
    assert len(launched) == 3


def test_a_refused_launch_is_not_counted(tmp_path):
    db = Database(tmp_path / "t.db")
    _baked(db, "baked")
    assert queue_base_renders(db.list_generations(), lambda wf, p: None) == 0


def test_a_row_already_being_repaired_is_not_queued_again(tmp_path):
    db = Database(tmp_path / "t.db")
    _baked(db, "baked")
    _add(db, "repair", params={TARGET_KEY: "baked"}, files=None,
         source=GenerationSource.BASE_RENDER, status="running")

    assert queue_base_renders(db.list_generations(), lambda wf, p: "p") == 0



def test_attaching_the_base_gives_the_row_its_two_levels(tmp_path):
    db = Database(tmp_path / "t.db")
    _baked(db, "baked", filename="sdxl_t2i_a.png")

    assert attach_base(db, "baked", [_file("sdxl_t2i_a_base.png")]) is True

    upgraded = db.get_generation("baked")
    assert [f["filename"] for f in gallery.row_output_files(upgraded)] == \
        ["sdxl_t2i_a.png", "sdxl_t2i_a_base.png"]
    assert [lvl.label for lvl in gallery.enhancement_versions(upgraded)] == \
        ["Enhancement 1/1", "Original"]
    assert gallery.original_files_of(upgraded)[0]["filename"] == "sdxl_t2i_a_base.png"


def test_a_repaired_row_is_not_offered_again(tmp_path):
    db = Database(tmp_path / "t.db")
    _baked(db, "baked", filename="sdxl_t2i_a.png")
    attach_base(db, "baked", [_file("sdxl_t2i_a_base.png")])
    assert rows_missing_their_base(db.list_generations()) == []


def test_folding_drops_the_repair_row_it_came_from(tmp_path):
    db = Database(tmp_path / "t.db")
    _baked(db, "baked", filename="sdxl_t2i_a.png")
    repair = _add(db, "repair", params={TARGET_KEY: "baked"},
                  files=[_file("sdxl_t2i_a_base.png")], source=GenerationSource.BASE_RENDER)

    assert fold_base_render(db, repair) == "baked"

    assert db.get_generation("repair") is None
    assert gallery.original_files_of(db.get_generation("baked"))


def test_the_target_key_reaches_no_node(tmp_path):
    params = base_params_for(_baked(Database(tmp_path / "t.db"), "baked"), _SDXL)
    without = {key: value for key, value in params.items() if key != TARGET_KEY}
    assert _SDXL.build_api_payload(params) == _SDXL.build_api_payload(without)


def test_a_finished_repair_is_folded_before_the_gallery_first_draws(qtbot, tmp_path, monkeypatch):
    db = Database(tmp_path / "t.db")
    _baked(db, "baked")
    _add(db, "repair", params={TARGET_KEY: "baked"},
         files=[_file("sdxl_t2i_baked_base.png")], source=GenerationSource.BASE_RENDER)
    waiting_at_each_draw = []
    draw = GalleryView.refresh

    def noting(view, **how):
        waiting_at_each_draw.append(db.get_generation("repair") is not None)
        draw(view, **how)

    monkeypatch.setattr(GalleryView, "refresh", noting)

    window = Core(ComfyUIClient(folders=SUITE_FOLDERS), db, AppState(tmp_path / "ui.json"))
    qtbot.addWidget(window)
    window._gallery_view.refresh()

    assert waiting_at_each_draw[0] is False, (
        "a repaired image is drawn with both its versions from the first")


def test_the_tool_waits_for_a_repair_with_the_loop_the_app_keeps():
    assert backfill_tool.render_base_now is base_backfill.render_base_now, (
        "a loop of the tool's own is the one piece nothing here would catch going out of step")


def test_a_repair_whose_target_is_gone_is_left_alone(tmp_path):
    db = Database(tmp_path / "t.db")
    repair = _add(db, "repair", params={TARGET_KEY: "vanished"},
                  files=[_file("orphan_base.png")], source=GenerationSource.BASE_RENDER)
    assert fold_base_render(db, repair) is None
    assert db.get_generation("repair") is not None, (
        "left whole, it can be found and cleared by hand")


def test_the_startup_sweep_folds_the_finished_and_leaves_the_running(tmp_path):
    db = Database(tmp_path / "t.db")
    _baked(db, "one", filename="sdxl_t2i_one.png")
    _baked(db, "two", filename="sdxl_t2i_two.png")
    _add(db, "done", params={TARGET_KEY: "one"},
         files=[_file("sdxl_t2i_one_base.png")], source=GenerationSource.BASE_RENDER)
    _add(db, "running", params={TARGET_KEY: "two"}, files=None,
         source=GenerationSource.BASE_RENDER, status="running")

    assert fold_completed_base_renders(db) == 1

    assert db.get_generation("done") is None
    assert db.get_generation("running")["status"] == "running"
    assert gallery.original_files_of(db.get_generation("one"))
    assert not gallery.original_files_of(db.get_generation("two"))



class _FakeClient:
    def __init__(self):
        self.cancelled, self.interrupted = [], []

    def cancel_prompt(self, prompt_id):
        self.cancelled.append(prompt_id)

    def interrupt(self, prompt_id=None):
        self.interrupted.append(prompt_id)


def test_opening_the_app_drops_what_the_absence_had_not_reached(tmp_path):
    db = Database(tmp_path / "t.db")
    _baked(db, "one")
    _add(db, "queued", params={TARGET_KEY: "one"}, files=None,
         source=GenerationSource.BASE_RENDER, status="pending")
    _add(db, "done", params={TARGET_KEY: "one"},
         files=[_file("sdxl_t2i_one_base.png")], source=GenerationSource.BASE_RENDER)
    client = _FakeClient()

    assert cancel_base_renders(db, client) == 1

    assert client.cancelled == ["queued"], (
        "the app is open now, so the graphics card is for the user's own work")
    assert db.get_generation("queued") is None
    assert db.get_generation("done") is not None


def test_one_caught_mid_render_is_stopped_by_name_too(tmp_path):
    db = Database(tmp_path / "t.db")
    _baked(db, "one")
    _add(db, "running", params={TARGET_KEY: "one"}, files=None,
         source=GenerationSource.BASE_RENDER, status="running")
    client = _FakeClient()

    assert cancel_base_renders(db, client) == 1
    assert client.interrupted == ["running"]


def test_a_repair_never_grows_a_folder_of_its_own(tmp_path):
    db = Database(tmp_path / "t.db")
    _baked(db, "one")
    _add(db, "running", params=dict(_SDXL.default_params(), enhance=False,
                                    **{TARGET_KEY: "one"}),
         files=None, source=GenerationSource.BASE_RENDER, status="running")
    _add(db, "landed", params=dict(_SDXL.default_params(), enhance=False,
                                   **{TARGET_KEY: "one"}),
         files=[_file("sdxl_t2i_one_base.png")], source=GenerationSource.BASE_RENDER)

    tree = gallery.build_gallery_tree(db.list_generations())
    shown = [r["prompt_id"] for media in tree for r in gallery.rows_under(media)]
    assert shown == ["one"]


def _timed(db, prompt_id, *, seconds, workflow="sdxl_t2i"):
    row = _add(db, prompt_id, params={"seed": 1}, files=[_file(f"{prompt_id}.png")],
               workflow=workflow)
    db.update_generation(prompt_id, duration_seconds=seconds)
    return row


def test_the_batch_is_priced_from_what_the_renders_actually_take(tmp_path):
    db = Database(tmp_path / "t.db")
    for i in range(40):
        _baked(db, f"baked{i}", seed=i)
    _timed(db, "timed", seconds=60)
    launched = []

    queued = queue_base_renders(
        db.list_generations(), lambda wf, p: launched.append(p[TARGET_KEY]) or "p",
        budget_minutes=5,
    )

    assert queued == 5
    assert len(launched) == 5


def test_an_untimed_workflow_is_priced_high_rather_than_guessed_low(tmp_path):
    db = Database(tmp_path / "t.db")
    for i in range(40):
        _baked(db, f"baked{i}", seed=i)

    queued = queue_base_renders(db.list_generations(), lambda wf, p: "p",
                                budget_minutes=5)

    assert queued == 5 * 60 / UNTIMED_SECONDS, (
        "a low guess queues more than ComfyUI can finish, which the next launch throws away; "
        "a high one costs only another absence")


def test_one_repair_always_goes_however_slow(tmp_path):
    db = Database(tmp_path / "t.db")
    _baked(db, "baked")
    _timed(db, "timed", seconds=600)

    assert queue_base_renders(db.list_generations(), lambda wf, p: "p",
                              budget_minutes=1) == 1


def test_typical_seconds_is_the_median_of_what_was_recorded(tmp_path):
    db = Database(tmp_path / "t.db")
    for i, seconds in enumerate((5, 6, 7, 8, 400)):
        _timed(db, f"t{i}", seconds=seconds)

    rows = db.list_generations()
    assert typical_seconds(rows, "sdxl_t2i") == 7
    assert typical_seconds(rows, "wan22_i2v") == UNTIMED_SECONDS


def test_the_work_left_for_while_closed_reaches_the_queue(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(GenerationJob, "start", lambda self, submit=None: None)
    db = Database(tmp_path / "t.db")
    for i in range(3):
        _baked(db, f"baked{i}", seed=i)
    jobs = JobQueue(db, ComfyUIClient(folders=SUITE_FOLDERS))

    assert downtime.queue_the_work_left(jobs, db.list_generations(), experiments_on=False,
                                        policy=None) == 3

    repairs = [r for r in db.list_generations()
               if r.get("source") == GenerationSource.BASE_RENDER]
    assert {gallery.parse_params(r["params_json"])[TARGET_KEY] for r in repairs} == \
        {"baked0", "baked1", "baked2"}


def test_closing_leaves_work_for_while_closed_and_opening_takes_it_back(qtbot, tmp_path,
                                                                         monkeypatch):
    monkeypatch.setattr(downtime.config, "LIBRARY_STATE_DIR", tmp_path)
    db = Database(tmp_path / "t.db")
    window = Core(ComfyUIClient(folders=SUITE_FOLDERS), db, AppState(tmp_path / "ui.json"))
    qtbot.addWidget(window)

    window.close()
    assert downtime.work_left()

    reopened = Core(ComfyUIClient(folders=SUITE_FOLDERS), db, AppState(tmp_path / "ui.json"))
    qtbot.addWidget(reopened)
    assert not downtime.work_left()


def test_a_branch_sessions_close_leaves_no_work_for_while_closed(qtbot, tmp_path,
                                                                  monkeypatch):
    monkeypatch.setenv(ENV_FLAG, "1")
    monkeypatch.setattr(downtime.config, "LIBRARY_STATE_DIR", tmp_path)
    window = Core(ComfyUIClient(folders=SUITE_FOLDERS), Database(tmp_path / "t.db"),
                  AppState(tmp_path / "ui.json"))
    qtbot.addWidget(window)

    window.close()

    assert not downtime.work_left()


def test_a_broken_close_chore_still_leaves_the_session_saved(qtbot, tmp_path,
                                                             monkeypatch):
    def boom():
        raise AttributeError("module 'origenerator.gallery' has no attribute 'X'")

    db = Database(tmp_path / "t.db")
    state_path = tmp_path / "ui.json"
    window = Core(ComfyUIClient(folders=SUITE_FOLDERS), db, AppState(state_path))
    qtbot.addWidget(window)
    monkeypatch.setattr(window, "_leave_work_for_while_closed", boom)
    window._gallery_view.select_generation("xyz")

    window.close()
    window.hand_comfyui_what_runs_while_closed()

    assert json.loads(state_path.read_text())["gallery_selection"] == "xyz"


class _PollingClient:
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
    now = [0.0]

    def monotonic():
        return now[0]

    def sleep(seconds):
        now[0] += seconds

    return monotonic, sleep


def test_a_repair_run_submits_the_base_settings_and_names_the_files_it_made(tmp_path,
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
    monkeypatch.setattr(
        base_backfill, "extract_completion",
        lambda *a, **k: ([_file("base.png")], None, 4.0))
    client = _PollingClient(after=3, history={"anything": True})
    monotonic, sleep = _clock()

    files = render_base_now(client, _SDXL, _base_params(), now=monotonic, sleep=sleep)

    assert files == [_file("base.png")]
    assert client.polls == 3


def test_a_repair_that_never_finishes_gives_up_rather_than_waiting_forever():
    client = _PollingClient(after=10**9)
    monotonic, sleep = _clock()

    files = render_base_now(client, _SDXL, _base_params(), now=monotonic, sleep=sleep)

    assert files == []
    assert monotonic() >= base_backfill.LONG_ENOUGH_FOR_ONE_IMAGE_ON_ANY_MODEL_SECONDS


def _repairable_db(tmp_path):
    db = Database(tmp_path / "repair.db")
    _add(db, "gone", params=dict(_SDXL.default_params(), seed=3, enhance=True),
         files=[_file("enhanced.png")])
    return db


def test_the_tool_reports_what_it_would_do_and_touches_nothing(tmp_path, capsys):
    db = _repairable_db(tmp_path)

    assert backfill_tool.main(["--db", str(tmp_path / "repair.db")]) == 0

    said = capsys.readouterr().out
    assert "1 enhanced image(s) with no base render kept" in said
    assert "sdxl_t2i: 1" in said
    assert "--apply" in said
    assert not gallery.original_files_of(db.get_generation("gone"))


def test_the_tool_folds_each_repair_into_the_row_it_belongs_to(tmp_path, monkeypatch):
    db = _repairable_db(tmp_path)
    monkeypatch.setattr(backfill_tool, "ComfyUIClient", lambda folders: object())
    monkeypatch.setattr(backfill_tool, "render_base_now",
                        lambda client, workflow, params: [_file("base.png")])

    code = backfill_tool.main(["--apply", "--db", str(tmp_path / "repair.db")])

    assert code == 0
    originals = gallery.original_files_of(db.get_generation("gone"))
    assert [f["filename"] for f in originals] == ["base.png"]


def test_the_tool_reports_a_repair_that_produced_nothing_rather_than_folding_it(
        tmp_path, monkeypatch, capsys):
    db = _repairable_db(tmp_path)
    monkeypatch.setattr(backfill_tool, "ComfyUIClient", lambda folders: object())
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
