import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from origenerator import evolver_export, gallery
from origenerator.comfyui_client import ComfyUIClient
from origenerator.config import EVOLVER_INBOX_DIR, EVOLVER_SOURCE
from origenerator.db import Database
from origenerator.generation_config import ConfigSnapshot
from origenerator.gui import generate_config_panel as gcp_module
from origenerator.gui.animated_strip import _VideoTile
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


def _submit(panel):
    """Drive the panel's own job to a submitted (running) state.

    Clicking Generate now only *emits* :attr:`generate_requested` — the gallery
    launches the job as a re-roll. The panel keeps its job machinery (submit,
    progress, completion, cancel, reconnect) for a container to drive; these tests
    exercise that machinery directly, standing in for the launcher by building the
    current form's job and beginning it, exactly as the old Generate did inline.
    """
    key = panel._workflow_combo.currentData()
    wf = WORKFLOW_REGISTRY[key]
    params = dict(wf.default_params(), **panel._param_form.get_values())
    panel._generate(wf, params)


def _is_descendant(widget, ancestor) -> bool:
    node = widget.parent()
    while node is not None:
        if node is ancestor:
            return True
        node = node.parent()
    return False


# --- layout: preview-over-form beside a slim history strip -----------------

def test_panel_lays_out_two_resizable_panes(panel):
    from PyQt6.QtWidgets import QSplitter
    assert isinstance(panel._panes, QSplitter)
    assert panel._panes.count() == 2


def test_thumbnail_history_is_the_right_pane(panel):
    from origenerator.gui.thumbnail_strip import ThumbnailStrip
    right = panel._panes.widget(1)
    assert right is panel._strip
    assert isinstance(right, ThumbnailStrip)


# --- a read-only gallery (no client) ----------------------------------------

def test_tolerates_a_missing_client(qtbot, tmp_path):
    # A read-only gallery has no ComfyUI client. The panel still builds — the form
    # shows for inspection — but Generate is disabled and no signals are wired.
    p = GenerateConfigPanel(None, Database(tmp_path / "t.db"))
    qtbot.addWidget(p)
    assert p._generate_btn.isEnabled() is False
    p._on_generate()                      # no-op, no crash
    assert p.active_prompt_id() is None
    p.teardown()                          # never connected, so a no-op too


# --- show the newest matching generation instead of the blank placeholder -----

def _wiz_params():
    return dict(WORKFLOW_REGISTRY["sdxl_t2i"].default_params(), positive_prompt="a wizard")


def test_recent_matching_row_finds_only_the_folders_own(qtbot, tmp_path):
    db = Database(tmp_path / "t.db")
    db.insert_generation(
        prompt_id="wiz", workflow_name="sdxl_t2i", workflow_version="v",
        positive_prompt="a wizard", params_json=json.dumps(_wiz_params()), workflow_json="{}",
    )
    db.insert_generation(  # a different prompt → a different settings folder
        prompt_id="drg", workflow_name="sdxl_t2i", workflow_version="v",
        positive_prompt="a dragon",
        params_json=json.dumps(dict(WORKFLOW_REGISTRY["sdxl_t2i"].default_params(),
                                    positive_prompt="a dragon")),
        workflow_json="{}",
    )
    panel = GenerateConfigPanel(ComfyUIClient(), db)
    qtbot.addWidget(panel)
    panel.prefill("sdxl_t2i", _wiz_params())
    assert panel._recent_matching_row()["prompt_id"] == "wiz"  # the dragon isn't in this folder


def test_prefill_shows_the_recent_match_in_the_preview(qtbot, tmp_path, monkeypatch):
    db = Database(tmp_path / "t.db")
    db.insert_generation(
        prompt_id="g1", workflow_name="sdxl_t2i", workflow_version="v",
        positive_prompt="a wizard", params_json=json.dumps(_wiz_params()), workflow_json="{}",
    )
    monkeypatch.setattr(gcp_module, "resolve_preview", lambda row, out: ("wiz.png", "image"))
    panel = GenerateConfigPanel(ComfyUIClient(), db)
    qtbot.addWidget(panel)
    shown = []
    monkeypatch.setattr(panel._preview, "show_media", lambda path, mt: shown.append((path, mt)))

    panel.prefill("sdxl_t2i", _wiz_params())

    assert shown[-1] == ("wiz.png", "image")


def test_idle_panel_with_no_matching_generation_stays_blank(qtbot, tmp_path):
    # Nothing generated with these settings yet → the placeholder, no crash.
    panel = GenerateConfigPanel(ComfyUIClient(), Database(tmp_path / "t.db"))
    qtbot.addWidget(panel)
    panel.show_recent_preview()
    assert panel._preview._media is None  # a placeholder, not a resolved file


def test_preview_over_form_share_the_main_pane(panel):
    # Preview-over-form: the live preview sits on top of the settings in the left
    # "main" pane, with the progress bar and run buttons under it — beside the slim
    # history strip. The preview is no longer its own splitter pane.
    main = panel._panes.widget(0)
    assert _is_descendant(panel._preview, main)
    assert _is_descendant(panel._progress, main)
    assert _is_descendant(panel._generate_btn, main)
    assert _is_descendant(panel._cancel_btn, main)
    assert panel._preview is not main  # nested inside the pane, not the pane itself


def test_generate_emits_generate_requested_with_workflow_and_params(panel):
    # Clicking Generate no longer runs its own job — it asks the gallery to, by
    # emitting the workflow and the form's values (which the gallery launches as a
    # re-roll of the config's folder). Nothing is submitted or recorded here.
    panel._param_form.set_values({"positive_prompt": "a wizard", "seed": 42})
    requested = []
    panel.generate_requested.connect(lambda wf, params: requested.append((wf, params)))

    panel._on_generate()

    assert len(requested) == 1
    workflow_name, params = requested[0]
    assert workflow_name == "sdxl_t2i"
    assert params["positive_prompt"] == "a wizard"
    assert params["seed"] == 42
    assert panel._db.list_generations() == []       # the panel submits nothing itself
    assert panel._client_prompt_id is None


def test_generate_randomizes_a_random_seed_before_emitting(panel):
    # A Random seed is re-rolled by the form's get_values, so the params carried to
    # the gallery already hold a concrete fresh seed (never the literal field text).
    panel._param_form.set_values({"positive_prompt": "a cat"})  # leaves Random checked
    assert panel._param_form.seed_is_random() is True
    requested = []
    panel.generate_requested.connect(lambda wf, params: requested.append(params))

    panel._on_generate()

    assert isinstance(requested[0]["seed"], int)  # a real seed, drawn for this run


def _complete_one(panel, seed=12345, prompt="a cat"):
    """Run one generation to completion so a real prior row exists in the DB."""
    panel._param_form.set_values({"seed": seed, "positive_prompt": prompt})
    _submit(panel)
    panel._client.job_completed.emit(panel._client_prompt_id, SDXL_HISTORY)


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


def test_plain_generate_clears_the_previous_result(qtbot, tmp_path):
    # A fresh, non-chained job still drops whatever the preview last showed.
    submit = MagicMock(return_value="x")
    panel, _client, _db = _i2v_panel(qtbot, tmp_path, submit)
    panel._workflow_combo.setCurrentIndex(_combo_index(panel, "sdxl_t2i"))
    panel._preview.clear = MagicMock()

    _submit(panel)

    panel._preview.clear.assert_called_once()


def test_completion_only_handled_for_own_prompt_id(panel):
    _submit(panel)
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
    _submit(panel)
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
    _submit(panel)

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
    _submit(panel)
    assert panel._progress.property("barState") == "queued"
    assert "queued" in panel._progress.format().lower()


def test_bar_flips_to_running_when_comfyui_starts_our_prompt(panel):
    _submit(panel)
    panel._client.node_executing.emit(panel._client_prompt_id, "5")  # ComfyUI begins our prompt
    assert panel._progress.property("barState") == "running"
    assert "generating" in panel._progress.format().lower()


def test_foreign_prompt_starting_leaves_our_bar_queued(panel):
    # If a sibling job (or outside work) starting flipped us to "running", we'd be
    # back to a bar that claims it's generating while still stuck in the queue.
    _submit(panel)
    panel._client.node_executing.emit("comfy-OTHER", "5")
    assert panel._progress.property("barState") == "queued"


def test_error_marks_row_for_own_id_only(panel):
    _submit(panel)
    our_id = panel._client_prompt_id

    panel._client.job_error.emit("comfy-OTHER", "boom")
    assert panel._db.get_generation(our_id)["status"] == "running"

    panel._client.job_error.emit(our_id, "boom")
    assert panel._db.get_generation(our_id)["status"] == "error"
    assert panel._generate_btn.isEnabled() is True


def test_completion_uses_workflow_captured_at_submit(panel):
    _submit(panel)  # submitted with the default workflow, sdxl_t2i
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
    _submit(panel)
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
    _submit(panel)
    client.submit_job.assert_called_once()


def test_i2v_generate_derives_size_in_payload_and_stores_none(qtbot, tmp_path):
    client = MagicMock()
    client.submit_job.return_value = "comfy-A"
    panel = GenerateConfigPanel(client, Database(tmp_path / "t.db"))
    qtbot.addWidget(panel)
    panel._workflow_combo.setCurrentIndex(_combo_index(panel, "wan22_i2v"))
    panel._param_form.set_values({"input_image": "start.png"})

    _submit(panel)

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
    _submit(panel)

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
    strip on completion) always returns ``None`` and ``list_generations`` (queried
    when the panel shows its settings' most recent result) returns ``[]`` — the
    strip and the recent-preview stay empty, which these duration/status tests
    don't inspect.
    """

    def __init__(self, durations=None):
        self._durations = durations or []
        self.updates = []
        self.inserts = []

    def recent_durations(self, workflow_name, limit=10):
        return list(self._durations)

    def list_generations(self):
        return []

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
    _submit(panel)
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
    _submit(panel)
    assert queue.submitted == [(panel, "sdxl_t2i")]
    client.submit_job.assert_not_called()       # nothing reaches ComfyUI yet
    assert panel._db.list_generations() == []    # and nothing is recorded yet
    assert "queued" in panel._progress.format().lower()
    assert panel._generate_btn.isEnabled() is False


def test_run_now_begins_the_prepared_job(qtbot, tmp_path):
    panel, client, queue = _queued_panel(qtbot, tmp_path)
    _submit(panel)
    panel.run_now()
    client.submit_job.assert_called_once()
    rows = panel._db.list_generations()
    assert len(rows) == 1 and rows[0]["status"] == "running"


def test_completion_releases_queue_slot(qtbot, tmp_path):
    panel, client, queue = _queued_panel(qtbot, tmp_path)
    _submit(panel)
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
    _submit(panel)
    panel._preview.show_frame = MagicMock()

    panel._client.preview_image.emit("comfy-OTHER", b"x")
    panel._preview.show_frame.assert_not_called()

    panel._client.preview_image.emit(panel._client_prompt_id, b"img-bytes")
    panel._preview.show_frame.assert_called_once_with(b"img-bytes")


# ---- cancel ----

def test_cancel_disabled_until_a_job_starts(panel):
    assert panel._cancel_btn.isEnabled() is False
    _submit(panel)
    assert panel._cancel_btn.isEnabled() is True


def test_cancel_running_job_interrupts_and_removes_row(panel):
    panel._client.interrupt = MagicMock()
    panel._client.cancel_prompt = MagicMock()
    _submit(panel)
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
    _submit(panel)  # submitted to ComfyUI but no executing signal yet
    our_id = panel._client_prompt_id

    panel._on_cancel()

    panel._client.cancel_prompt.assert_called_once_with(our_id)
    panel._client.interrupt.assert_not_called()
    assert panel._db.get_generation(our_id) is None


def test_cancel_while_queued_drops_the_queue_slot(qtbot, tmp_path):
    panel, client, queue = _queued_panel(qtbot, tmp_path)
    _submit(panel)  # queued in the JobQueue, not yet submitted

    panel._on_cancel()

    assert queue.canceled == [panel]
    client.submit_job.assert_not_called()
    assert panel._db.list_generations() == []  # nothing was ever recorded
    assert panel._cancel_btn.isEnabled() is False


def test_completed_job_cannot_be_canceled(panel):
    panel._client.interrupt = MagicMock()
    _submit(panel)
    panel._client.job_completed.emit(panel._client_prompt_id, SDXL_HISTORY)

    panel._on_cancel()  # no in-flight job remains

    panel._client.interrupt.assert_not_called()
    assert panel._cancel_btn.isEnabled() is False


def test_cancel_colors_the_bar_yellow(panel):
    panel._client.cancel_prompt = MagicMock()
    _submit(panel)
    panel._on_cancel()
    assert panel._progress.property("barState") == "canceled"


# --- in-flight descriptor: what the gallery's Recents shelf reads from a tab ---

def test_in_flight_descriptor_is_none_when_idle(panel):
    assert panel.in_flight_descriptor() is None


def test_in_flight_descriptor_reports_a_running_job_and_mirrors_its_frame(panel):
    panel._param_form.set_values({"positive_prompt": "a cat", "seed": 1})
    _submit(panel)  # no queue: submits at once, then waits on ComfyUI
    desc = panel.in_flight_descriptor()
    assert desc["key"] == panel._client_prompt_id
    assert desc["status"] == "queued"        # submitted, ComfyUI hasn't begun it
    assert desc["frame"] is None

    panel._client.preview_image.emit(panel._client_prompt_id, b"frame-bytes")
    desc = panel.in_flight_descriptor()
    assert desc["status"] == "running"       # a preview means our prompt is executing
    assert desc["frame"] == b"frame-bytes"


def test_in_flight_descriptor_clears_when_the_job_finishes(panel):
    _submit(panel)
    panel._client.job_completed.emit(panel._client_prompt_id, SDXL_HISTORY)
    assert panel.in_flight_descriptor() is None


def test_in_flight_descriptor_reports_a_tab_queued_behind_a_running_one(qtbot, tmp_path):
    from origenerator.job_queue import JobQueue
    client = ComfyUIClient()
    client.submit_job = lambda payload, prompt_id: prompt_id
    db = Database(tmp_path / "q.db")
    queue = JobQueue(db)
    running = GenerateConfigPanel(client, db, queue=queue)
    waiting = GenerateConfigPanel(client, db, queue=queue)
    qtbot.addWidget(running)
    qtbot.addWidget(waiting)
    running._param_form.set_values({"seed": 1})
    waiting._param_form.set_values({"seed": 2})

    _submit(running)   # takes the single slot and runs
    _submit(waiting)   # sits in the local queue behind it, no DB row yet

    desc = waiting.in_flight_descriptor()
    assert desc["status"] == "queued"
    # A waiting tab still has a card, keyed by its staged id, though it isn't yet a
    # live job (nothing to reconnect to) — so active_prompt_id stays None.
    assert desc["key"] and waiting.active_prompt_id() is None


# --- displaying a saved generation: the footer folded in from the inspect pane ---

def _image_row(db, prompt_id="img1", prompt="a cat", filename="sdxl_img1.png"):
    """A completed SDXL image whose output file an i2v can name as its source."""
    params = dict(WORKFLOW_REGISTRY["sdxl_t2i"].default_params(),
                  positive_prompt=prompt, seed=1)
    db.insert_generation(
        prompt_id=prompt_id, workflow_name="sdxl_t2i", workflow_version="v002",
        positive_prompt=prompt, seed=1,
        params_json=json.dumps(params), workflow_json="{}",
    )
    db.update_generation(prompt_id, status="completed",
                         output_files=json.dumps([{"filename": filename, "subfolder": "image"}]))
    return db.get_generation(prompt_id)


def _video_row(db, prompt_id="vid1", input_image=None):
    """A completed WAN i2v video, optionally built on a named source image."""
    params = {"positive_prompt": "dance", "seed": 5}
    if input_image is not None:
        params["input_image"] = input_image
    db.insert_generation(
        prompt_id=prompt_id, workflow_name="wan22_i2v", workflow_version="v002",
        positive_prompt="dance", seed=5,
        params_json=json.dumps(params), workflow_json="{}",
    )
    db.update_generation(prompt_id, status="completed",
                         output_files=json.dumps([{"filename": f"{prompt_id}.mp4", "subfolder": "video"}]))
    return db.get_generation(prompt_id)


@pytest.fixture
def saved_panel(qtbot, tmp_path):
    """A panel over a DB with an image and the video animated from it."""
    db = Database(tmp_path / "t.db")
    panel = GenerateConfigPanel(ComfyUIClient(), db)
    qtbot.addWidget(panel)
    panel._preview.show_media = MagicMock()  # don't start real WMF playback
    return panel, db


def test_a_fresh_tab_shows_no_footer(saved_panel):
    panel, _db = saved_panel
    assert panel._displayed_row is None
    assert panel._animated_strip.isHidden()
    assert panel._source_link.isHidden()
    assert panel._evolver_btn.isHidden()


def test_showing_an_image_lists_the_videos_it_was_animated_into(saved_panel, monkeypatch):
    panel, db = saved_panel
    image = _image_row(db, "img1", filename="sdxl_img1.png")
    _video_row(db, "vid1", input_image="sdxl_img1.png")
    monkeypatch.setattr(gcp_module, "animated_preview_path", lambda r, o, t: None)
    image_rows = [image]

    panel.show_saved_generation(image, image_rows)

    assert not panel._animated_strip.isHidden()
    assert len(panel._animated_strip.findChildren(_VideoTile)) == 1
    assert panel._source_link.isHidden()   # an image has no source-image link
    assert panel._evolver_btn.isHidden()   # Evolver is for videos
    assert panel._displayed_row is image


def test_showing_an_image_footer_tile_click_emits_animated_activated(saved_panel, monkeypatch):
    panel, db = saved_panel
    image = _image_row(db, "img1", filename="sdxl_img1.png")
    _video_row(db, "vid1", input_image="sdxl_img1.png")
    monkeypatch.setattr(gcp_module, "animated_preview_path", lambda r, o, t: None)
    panel.show_saved_generation(image, [image])
    got = []
    panel.animated_activated.connect(got.append)

    panel._animated_strip.video_activated.emit("vid1")

    assert got == ["vid1"]


def test_showing_a_video_reveals_evolver_and_source_link(saved_panel, monkeypatch):
    panel, db = saved_panel
    image = _image_row(db, "img1", filename="sdxl_img1.png")
    video = _video_row(db, "vid1", input_image="sdxl_img1.png")
    monkeypatch.setattr(gcp_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))

    panel.show_saved_generation(video, [image])

    assert not panel._evolver_btn.isHidden()   # a video with a file → sendable
    assert not panel._source_link.isHidden()   # its start frame is a known generation
    assert 'href="img1"' in panel._source_link.text()
    assert panel._animated_strip.isHidden()    # a video isn't animated into anything


def test_video_source_link_click_emits_source_activated(saved_panel, monkeypatch):
    panel, db = saved_panel
    image = _image_row(db, "img1", filename="sdxl_img1.png")
    video = _video_row(db, "vid1", input_image="sdxl_img1.png")
    monkeypatch.setattr(gcp_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))
    panel.show_saved_generation(video, [image])
    got = []
    panel.source_activated.connect(got.append)

    panel._source_link.linkActivated.emit("img1")

    assert got == ["img1"]


def test_video_without_a_known_source_hides_the_link(saved_panel, monkeypatch):
    panel, db = saved_panel
    video = _video_row(db, "vid1", input_image="hand_placed.png")  # not a generation
    monkeypatch.setattr(gcp_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))

    panel.show_saved_generation(video, [])

    assert panel._source_link.isHidden()
    assert not panel._evolver_btn.isHidden()  # still a sendable video


def _script_beside(video_path):
    from origenerator.funscript import (
        funscript_path_for, synthesize_actions, write_funscript,
    )
    actions = synthesize_actions(2.0, hz=1.0, loop=False)
    write_funscript(funscript_path_for(video_path), actions)
    return actions


def test_a_scripted_video_reveals_the_drive_osr2_button(saved_panel, monkeypatch, tmp_path):
    panel, db = saved_panel
    video = _video_row(db, "vid1", input_image="hand.png")
    vpath = tmp_path / "vid1.mp4"
    vpath.write_bytes(b"v")
    _script_beside(vpath)
    monkeypatch.setattr(gcp_module, "resolve_preview", lambda row, out: (vpath, "video"))

    panel.show_saved_generation(video, [])
    assert not panel._osr2_btn.isHidden()


def test_a_video_without_a_funscript_hides_the_drive_osr2_button(saved_panel, monkeypatch, tmp_path):
    panel, db = saved_panel
    video = _video_row(db, "vid1", input_image="hand.png")
    vpath = tmp_path / "vid1.mp4"
    vpath.write_bytes(b"v")  # no .funscript beside it
    monkeypatch.setattr(gcp_module, "resolve_preview", lambda row, out: (vpath, "video"))

    panel.show_saved_generation(video, [])
    assert panel._osr2_btn.isHidden()


def test_enabling_drive_osr2_emits_the_toggle_and_exposes_player_and_actions(
    saved_panel, monkeypatch, tmp_path
):
    panel, db = saved_panel
    video = _video_row(db, "vid1", input_image="hand.png")
    vpath = tmp_path / "vid1.mp4"
    vpath.write_bytes(b"v")
    actions = _script_beside(vpath)
    monkeypatch.setattr(gcp_module, "resolve_preview", lambda row, out: (vpath, "video"))
    panel.show_saved_generation(video, [])

    events = []
    panel.osr2_drive_toggled.connect(events.append)
    panel._osr2_btn.setChecked(True)

    assert events == [True]
    player, target_actions = panel.osr2_drive_target()
    assert player is panel._preview.player()
    assert target_actions == actions


def test_switching_away_from_a_driving_video_stops_the_drive(saved_panel, monkeypatch, tmp_path):
    panel, db = saved_panel
    video = _video_row(db, "vid1", input_image="hand.png")
    vpath = tmp_path / "vid1.mp4"
    vpath.write_bytes(b"v")
    _script_beside(vpath)
    monkeypatch.setattr(gcp_module, "resolve_preview", lambda row, out: (vpath, "video"))
    panel.show_saved_generation(video, [])
    panel._osr2_btn.setChecked(True)

    events = []
    panel.osr2_drive_toggled.connect(events.append)
    image = _image_row(db, "img1", filename="i.png")
    monkeypatch.setattr(gcp_module, "resolve_preview", lambda row, out: (Path("C:/i.png"), "image"))
    monkeypatch.setattr(gcp_module, "animated_preview_path", lambda r, o, t: None)
    panel.show_saved_generation(image, [image])

    assert events == [False]  # loading other media ended the drive
    assert panel._osr2_btn.isHidden()


def test_showing_a_video_seeds_the_form_with_its_params(saved_panel, monkeypatch):
    panel, db = saved_panel
    video = _video_row(db, "vid1", input_image="sdxl_img1.png")
    monkeypatch.setattr(gcp_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))

    panel.show_saved_generation(video, [])

    assert panel._workflow_combo.currentData() == "wan22_i2v"
    assert panel._param_form.get_values_static()["positive_prompt"] == "dance"


def test_showing_an_unregistered_generation_still_shows_preview_and_footer(saved_panel, monkeypatch):
    panel, db = saved_panel
    db.insert_generation(
        prompt_id="u1", workflow_name="unknown", workflow_version="imported",
        params_json=json.dumps({"steps": 20}), workflow_json="{}",
    )
    db.update_generation("u1", status="completed",
                         output_files=json.dumps([{"filename": "u1.mp4", "subfolder": "video"}]))
    row = db.get_generation("u1")
    before = panel._param_form.get_values_static()
    monkeypatch.setattr(gcp_module, "resolve_preview",
                        lambda r, out: (Path("C:/out/u1.mp4"), "video"))

    panel.show_saved_generation(row, [])

    assert panel._param_form.get_values_static() == before  # form left as-is
    assert not panel._evolver_btn.isHidden()                # footer still applies
    assert panel._displayed_row is row


def test_showing_a_saved_generation_shows_its_preview_over_the_autoshow(saved_panel, monkeypatch):
    # The form's recent-preview autoshow must not override the selection's output:
    # show_media's last call is the selection, not the folder's newest match.
    panel, db = saved_panel
    video = _video_row(db, "vid1")
    monkeypatch.setattr(gcp_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))

    panel.show_saved_generation(video, [])

    assert panel._preview.show_media.call_args.args == (Path("C:/out/vid1.mp4"), "video")


def test_send_to_evolver_copies_the_displayed_video(saved_panel, monkeypatch):
    panel, db = saved_panel
    video = _video_row(db, "vid1")
    video_path = Path("C:/out/vid1.mp4")
    monkeypatch.setattr(gcp_module, "resolve_preview", lambda row, out: (video_path, "video"))
    export = MagicMock(return_value=EVOLVER_INBOX_DIR / EVOLVER_SOURCE / "vid1.mp4")
    monkeypatch.setattr(evolver_export, "export_video", export)

    panel.show_saved_generation(video, [])
    panel._on_send_to_evolver()

    export.assert_called_once_with(video_path, EVOLVER_INBOX_DIR / EVOLVER_SOURCE)
    assert panel._displayed_row["evolver_exported_at"]
    assert panel._evolver_btn.text() == "Sent to Evolver ✓"
    assert panel._evolver_btn.isEnabled() is False


def test_send_to_evolver_does_not_re_export_an_already_sent_video(saved_panel, monkeypatch):
    panel, db = saved_panel
    video = _video_row(db, "vid1")
    db.mark_evolver_exported("vid1")
    video = db.get_generation("vid1")
    monkeypatch.setattr(gcp_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))
    export = MagicMock()
    monkeypatch.setattr(evolver_export, "export_video", export)

    panel.show_saved_generation(video, [])
    assert panel._evolver_btn.text() == "Sent to Evolver ✓"
    panel._on_send_to_evolver()

    export.assert_not_called()


def test_send_to_evolver_warns_and_survives_a_failed_copy(saved_panel, monkeypatch):
    panel, db = saved_panel
    video = _video_row(db, "vid1")
    monkeypatch.setattr(gcp_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))
    monkeypatch.setattr(evolver_export, "export_video",
                        MagicMock(side_effect=OSError("inbox unreachable")))
    warn = MagicMock()
    monkeypatch.setattr(gcp_module.QMessageBox, "warning", warn)

    panel.show_saved_generation(video, [])
    panel._on_send_to_evolver()  # must not raise

    warn.assert_called_once()


def test_generating_hides_a_previously_shown_footer(saved_panel, monkeypatch):
    panel, db = saved_panel
    video = _video_row(db, "vid1")
    monkeypatch.setattr(gcp_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))
    panel.show_saved_generation(video, [])
    assert not panel._evolver_btn.isHidden()
    panel._client.submit_job = MagicMock(return_value="x")

    # Switch to an image workflow that needs no input, then run a real generation.
    panel._workflow_combo.setCurrentIndex(_combo_index(panel, "sdxl_t2i"))
    panel._param_form.set_values({"seed": 999, "positive_prompt": "novel"})
    _submit(panel)

    assert panel._displayed_row is None
    assert panel._evolver_btn.isHidden()
    assert panel._source_link.isHidden()


def test_completion_makes_the_finished_row_the_displayed_one(saved_panel):
    panel, db = saved_panel
    panel._client.submit_job = MagicMock(return_value="x")
    panel._param_form.set_values({"seed": 7, "positive_prompt": "a fox"})
    _submit(panel)
    pid = panel._client_prompt_id

    panel._client.job_completed.emit(pid, SDXL_HISTORY)

    assert panel._displayed_row is not None
    assert panel._displayed_row["prompt_id"] == pid  # the just-finished run
