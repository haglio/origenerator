from unittest.mock import MagicMock

from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gui.generate_view import GenerateView


def _select_workflow(view, name):
    combo = view._workflow_combo
    for i in range(combo.count()):
        if combo.itemData(i) == name:
            combo.setCurrentIndex(i)
            return
    raise AssertionError(f"workflow {name!r} not offered")


def test_generate_blocks_when_input_image_missing(qtbot, tmp_path):
    client = MagicMock()
    view = GenerateView(client, Database(tmp_path / "t.db"))
    qtbot.addWidget(view)

    _select_workflow(view, "wan22_i2v")  # leaves Input Image blank
    view._on_generate()

    client.submit_job.assert_not_called()
    assert "image" in view._status_label.text().lower()
    assert view._db.list_generations() == []  # nothing recorded


def test_generate_submits_when_input_image_present(qtbot, tmp_path):
    client = MagicMock()
    client.submit_job.return_value = "comfy-prompt-id"
    view = GenerateView(client, Database(tmp_path / "t.db"))
    qtbot.addWidget(view)

    _select_workflow(view, "wan22_i2v")
    view._param_form.set_values({"input_image": "start.png"})
    view._on_generate()

    client.submit_job.assert_called_once()


class SpyDB:
    """Records the calls GenerateView makes, returning canned durations."""

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


def _view(qtbot, db):
    view = GenerateView(ComfyUIClient(), db)
    qtbot.addWidget(view)
    return view


def test_on_completed_records_execution_duration(qtbot):
    db = SpyDB()
    view = _view(qtbot, db)
    view._current_prompt_id = "p1"

    view._on_completed("comfyui-xyz", _history_with_duration(15.26))

    prompt_id, fields = db.updates[-1]
    assert prompt_id == "p1"
    assert fields["status"] == "completed"
    assert fields["duration_seconds"] == 15.26


def test_estimate_label_reflects_recent_durations(qtbot):
    db = SpyDB(durations=[700.0, 724.0, 800.0])
    view = _view(qtbot, db)
    assert view._estimate_label.text() == "Typical time: ~12 min (based on 3 runs)"


def test_estimate_label_when_no_history(qtbot):
    db = SpyDB(durations=[])
    view = _view(qtbot, db)
    assert view._estimate_label.text() == "Typical time: No timing data yet"


def test_on_completed_status_shows_actual_time(qtbot):
    db = SpyDB()
    view = _view(qtbot, db)
    view._current_prompt_id = "p1"

    view._on_completed("comfyui-xyz", _history_with_duration(905))

    assert view._status_label.text() == "Done in 15 min 5 sec"
