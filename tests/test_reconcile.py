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
    # Patch where the tree builder looks the signature up (settings_folder_key and
    # build_gallery_tree both resolve it in gallery.tree), not the facade re-export.
    original = gallery.settings_signature
    monkeypatch.setattr(gallery.tree, "settings_signature",
                        lambda *a, **kw: original(*a, **kw) + "X")
    new_key = gallery.settings_folder_key(row)
    assert new_key != key

    summary = reconcile_folder_meta(db)

    meta = db.folder_meta_map()
    assert meta.get(new_key, {}).get("starred") is True  # the star followed the folder
    assert key not in meta
    assert summary["repointed"] == 1


def test_reconcile_repoints_an_i2v_star_across_the_frame_config_change(tmp_path):
    # A star made before an i2v's start-frame config was folded into its settings
    # key dangles once the formula changes. With no stored identity it is recovered
    # through the pre-frame-config legacy formula and moved onto the live folder —
    # so the user's bookmark survives this fix.
    db = Database(tmp_path / "t.db")
    _add_completed(db, "img", params={"positive_prompt": "a face", "steps": 30, "seed": 1},
                   filename="sdxl_t2i_img.png")
    video = _add_completed(
        db, "vid", workflow="wan22_i2v",
        params={"positive_prompt": "", "input_image": "sdxl_t2i_img.png", "seed": 2},
        filename="wan22_i2v_vid.mp4",
    )
    index = gallery.build_image_config_index([db.get_generation("img")])
    legacy_key = gallery.legacy_preframe_settings_folder_key(video)
    current_key = gallery.settings_folder_key(video, index)
    assert legacy_key != current_key                 # the fold moved the folder's key
    db.set_folder_starred(legacy_key, True)          # a star from before the fold

    summary = reconcile_folder_meta(db)

    meta = db.folder_meta_map()
    assert meta.get(current_key, {}).get("starred") is True  # moved onto the live folder
    assert legacy_key not in meta                             # old key cleared
    assert summary["repointed"] == 1


def test_reconcile_repoints_a_star_across_the_version_fold(tmp_path):
    # A star made before the workflow generation was folded into the settings
    # key dangles once the formula changes. With no stored identity it is
    # recovered through the pre-version legacy formula and moved onto the live
    # folder — so a bookmark made just before this fix survives it.
    db = Database(tmp_path / "t.db")
    row = _add_completed(db, "p1", params={"positive_prompt": "a cat", "steps": 30, "seed": 1},
                         filename="sdxl_t2i_p1.png")
    legacy_key = gallery.legacy_preversion_settings_folder_key(row)
    current_key = gallery.settings_folder_key(row)
    assert legacy_key != current_key                 # the fold moved the folder's key
    db.set_folder_starred(legacy_key, True)          # a star from before the fold

    summary = reconcile_folder_meta(db)

    meta = db.folder_meta_map()
    assert meta.get(current_key, {}).get("starred") is True  # moved onto the live folder
    assert legacy_key not in meta                             # old key cleared
    assert summary["repointed"] == 1


def test_reconcile_repoints_both_stars_across_the_enhancement_merge(tmp_path):
    # The enhancement split is the one formula change that MERGED folders: an
    # enhanced render and its unenhanced twin used to be two, and are now one. A
    # star on either of the old folders has to land on the merged one — including
    # the enhanced side, whose row may not be the member the legacy key is
    # recomputed from.
    db = Database(tmp_path / "t.db")
    plain = _add_completed(db, "p1", params={"positive_prompt": "a cat", "steps": 30,
                                             "seed": 1, "enhance": False},
                           filename="sdxl_t2i_p1.png")
    enhanced = _add_completed(db, "p2", params={"positive_prompt": "a cat", "steps": 30,
                                                "seed": 2, "enhance": True},
                              filename="sdxl_t2i_p2.png")
    current_key = gallery.settings_folder_key(plain)
    assert gallery.settings_folder_key(enhanced) == current_key  # one folder now
    plain_key, enhanced_key = (
        gallery.legacy_preenhance_settings_folder_keys([row]).pop()
        for row in (plain, enhanced)
    )
    assert plain_key != enhanced_key != current_key  # two folders before
    db.set_folder_starred(plain_key, True)
    db.rename_folder(enhanced_key, "Cats")

    summary = reconcile_folder_meta(db)

    meta = db.folder_meta_map()
    assert meta.get(current_key, {}).get("starred") is True    # the star came along
    assert meta[current_key]["custom_name"] == "Cats"          # so did the name
    assert plain_key not in meta and enhanced_key not in meta  # both old keys cleared
    assert summary["repointed"] == 2


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
