import json
from unittest.mock import MagicMock

import pytest

from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gui.generate_config_panel import GenerateConfigPanel

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
    assert "image" in panel._status_label.text().lower()
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
