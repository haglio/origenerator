import json

from PIL import Image

from origenerator.db import Database
from origenerator.reconcile import reconcile_in_flight

# sdxl_t2i saves under output node "7".
SDXL_HISTORY = {"outputs": {"7": {"images": [{"filename": "a.png", "subfolder": ""}]}}}


class FakeComfy:
    """Stands in for ComfyUIClient's HTTP surface during reconciliation."""

    def __init__(self, queue=(), histories=None, queue_error=False):
        self._queue = set(queue)
        self._histories = histories or {}
        self._queue_error = queue_error

    def fetch_queue(self):
        if self._queue_error:
            raise ConnectionError("comfyui down")
        return set(self._queue)

    def fetch_history(self, prompt_id):
        return self._histories.get(prompt_id, {})


def _insert_in_flight(db, prompt_id, *, workflow="sdxl_t2i", status="running"):
    db.insert_generation(
        prompt_id=prompt_id, workflow_name=workflow, workflow_version="v",
        params_json="{}", workflow_json="{}",
    )
    db.update_generation(prompt_id, status=status)


def test_finished_row_is_finalized_from_history(tmp_path):
    db = Database(tmp_path / "t.db")
    _insert_in_flight(db, "p1")
    out = tmp_path / "out"
    out.mkdir()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(out / "a.png")

    summary = reconcile_in_flight(db, FakeComfy(histories={"p1": SDXL_HISTORY}),
                                  out, tmp_path / "thumbs")

    row = db.get_generation("p1")
    assert row["status"] == "completed"
    assert "a.png" in row["output_files"]
    assert row["thumbnail_path"]  # rendered from the on-disk output
    assert summary["finalized"] == 1


def test_still_queued_row_is_left_running(tmp_path):
    db = Database(tmp_path / "t.db")
    _insert_in_flight(db, "p1")

    summary = reconcile_in_flight(db, FakeComfy(queue={"p1"}), tmp_path, tmp_path / "thumbs")

    assert db.get_generation("p1")["status"] == "running"
    assert summary["running"] == 1


def test_pending_row_still_queued_is_left(tmp_path):
    db = Database(tmp_path / "t.db")
    _insert_in_flight(db, "p1", status="pending")  # pending counts as in flight

    reconcile_in_flight(db, FakeComfy(queue={"p1"}), tmp_path, tmp_path / "thumbs")

    assert db.get_generation("p1") is not None


def test_gone_row_is_cleared(tmp_path):
    db = Database(tmp_path / "t.db")
    _insert_in_flight(db, "p1")  # not in the queue, not in history

    summary = reconcile_in_flight(db, FakeComfy(), tmp_path, tmp_path / "thumbs")

    assert db.get_generation("p1") is None  # any file it wrote is caught by the importer
    assert summary["cleared"] == 1


def test_completed_rows_are_untouched(tmp_path):
    db = Database(tmp_path / "t.db")
    _insert_in_flight(db, "done", status="completed")
    _insert_in_flight(db, "gone")  # an in-flight row so the reconcile loop runs

    reconcile_in_flight(db, FakeComfy(), tmp_path, tmp_path / "thumbs")

    assert db.get_generation("done") is not None  # not an in-flight row: never considered


def test_server_unreachable_leaves_rows_intact(tmp_path):
    db = Database(tmp_path / "t.db")
    _insert_in_flight(db, "p1")

    summary = reconcile_in_flight(db, FakeComfy(queue_error=True), tmp_path, tmp_path / "thumbs")

    # A server we can't read is not evidence the job is gone — don't clear it.
    assert db.get_generation("p1")["status"] == "running"
    assert summary["running"] == 1


def test_no_in_flight_rows_is_a_noop(tmp_path):
    db = Database(tmp_path / "t.db")
    _insert_in_flight(db, "done", status="completed")

    summary = reconcile_in_flight(db, FakeComfy(), tmp_path, tmp_path / "thumbs")

    assert summary == {"finalized": 0, "running": 0, "cleared": 0}
