import json
from unittest.mock import MagicMock

import pytest

from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.generation_config import ConfigSnapshot
from origenerator.gui.generate_config_panel import GenerateConfigPanel
from origenerator.workflows import WORKFLOW_REGISTRY

SDXL_HISTORY = {"outputs": {"7": {"images": [{"filename": "a.png", "subfolder": ""}]}}}


@pytest.fixture
def panel(qtbot, tmp_path):
    client = ComfyUIClient()
    client.submit_job = lambda payload: "comfy-A"
    db = Database(tmp_path / "test.db")
    p = GenerateConfigPanel(client, db)
    qtbot.addWidget(p)
    return p


def _combo_index(panel, key):
    for i in range(panel._workflow_combo.count()):
        if panel._workflow_combo.itemData(i) == key:
            return i
    raise AssertionError(f"workflow {key} not in combo")


def test_generate_inserts_row_and_submits(panel):
    panel._on_generate()
    rows = panel._db.list_generations()
    assert len(rows) == 1
    assert rows[0]["workflow_name"] == "sdxl_t2i"
    assert rows[0]["status"] == "running"
    assert panel._client_prompt_id == rows[0]["prompt_id"]
    assert panel._comfy_prompt_id == "comfy-A"


def test_completion_only_handled_for_own_prompt_id(panel):
    completed = []
    panel.generation_completed.connect(completed.append)
    panel._on_generate()
    our_id = panel._client_prompt_id

    # A sibling panel's job completing must not touch this panel.
    panel._client.job_completed.emit("comfy-OTHER", SDXL_HISTORY)
    assert panel._db.get_generation(our_id)["status"] == "running"
    assert panel._generate_btn.isEnabled() is False
    assert completed == []

    # Our own job's completion is handled.
    panel._client.job_completed.emit("comfy-A", SDXL_HISTORY)
    row = panel._db.get_generation(our_id)
    assert row["status"] == "completed"
    assert "a.png" in row["output_files"]
    assert panel._generate_btn.isEnabled() is True
    assert completed == [our_id]


def test_progress_only_moves_for_own_prompt_id(panel):
    panel._on_generate()
    panel._client.progress.emit("comfy-OTHER", 5, 10)
    assert panel._progress.value() == 0
    panel._client.progress.emit("comfy-A", 5, 10)
    assert panel._progress.value() == 5


def test_error_marks_row_for_own_id_only(panel):
    panel._on_generate()
    our_id = panel._client_prompt_id

    panel._client.job_error.emit("comfy-OTHER", "boom")
    assert panel._db.get_generation(our_id)["status"] == "running"

    panel._client.job_error.emit("comfy-A", "boom")
    assert panel._db.get_generation(our_id)["status"] == "error"
    assert panel._generate_btn.isEnabled() is True


def test_completion_uses_workflow_captured_at_submit(panel):
    panel._on_generate()  # submitted with the default workflow, sdxl_t2i
    our_id = panel._client_prompt_id
    # User switches the workflow combo while the job is still running.
    panel._workflow_combo.setCurrentIndex(_combo_index(panel, "wan22_i2v"))
    panel._client.job_completed.emit("comfy-A", SDXL_HISTORY)
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
    panel._client.job_completed.emit("comfy-A", SDXL_HISTORY)
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


class SpyDB:
    """Records the calls a panel makes, returning canned recent durations."""

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
    panel._comfy_prompt_id = "comfyui-xyz"
    panel._submitted_workflow = WORKFLOW_REGISTRY["sdxl_t2i"]

    panel._on_completed("comfyui-xyz", _history_with_duration(15.26))

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
    panel._comfy_prompt_id = "comfyui-xyz"
    panel._submitted_workflow = WORKFLOW_REGISTRY["sdxl_t2i"]

    panel._on_completed("comfyui-xyz", _history_with_duration(905))

    assert panel._progress.format() == "Done in 15 min 5 sec"


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

    def submit(self, panel, workflow_name):
        self.submitted.append((panel, workflow_name))

    def release(self, panel):
        self.released.append(panel)


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
    panel._on_completed("comfy-A", SDXL_HISTORY)
    assert queue.released == [panel]


def test_set_queue_status_shows_position_and_eta(panel):
    panel.set_queue_status(2, 905.0)
    text = panel._progress.format()
    assert "#2" in text and "15 min" in text


def test_completion_colors_the_bar_done(panel):
    panel._client_prompt_id = "p1"
    panel._comfy_prompt_id = "comfy-A"
    panel._submitted_workflow = WORKFLOW_REGISTRY["sdxl_t2i"]
    panel._on_completed("comfy-A", SDXL_HISTORY)
    assert panel._progress.property("barState") == "done"


def test_error_colors_the_bar_red(panel):
    panel._client_prompt_id = "p1"
    panel._comfy_prompt_id = "comfy-A"
    panel._submitted_workflow = WORKFLOW_REGISTRY["sdxl_t2i"]
    panel._on_error("comfy-A", "boom")
    assert panel._progress.property("barState") == "error"


def test_queue_status_colors_the_bar_grey(panel):
    panel.set_queue_status(1, 0)
    assert panel._progress.property("barState") == "queued"


def test_completion_records_generated_id(panel):
    panel._client_prompt_id = "p1"
    panel._comfy_prompt_id = "comfy-A"
    panel._submitted_workflow = WORKFLOW_REGISTRY["sdxl_t2i"]
    panel._on_completed("comfy-A", SDXL_HISTORY)
    assert panel.generated_ids() == ["p1"]


# ---- generic captured-graph replay ----

def test_submit_replay_patches_graph_and_submits(panel):
    sent = {}
    panel._client.submit_job = lambda payload: (sent.update(payload), "comfy-R")[1]
    graph = {
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"},
              "_meta": {"title": "Positive"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "oldneg"},
              "_meta": {"title": "Negative"}},
        "4": {"class_type": "KSampler", "inputs": {"seed": 1}},
    }
    row = {"workflow_name": "hunyuan_t2v", "workflow_version": "imported",
           "workflow_json": json.dumps(graph), "params_json": "{}",
           "positive_prompt": "old", "negative_prompt": "oldneg", "seed": 1}

    panel.submit_replay(row, {"positive": "new pos", "negative": "new neg",
                              "seed": 999, "input_image": None})

    assert sent["2"]["inputs"]["text"] == "new pos"
    assert sent["3"]["inputs"]["text"] == "new neg"
    assert sent["4"]["inputs"]["seed"] == 999
    rows = panel._db.list_generations()
    assert len(rows) == 1
    assert rows[0]["workflow_name"] == "hunyuan_t2v"
    assert rows[0]["status"] == "running"
    assert panel._submitted_workflow is None   # routes completion through generic path


def test_submit_replay_blocks_on_missing_source(panel):
    graph = {"1": {"class_type": "LoadImage",
                   "inputs": {"image": "definitely_absent_zzz.png"}}}
    row = {"workflow_name": "x", "workflow_version": "imported",
           "workflow_json": json.dumps(graph), "params_json": "{}"}
    called = []
    panel._client.submit_job = lambda payload: called.append(payload) or "c"

    panel.submit_replay(row, {"positive": "p", "negative": "",
                              "seed": None, "input_image": None})

    assert called == []
    assert "missing" in panel._progress.format().lower()
    assert panel._db.list_generations() == []


def test_replay_completion_uses_generic_extractor(panel):
    panel._db.insert_generation(
        prompt_id="p1", workflow_name="x", workflow_version="replay",
        params_json="{}", workflow_json="{}",
    )
    panel._db.update_generation("p1", status="running")
    panel._client_prompt_id = "p1"
    panel._comfy_prompt_id = "comfy-R"
    panel._submitted_workflow = None  # replay: no captured template

    # VHS_VideoCombine reports under "gifs"; the generic extractor must find it.
    history = {"outputs": {"9": {"gifs": [{"filename": "out.mp4", "subfolder": "video"}]}}}
    panel._client.job_completed.emit("comfy-R", history)

    row = panel._db.get_generation("p1")
    assert row["status"] == "completed"
    assert "out.mp4" in row["output_files"]
