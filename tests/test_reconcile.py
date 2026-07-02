import json

from PIL import Image

from origenerator import gallery
from origenerator.db import Database
from origenerator.reconcile import reconcile_in_flight, reconcile_folder_meta

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


# --- folder-bookmark reconciliation -----------------------------------------

def _add_completed(db, pid, *, params, filename, workflow="sdxl_t2i"):
    db.insert_generation(prompt_id=pid, workflow_name=workflow, workflow_version="v",
                         params_json=json.dumps(params), workflow_json="{}")
    db.update_generation(
        pid, status="completed",
        output_files=json.dumps([{"filename": filename, "subfolder": ""}]),
    )
    return db.get_generation(pid)


def test_reconcile_repoints_a_star_orphaned_by_the_settings_formula_change(tmp_path):
    db = Database(tmp_path / "t.db")
    row = _add_completed(db, "p1", params={"positive_prompt": "a cat", "steps": 30, "seed": 1},
                         filename="sdxl_t2i_p1.png")
    legacy_key = gallery.legacy_settings_folder_key(row)
    current_key = gallery.settings_folder_key(row)
    assert legacy_key != current_key
    db.set_folder_starred(legacy_key, True)  # a star from before the formula change

    summary = reconcile_folder_meta(db)

    meta = db.folder_meta_map()
    assert meta.get(current_key, {}).get("starred") is True  # moved onto the live folder
    assert legacy_key not in meta                            # old key cleared
    assert summary["repointed"] == 1


def test_reconcile_backfills_identity_onto_a_matching_bookmark(tmp_path):
    db = Database(tmp_path / "t.db")
    row = _add_completed(db, "p1", params={"positive_prompt": "a cat", "steps": 30, "seed": 1},
                         filename="sdxl_t2i_p1.png")
    key = gallery.settings_folder_key(row)
    db.set_folder_starred(key, True)  # identity NULL

    summary = reconcile_folder_meta(db)

    (meta,) = [m for m in db.folder_meta_full() if m["folder_key"] == key]
    assert meta["level"] == "settings"
    assert meta["ref_prompt_id"] == "p1"  # now future-proof
    assert summary["refreshed"] == 1


def test_reconcile_remaps_a_future_key_change_via_stored_identity(tmp_path, monkeypatch):
    db = Database(tmp_path / "t.db")
    row = _add_completed(db, "p1", params={"positive_prompt": "a cat", "steps": 30, "seed": 1},
                         filename="sdxl_t2i_p1.png")
    key = gallery.settings_folder_key(row)
    # A bookmark already carrying identity, as a prior reconcile would leave it.
    db.upsert_folder_meta(key, custom_name=None, starred=True,
                          level="settings", ref_prompt_id="p1")

    # Simulate a *future* settings-key formula change: the folder's key shifts.
    original = gallery.settings_signature
    monkeypatch.setattr(gallery, "settings_signature", lambda wf, pj: original(wf, pj) + "X")
    new_key = gallery.settings_folder_key(row)
    assert new_key != key

    summary = reconcile_folder_meta(db)

    meta = db.folder_meta_map()
    assert meta.get(new_key, {}).get("starred") is True  # the star followed the folder
    assert key not in meta
    assert summary["repointed"] == 1


def test_reconcile_leaves_a_truly_orphaned_bookmark_untouched(tmp_path):
    db = Database(tmp_path / "t.db")
    _add_completed(db, "p1", params={"positive_prompt": "a cat", "steps": 30, "seed": 1},
                   filename="sdxl_t2i_p1.png")
    dead = "image/sdxl_t2i/000000000000"  # names no live folder, no recoverable identity
    db.set_folder_starred(dead, True)

    summary = reconcile_folder_meta(db)

    assert db.folder_meta_map()[dead]["starred"] is True  # a user's star is never dropped
    assert summary["orphaned"] == 1


def test_reconcile_merges_when_the_target_folder_is_already_bookmarked(tmp_path):
    db = Database(tmp_path / "t.db")
    row = _add_completed(db, "p1", params={"positive_prompt": "a cat", "steps": 30, "seed": 1},
                         filename="sdxl_t2i_p1.png")
    legacy_key = gallery.legacy_settings_folder_key(row)
    current_key = gallery.settings_folder_key(row)
    db.rename_folder(current_key, "Cats")    # the live folder already has a name
    db.set_folder_starred(legacy_key, True)  # a stale star to fold in

    reconcile_folder_meta(db)

    meta = db.folder_meta_map()[current_key]
    assert meta["starred"] is True        # star moved in
    assert meta["custom_name"] == "Cats"  # existing name preserved
    assert legacy_key not in db.folder_meta_map()


def test_reconcile_with_no_bookmarks_is_a_noop(tmp_path):
    db = Database(tmp_path / "t.db")
    _add_completed(db, "p1", params={"positive_prompt": "a cat", "steps": 30, "seed": 1},
                   filename="sdxl_t2i_p1.png")
    assert reconcile_folder_meta(db) == {"refreshed": 0, "repointed": 0, "orphaned": 0}
