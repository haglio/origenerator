from __future__ import annotations

from origenerator.db import Database
from origenerator.generation_state import GenerationSource
from origenerator.inflight import drop_in_flight


class FakeComfy:
    def __init__(self, refuses=()):
        self.cancelled, self.interrupted = [], []
        self._refuses = set(refuses)

    def cancel_prompt(self, prompt_id):
        if prompt_id in self._refuses:
            raise ConnectionError("comfyui down")
        self.cancelled.append(prompt_id)

    def interrupt(self, prompt_id):
        self.interrupted.append(prompt_id)


def _row(db, prompt_id, *, source=GenerationSource.BACKFILL, status="running"):
    db.insert_generation(prompt_id=prompt_id, workflow_name="sdxl_t2i", workflow_version="v",
                         params_json="{}", workflow_json="{}", source=source)
    db.update_generation(prompt_id, status=status)


def test_every_unfinished_row_of_the_source_is_dequeued_and_stopped_by_name_and_deleted(tmp_path):
    db = Database(tmp_path / "t.db")
    _row(db, "p1")
    _row(db, "p2", status="pending")
    client = FakeComfy()

    dropped = drop_in_flight(db, client, GenerationSource.BACKFILL, "backfill run")

    assert (dropped, sorted(client.cancelled), sorted(client.interrupted)) == (2, ["p1", "p2"], ["p1", "p2"])
    assert db.get_generation("p1") is None and db.get_generation("p2") is None


def test_a_row_the_server_would_not_let_go_of_is_kept(tmp_path):
    db = Database(tmp_path / "t.db")
    _row(db, "p1")
    _row(db, "p2")

    dropped = drop_in_flight(db, FakeComfy(refuses={"p1"}), GenerationSource.BACKFILL, "backfill run")

    assert dropped == 1
    assert db.get_generation("p1")["status"] == "running"
    assert db.get_generation("p2") is None


def test_finished_rows_and_rows_of_another_source_are_untouched(tmp_path):
    db = Database(tmp_path / "t.db")
    _row(db, "done", status="completed")
    _row(db, "other", source=GenerationSource.GENERATED)
    client = FakeComfy()

    dropped = drop_in_flight(db, client, GenerationSource.BACKFILL, "backfill run")

    assert (dropped, client.cancelled) == (0, [])
    assert db.get_generation("done") is not None and db.get_generation("other") is not None
