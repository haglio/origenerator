import json
from unittest.mock import MagicMock

import pytest

from origenerator import gallery
from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.generation_config import ConfigSnapshot
from origenerator.gui.generate_config_panel import GenerateConfigPanel
from origenerator.workflows import WORKFLOW_REGISTRY

SDXL_HISTORY = {"outputs": {"7": {"images": [{"filename": "a.png", "subfolder": ""}]}}}


@pytest.fixture
def panel(qtbot, tmp_path):
    client = ComfyUIClient()
    client.submit_job = lambda payload, prompt_id: prompt_id
    db = Database(tmp_path / "test.db")
    p = GenerateConfigPanel(client, db)
    qtbot.addWidget(p)
    return p


def _combo_index(panel, key):
    for i in range(panel._workflow_combo.count()):
        if panel._workflow_combo.itemData(i) == key:
            return i
    raise AssertionError(f"workflow {key} not in combo")


def _is_descendant(widget, ancestor) -> bool:
    node = widget.parent()
    while node is not None:
        if node is ancestor:
            return True
        node = node.parent()
    return False


# --- layout: three resizable panes ----------------------------------------

def test_panel_lays_out_three_resizable_panes(panel):
    from PyQt6.QtWidgets import QSplitter
    assert isinstance(panel._panes, QSplitter)
    assert panel._panes.count() == 3


def test_thumbnail_history_is_the_left_pane(panel):
    from origenerator.gui.thumbnail_strip import ThumbnailStrip
    left = panel._panes.widget(0)
    assert left is panel._strip
    assert isinstance(left, ThumbnailStrip)


def test_run_controls_live_in_the_main_pane_not_the_preview(panel):
    # The preview is its own pane; the progress bar and run buttons sit under the
    # middle "main" pane, so they span only the settings, not the preview.
    main = panel._panes.widget(1)
    assert panel._preview is panel._panes.widget(2)
    assert _is_descendant(panel._progress, main)
    assert _is_descendant(panel._generate_btn, main)
    assert _is_descendant(panel._cancel_btn, main)
    assert not _is_descendant(panel._progress, panel._preview)


def test_generate_inserts_row_and_submits(panel):
    panel._on_generate()
    rows = panel._db.list_generations()
    assert len(rows) == 1
    assert rows[0]["workflow_name"] == "sdxl_t2i"
    assert rows[0]["status"] == "running"
    # We submit under the DB row's own id, so ComfyUI's signals key on the same id.
    assert panel._client_prompt_id == rows[0]["prompt_id"]


def _complete_one(panel, seed=12345, prompt="a cat"):
    """Run one generation to completion so a real prior row exists in the DB."""
    panel._param_form.set_values({"seed": seed, "positive_prompt": prompt})
    panel._on_generate()
    panel._client.job_completed.emit(panel._client_prompt_id, SDXL_HISTORY)


def test_generate_warns_on_exact_duplicate_instead_of_resubmitting(panel, monkeypatch):
    _complete_one(panel)
    asked = []
    monkeypatch.setattr(
        panel, "_offer_reroll", lambda wf: asked.append(wf) or False
    )

    panel._on_generate()  # identical config, seed not random

    assert asked, "the user should have been warned about the duplicate"
    assert len(panel._db.list_generations()) == 1  # declined: nothing new submitted
    assert panel._generate_btn.isEnabled() is True  # button re-enabled, not stuck


def test_generate_duplicate_reroll_randomizes_seed_and_checks_random(panel, monkeypatch):
    _complete_one(panel, seed=12345)
    monkeypatch.setattr(panel, "_offer_reroll", lambda wf: True)

    panel._on_generate()

    rows = panel._db.list_generations()  # newest first
    assert len(rows) == 2                 # a new job was submitted
    assert rows[0]["seed"] != 12345       # with a fresh seed, not the duplicate
    assert panel._param_form.seed_is_random() is True  # Random box now checked


def test_generate_with_random_seed_never_warns(panel, monkeypatch):
    _complete_one(panel, seed=12345)         # an identical prior run exists
    panel._param_form.set_seed_random(True)  # but the user re-checks Random
    asked = []
    monkeypatch.setattr(
        panel, "_offer_reroll", lambda wf: asked.append(wf) or False
    )

    panel._on_generate()

    assert asked == []  # a random seed can't reproduce a past run
    assert len(panel._db.list_generations()) == 2


def test_generate_does_not_warn_when_no_prior_match(panel, monkeypatch):
    asked = []
    monkeypatch.setattr(
        panel, "_offer_reroll", lambda wf: asked.append(wf) or False
    )
    panel._param_form.set_values({"seed": 999, "positive_prompt": "novel"})

    panel._on_generate()

    assert asked == []  # nothing matches: generate without nagging
    assert len(panel._db.list_generations()) == 1


def _seed_source_image(db):
    """A completed SDXL image in the DB, to serve as an i2v's reproducible input."""
    sdxl = WORKFLOW_REGISTRY["sdxl_t2i"]
    db.insert_generation(
        prompt_id="img", workflow_name="sdxl_t2i", workflow_version="v002",
        positive_prompt="a cat", seed=7,
        params_json=json.dumps(dict(sdxl.default_params(), seed=7, positive_prompt="a cat")),
        workflow_json="{}",
    )
    db.update_generation("img", status="completed",
                         output_files=json.dumps([{"filename": "sdxl_src.png", "subfolder": "image"}]))


def _i2v_panel(qtbot, tmp_path, submit):
    client = ComfyUIClient()
    client.submit_job = submit
    db = Database(tmp_path / "t.db")
    _seed_source_image(db)
    panel = GenerateConfigPanel(client, db)
    qtbot.addWidget(panel)
    panel._workflow_combo.setCurrentIndex(_combo_index(panel, "wan22_i2v"))
    return panel, client, db


def test_random_input_box_shows_only_for_a_reproducible_input(qtbot, tmp_path):
    panel, _client, _db = _i2v_panel(qtbot, tmp_path, lambda *a: "comfy-A")
    box = panel._param_form._image_random_checks["input_image"]

    panel._param_form.set_values({"input_image": "hand_placed.png"})  # not a generation
    assert box.isHidden()

    panel._param_form.set_values({"input_image": "sdxl_src.png"})     # a known generation
    assert not box.isHidden()


def test_random_input_generates_a_fresh_image_then_the_video(qtbot, tmp_path):
    submit = MagicMock(return_value="x")
    panel, client, db = _i2v_panel(qtbot, tmp_path, submit)
    panel._param_form.set_values({"input_image": "sdxl_src.png", "positive_prompt": "dance"})
    panel._param_form._image_random_checks["input_image"].setChecked(True)

    panel._on_generate()

    # Stage 1: a fresh input image is generating (its own SDXL job), not the video.
    assert panel._input_image_job is not None
    assert panel._input_image_job.workflow.name == "sdxl_t2i"
    assert db.get_generation("img")  # the original source is untouched
    img_id = panel._input_image_job.prompt_id  # the pre-step's own id ComfyUI runs it under

    client.job_completed.emit(img_id, SDXL_HISTORY)  # the image finishes

    # Stage 2: the fresh image is saved and the video runs on it.
    assert panel._input_image_job is None
    fresh = [r for r in db.list_generations()
             if r["workflow_name"] == "sdxl_t2i" and r["prompt_id"] != "img"]
    assert len(fresh) == 1
    assert panel._client_prompt_id is not None  # the video job is now running
    video = next(r for r in db.list_generations() if r["workflow_name"] == "wan22_i2v")
    params = json.loads(video["params_json"])
    assert params["input_image"] == "a.png [output]"  # the fresh image's output, annotated
    assert params["positive_prompt"] == "dance"


def test_random_input_state_survives_capture_and_restore(qtbot, tmp_path):
    panel, client, db = _i2v_panel(qtbot, tmp_path, lambda p: "comfy-A")
    panel._param_form.set_values({"input_image": "sdxl_src.png"})  # reproducible → box shows
    panel._param_form._image_random_checks["input_image"].setChecked(True)

    snapshot = panel.current_config()
    assert snapshot.image_is_random is True

    restored = GenerateConfigPanel(client, db)
    qtbot.addWidget(restored)
    restored.restore_config(snapshot)

    assert restored._param_form.image_is_random() is True


def test_video_stage_keeps_the_input_image_frame_until_the_video_previews(qtbot, tmp_path):
    # The random-input i2v flow shows the image being generated, then the video.
    # Starting the video must not clear the image frame — it stays until the video
    # streams its own first frame — so the preview doesn't blank between stages.
    submit = MagicMock(return_value="x")
    panel, client, _db = _i2v_panel(qtbot, tmp_path, submit)
    panel._param_form.set_values({"input_image": "sdxl_src.png", "positive_prompt": "dance"})
    panel._param_form._image_random_checks["input_image"].setChecked(True)
    panel._on_generate()
    img_id = panel._input_image_job.prompt_id
    panel._preview.clear = MagicMock()

    client.job_completed.emit(img_id, SDXL_HISTORY)  # image done -> the video stage begins

    assert panel._client_prompt_id is not None       # the video job is running
    panel._preview.clear.assert_not_called()          # the input image frame is left up


def test_plain_generate_clears_the_previous_result(qtbot, tmp_path):
    # A fresh, non-chained job still drops whatever the preview last showed.
    submit = MagicMock(return_value="x")
    panel, _client, _db = _i2v_panel(qtbot, tmp_path, submit)
    panel._workflow_combo.setCurrentIndex(_combo_index(panel, "sdxl_t2i"))
    panel._preview.clear = MagicMock()

    panel._on_generate()

    panel._preview.clear.assert_called_once()


def test_completion_only_handled_for_own_prompt_id(panel):
    panel._on_generate()
    our_id = panel._client_prompt_id

    # A sibling panel's job completing must not touch this panel.
    panel._client.job_completed.emit("comfy-OTHER", SDXL_HISTORY)
    assert panel._db.get_generation(our_id)["status"] == "running"
    assert panel._generate_btn.isEnabled() is False
    assert our_id not in panel._strip_ids  # our run isn't done, so not in the strip

    # Our own job's completion is handled.
    panel._client.job_completed.emit(our_id, SDXL_HISTORY)
    row = panel._db.get_generation(our_id)
    assert row["status"] == "completed"
    assert "a.png" in row["output_files"]
    assert panel._generate_btn.isEnabled() is True
    assert panel._strip_ids == [our_id]  # the finished run now leads this tab's strip


def test_progress_only_moves_for_own_prompt_id(panel):
    panel._on_generate()
    panel._client.progress.emit("comfy-OTHER", 5, 10)
    assert panel._progress.property("barState") == "queued"  # foreign progress ignored
    panel._client.progress.emit(panel._client_prompt_id, 5, 10)
    assert panel._progress.value() == 5


def test_progress_bar_accumulates_across_sampler_stages(panel):
    # A dual-noise workflow samples in two passes; ComfyUI restarts its step
    # count each pass. The bar must ramp once from 0 to the run's total rather
    # than fill, snap back to 0, and fill again.
    panel._workflow_combo.setCurrentIndex(_combo_index(panel, "wan22_t2i"))
    panel._param_form.set_values({"steps": 20})
    panel._on_generate()

    pid = panel._client_prompt_id
    panel._client.progress.emit(pid, 10, 10)   # first pass ends (10 of 20)
    assert panel._progress.maximum() == 20
    assert panel._progress.value() == 10

    panel._client.progress.emit(pid, 1, 10)    # second pass restarts at 1
    assert panel._progress.value() == 11             # continues, not reset to 1


# ---- server-side queue (ComfyUI busy with work from outside Origenerator) ----


def test_bar_stays_queued_until_comfyui_starts_our_prompt(panel):
    # ComfyUI may be busy with a prompt submitted outside Origenerator, so ours
    # can sit in the server's queue before it starts. Until then the bar reads
    # "queued", not a stuck "Generating… 0%".
    panel._on_generate()
    assert panel._progress.property("barState") == "queued"
    assert "queued" in panel._progress.format().lower()


def test_bar_flips_to_running_when_comfyui_starts_our_prompt(panel):
    panel._on_generate()
    panel._client.node_executing.emit(panel._client_prompt_id, "5")  # ComfyUI begins our prompt
    assert panel._progress.property("barState") == "running"
    assert "generating" in panel._progress.format().lower()


def test_foreign_prompt_starting_leaves_our_bar_queued(panel):
    # If a sibling job (or outside work) starting flipped us to "running", we'd be
    # back to a bar that claims it's generating while still stuck in the queue.
    panel._on_generate()
    panel._client.node_executing.emit("comfy-OTHER", "5")
    assert panel._progress.property("barState") == "queued"


def test_error_marks_row_for_own_id_only(panel):
    panel._on_generate()
    our_id = panel._client_prompt_id

    panel._client.job_error.emit("comfy-OTHER", "boom")
    assert panel._db.get_generation(our_id)["status"] == "running"

    panel._client.job_error.emit(our_id, "boom")
    assert panel._db.get_generation(our_id)["status"] == "error"
    assert panel._generate_btn.isEnabled() is True


def test_completion_uses_workflow_captured_at_submit(panel):
    panel._on_generate()  # submitted with the default workflow, sdxl_t2i
    our_id = panel._client_prompt_id
    # User switches the workflow combo while the job is still running.
    panel._workflow_combo.setCurrentIndex(_combo_index(panel, "wan22_i2v"))
    panel._client.job_completed.emit(our_id, SDXL_HISTORY)
    row = panel._db.get_generation(our_id)
    # Outputs extracted via sdxl's node (7), not the now-current wan22's node (19).
    assert "a.png" in row["output_files"]


def test_current_config_does_not_randomize_and_reports_random_flag(panel):
    snap1 = panel.current_config()
    snap2 = panel.current_config()
    assert snap1.workflow_name == "sdxl_t2i"
    assert snap1.seed_is_random is True  # fresh panel: Random box checked
    assert snap1.params["seed"] == snap2.params["seed"]  # not re-randomized

    panel.prefill("sdxl_t2i", {"seed": 99})
    snap3 = panel.current_config()
    assert snap3.seed_is_random is False
    assert snap3.params["seed"] == 99


def test_prefill_selects_workflow_and_sets_values(panel):
    panel.prefill("wan22_i2v", {"positive_prompt": "a fox"})
    assert panel._workflow_combo.currentData() == "wan22_i2v"
    assert panel._param_form.get_values_static()["positive_prompt"] == "a fox"


def test_restore_config_reapplies_workflow_params_and_random_seed(panel):
    snap = ConfigSnapshot("wan22_i2v", {"positive_prompt": "a fox"}, seed_is_random=True)
    panel.restore_config(snap)
    assert panel._workflow_combo.currentData() == "wan22_i2v"
    assert panel._param_form.get_values_static()["positive_prompt"] == "a fox"
    # A tab that was on Random comes back random, not frozen on a stale seed.
    assert panel._param_form.seed_is_random() is True


def test_restore_config_pins_concrete_seed_when_not_random(panel):
    panel.restore_config(ConfigSnapshot("sdxl_t2i", {"seed": 99}, seed_is_random=False))
    snap = panel.current_config()
    assert snap.seed_is_random is False
    assert snap.params["seed"] == 99


def test_teardown_stops_handling_signals(panel):
    panel._on_generate()
    our_id = panel._client_prompt_id
    panel.teardown()
    panel._client.job_completed.emit(our_id, SDXL_HISTORY)
    # After teardown the panel ignores the client entirely.
    assert panel._db.get_generation(our_id)["status"] == "running"


def test_generate_blocks_when_input_image_missing(qtbot, tmp_path):
    client = MagicMock()
    panel = GenerateConfigPanel(client, Database(tmp_path / "t.db"))
    qtbot.addWidget(panel)
    panel._workflow_combo.setCurrentIndex(_combo_index(panel, "wan22_i2v"))
    panel._on_generate()
    client.submit_job.assert_not_called()
    assert "image" in panel._progress.format().lower()
    assert panel._db.list_generations() == []  # nothing recorded


def test_generate_submits_when_input_image_present(qtbot, tmp_path):
    client = MagicMock()
    client.submit_job.return_value = "comfy-prompt-id"
    panel = GenerateConfigPanel(client, Database(tmp_path / "t.db"))
    qtbot.addWidget(panel)
    panel._workflow_combo.setCurrentIndex(_combo_index(panel, "wan22_i2v"))
    panel._param_form.set_values({"input_image": "start.png"})
    panel._on_generate()
    client.submit_job.assert_called_once()


def test_i2v_generate_derives_size_in_payload_and_stores_none(qtbot, tmp_path):
    client = MagicMock()
    client.submit_job.return_value = "comfy-A"
    panel = GenerateConfigPanel(client, Database(tmp_path / "t.db"))
    qtbot.addWidget(panel)
    panel._workflow_combo.setCurrentIndex(_combo_index(panel, "wan22_i2v"))
    panel._param_form.set_values({"input_image": "start.png"})

    panel._on_generate()

    payload = client.submit_job.call_args[0][0]
    # Size is derived in-graph (scale-to-budget + get-size), not hardcoded...
    assert any(n["class_type"] == "ImageScaleToTotalPixels" for n in payload.values())
    assert any(n["class_type"] == "GetImageSize" for n in payload.values())
    # ...and never persisted as a setting.
    stored = json.loads(panel._db.list_generations()[0]["params_json"])
    assert "width" not in stored and "height" not in stored


def test_reused_lora_survives_to_the_generated_payload(qtbot, tmp_path):
    # "Reuse Parameters" prefills a past generation's config, LoRA included. The
    # WAN LoRA has no form widget (it lives only in default_params), so a naive
    # form round-trip would drop the reused choice and the payload would fall back
    # to the workflow's default LoRA. The reused LoRA must reach the graph instead.
    client = MagicMock()
    client.submit_job.return_value = "comfy-A"
    panel = GenerateConfigPanel(client, Database(tmp_path / "t.db"))
    qtbot.addWidget(panel)

    panel.prefill("wan22_i2v", {
        "input_image": "start.png",
        "lora_high": "custom-high.safetensors",
        "lora_low": "custom-low.safetensors",
    })
    panel._on_generate()

    payload = client.submit_job.call_args[0][0]
    loras = {
        node["inputs"]["lora_name"]
        for node in payload.values()
        if node["class_type"] == "LoraLoaderModelOnly"
    }
    assert loras == {"custom-high.safetensors", "custom-low.safetensors"}
    # And it's persisted, so the row remains reusable (and folders by this LoRA).
    stored = json.loads(panel._db.list_generations()[0]["params_json"])
    assert stored["lora_high"] == "custom-high.safetensors"
    assert stored["lora_low"] == "custom-low.safetensors"


class SpyDB:
    """Records the calls a panel makes, returning canned recent durations.

    It stores no rows, so ``get_generation`` (used when the panel re-renders its
    strip on completion) always returns ``None`` — the strip stays empty, which
    these duration/status tests don't inspect.
    """

    def __init__(self, durations=None):
        self._durations = durations or []
        self.updates = []
        self.inserts = []

    def recent_durations(self, workflow_name, limit=10):
        return list(self._durations)

    def insert_generation(self, **kwargs):
        self.inserts.append(kwargs)

    def update_generation(self, prompt_id, **fields):
        self.updates.append((prompt_id, fields))

    def get_generation(self, prompt_id):
        return None


def _history_with_duration(seconds):
    ms = int(seconds * 1000)
    return {"status": {"messages": [
        ["execution_start", {"timestamp": 1_000}],
        ["execution_success", {"timestamp": 1_000 + ms}],
    ]}}


def _spy_panel(qtbot, db):
    panel = GenerateConfigPanel(ComfyUIClient(), db)
    qtbot.addWidget(panel)
    return panel


def test_on_completed_records_execution_duration(qtbot):
    db = SpyDB()
    panel = _spy_panel(qtbot, db)
    panel._client_prompt_id = "p1"
    panel._submitted_workflow = WORKFLOW_REGISTRY["sdxl_t2i"]

    panel._on_completed("p1", _history_with_duration(15.26))

    prompt_id, fields = db.updates[-1]
    assert prompt_id == "p1"
    assert fields["status"] == "completed"
    assert fields["duration_seconds"] == 15.26


def test_estimate_label_reflects_recent_durations(qtbot):
    panel = _spy_panel(qtbot, SpyDB(durations=[700.0, 724.0, 800.0]))
    assert panel._estimate_label.text() == "Typical time: ~12 min (based on 3 runs)"


def test_estimate_label_when_no_history(qtbot):
    panel = _spy_panel(qtbot, SpyDB(durations=[]))
    assert panel._estimate_label.text() == "Typical time: No timing data yet"


def test_on_completed_status_shows_actual_time(qtbot):
    db = SpyDB()
    panel = _spy_panel(qtbot, db)
    panel._client_prompt_id = "p1"
    panel._submitted_workflow = WORKFLOW_REGISTRY["sdxl_t2i"]

    panel._on_completed("p1", _history_with_duration(905))

    assert panel._progress.format() == "Done in 15 min 5 sec"


# ---- reconnect to a job left running by a previous session ----

def test_active_prompt_id_reports_in_flight_then_clears(panel):
    assert panel.active_prompt_id() is None
    panel._on_generate()
    assert panel.active_prompt_id() == panel._client_prompt_id
    panel._client.job_completed.emit(panel._client_prompt_id, SDXL_HISTORY)
    assert panel.active_prompt_id() is None


def test_reconnect_binds_panel_to_a_running_job(panel):
    wf = WORKFLOW_REGISTRY["sdxl_t2i"]
    payload = wf.build_api_payload(wf.default_params())
    panel._db.insert_generation(
        prompt_id="run-1", workflow_name="sdxl_t2i", workflow_version="v",
        params_json="{}", workflow_json=json.dumps(payload),
    )
    panel._db.update_generation("run-1", status="running")

    panel.reconnect("run-1", wf, payload)

    assert panel.active_prompt_id() == "run-1"
    assert panel._cancel_btn.isEnabled() is True
    assert panel._generate_btn.isEnabled() is False

    panel._client.progress.emit("run-1", 25, 50)  # ComfyUI's live progress resumes
    assert panel._progress.property("barState") == "running"

    panel._client.job_completed.emit("run-1", SDXL_HISTORY)
    assert panel._db.get_generation("run-1")["status"] == "completed"
    assert panel.active_prompt_id() is None


def test_reconnected_job_is_cancelable(panel):
    panel._client.interrupt = MagicMock()
    wf = WORKFLOW_REGISTRY["sdxl_t2i"]
    panel._db.insert_generation(
        prompt_id="run-1", workflow_name="sdxl_t2i", workflow_version="v",
        params_json="{}", workflow_json="{}",
    )
    panel._db.update_generation("run-1", status="running")
    panel.reconnect("run-1", wf, {})
    panel._client.node_executing.emit("run-1", "5")  # it's executing

    panel._on_cancel()

    panel._client.interrupt.assert_called_once()
    assert panel._db.get_generation("run-1") is None  # canceled run leaves no trace


def test_title_is_workflow_name_for_blank_config(panel):
    assert panel.title() == "SDXL Text-to-Image"


def test_title_leads_with_model_then_prompt(panel):
    panel.prefill("sdxl_t2i", {"positive_prompt": "a cat in a hat"})
    assert panel.title() == "SDXL Text-to-Image › a cat in a hat"


def test_title_changed_emitted_when_prompt_edited(panel):
    titles = []
    panel.title_changed.connect(titles.append)
    panel.prefill("sdxl_t2i", {"positive_prompt": "a fox"})
    assert titles and titles[-1] == "SDXL Text-to-Image › a fox"


def test_custom_title_overrides_and_sticks(panel):
    panel.set_custom_title("My experiments")
    assert panel.title() == "My experiments"
    panel.prefill("sdxl_t2i", {"positive_prompt": "a fox"})
    assert panel.title() == "My experiments"  # rename survives config changes


class FakeQueue:
    """A queue that records calls but never auto-starts the next job."""

    def __init__(self):
        self.submitted = []
        self.released = []
        self.canceled = []

    def submit(self, panel, workflow_name):
        self.submitted.append((panel, workflow_name))

    def release(self, panel):
        self.released.append(panel)

    def cancel(self, panel):
        self.canceled.append(panel)


def _queued_panel(qtbot, tmp_path):
    client = MagicMock()
    client.submit_job.return_value = "comfy-A"
    queue = FakeQueue()
    panel = GenerateConfigPanel(client, Database(tmp_path / "t.db"), queue=queue)
    qtbot.addWidget(panel)
    return panel, client, queue


def test_generate_with_queue_defers_submission(qtbot, tmp_path):
    panel, client, queue = _queued_panel(qtbot, tmp_path)
    panel._on_generate()
    assert queue.submitted == [(panel, "sdxl_t2i")]
    client.submit_job.assert_not_called()       # nothing reaches ComfyUI yet
    assert panel._db.list_generations() == []    # and nothing is recorded yet
    assert "queued" in panel._progress.format().lower()
    assert panel._generate_btn.isEnabled() is False


def test_run_now_begins_the_prepared_job(qtbot, tmp_path):
    panel, client, queue = _queued_panel(qtbot, tmp_path)
    panel._on_generate()
    panel.run_now()
    client.submit_job.assert_called_once()
    rows = panel._db.list_generations()
    assert len(rows) == 1 and rows[0]["status"] == "running"


def test_completion_releases_queue_slot(qtbot, tmp_path):
    panel, client, queue = _queued_panel(qtbot, tmp_path)
    panel._on_generate()
    panel.run_now()
    panel._on_completed(panel._client_prompt_id, SDXL_HISTORY)
    assert queue.released == [panel]


def test_set_queue_status_shows_position_and_eta(panel):
    panel.set_queue_status(2, 905.0)
    text = panel._progress.format()
    assert "#2" in text and "15 min" in text


def test_completion_colors_the_bar_done(panel):
    panel._client_prompt_id = "p1"
    panel._submitted_workflow = WORKFLOW_REGISTRY["sdxl_t2i"]
    panel._on_completed("p1", SDXL_HISTORY)
    assert panel._progress.property("barState") == "done"


def test_error_colors_the_bar_red(panel):
    panel._client_prompt_id = "p1"
    panel._submitted_workflow = WORKFLOW_REGISTRY["sdxl_t2i"]
    panel._on_error("p1", "boom")
    assert panel._progress.property("barState") == "error"


def test_queue_status_colors_the_bar_grey(panel):
    panel.set_queue_status(1, 0)
    assert panel._progress.property("barState") == "queued"


def test_settings_key_matches_a_stored_generation_of_the_same_settings(panel):
    full = dict(WORKFLOW_REGISTRY["sdxl_t2i"].default_params())
    full["positive_prompt"] = "a cat"
    panel.prefill("sdxl_t2i", full)
    workflow, signature = panel.settings_key()
    assert workflow == "sdxl_t2i"
    # The same params at any seed share the signature; a different setting splits it.
    assert signature == gallery.settings_signature("sdxl_t2i", json.dumps({**full, "seed": 999}))
    assert signature != gallery.settings_signature("sdxl_t2i", json.dumps({**full, "steps": 7}))


# ---- live preview ----

def test_preview_frame_shown_only_for_own_job(panel):
    panel._on_generate()
    panel._preview.show_frame = MagicMock()

    panel._client.preview_image.emit("comfy-OTHER", b"x")
    panel._preview.show_frame.assert_not_called()

    panel._client.preview_image.emit(panel._client_prompt_id, b"img-bytes")
    panel._preview.show_frame.assert_called_once_with(b"img-bytes")


# ---- cancel ----

def test_cancel_disabled_until_a_job_starts(panel):
    assert panel._cancel_btn.isEnabled() is False
    panel._on_generate()
    assert panel._cancel_btn.isEnabled() is True


def test_cancel_running_job_interrupts_and_removes_row(panel):
    panel._client.interrupt = MagicMock()
    panel._client.cancel_prompt = MagicMock()
    panel._on_generate()
    our_id = panel._client_prompt_id
    panel._client.node_executing.emit(our_id, "5")  # our job is now executing

    panel._on_cancel()

    panel._client.interrupt.assert_called_once()
    panel._client.cancel_prompt.assert_not_called()
    assert panel._db.get_generation(our_id) is None  # a canceled run leaves no trace
    assert panel._generate_btn.isEnabled() is True
    assert panel._cancel_btn.isEnabled() is False


def test_cancel_submitted_but_unstarted_job_dequeues(panel):
    panel._client.interrupt = MagicMock()
    panel._client.cancel_prompt = MagicMock()
    panel._on_generate()  # submitted to ComfyUI but no executing signal yet
    our_id = panel._client_prompt_id

    panel._on_cancel()

    panel._client.cancel_prompt.assert_called_once_with(our_id)
    panel._client.interrupt.assert_not_called()
    assert panel._db.get_generation(our_id) is None


def test_cancel_while_queued_drops_the_queue_slot(qtbot, tmp_path):
    panel, client, queue = _queued_panel(qtbot, tmp_path)
    panel._on_generate()  # queued in the JobQueue, not yet submitted

    panel._on_cancel()

    assert queue.canceled == [panel]
    client.submit_job.assert_not_called()
    assert panel._db.list_generations() == []  # nothing was ever recorded
    assert panel._cancel_btn.isEnabled() is False


def test_completed_job_cannot_be_canceled(panel):
    panel._client.interrupt = MagicMock()
    panel._on_generate()
    panel._client.job_completed.emit(panel._client_prompt_id, SDXL_HISTORY)

    panel._on_cancel()  # no in-flight job remains

    panel._client.interrupt.assert_not_called()
    assert panel._cancel_btn.isEnabled() is False


def test_cancel_colors_the_bar_yellow(panel):
    panel._client.cancel_prompt = MagicMock()
    panel._on_generate()
    panel._on_cancel()
    assert panel._progress.property("barState") == "canceled"
