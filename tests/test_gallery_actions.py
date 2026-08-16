import json
from pathlib import Path

from origenerator.branch_session import ENV_FLAG, session_trash
from origenerator.db import Database
from origenerator.gallery_actions import GalleryActions


def _completed_row(db, output_dir, pid, filename, *, subfolder="", thumb_dir=None):
    """Insert a completed generation with its output (and thumbnail) on disk."""
    db.insert_generation(
        prompt_id=pid, workflow_name="sdxl_t2i", workflow_version="v002",
        params_json="{}", workflow_json="{}",
    )
    file_path = output_dir / subfolder / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(b"data")

    thumb_path = None
    if thumb_dir is not None:
        thumb_dir.mkdir(parents=True, exist_ok=True)
        thumb_path = thumb_dir / f"{pid}.jpg"
        thumb_path.write_bytes(b"thumb")

    db.update_generation(
        pid, status="completed",
        output_files=json.dumps([{"filename": filename, "subfolder": subfolder}]),
        thumbnail_path=str(thumb_path) if thumb_path else None,
    )
    return db.get_generation(pid)


def _actions(tmp_path, limit=50, release_files=None):
    db = Database(tmp_path / "test.db")
    output_dir = tmp_path / "output"
    # Composed the way the gallery composes it, so which trash a session may use
    # is part of what these tests exercise.
    trash = session_trash(tmp_path / "trash")
    return GalleryActions(db, output_dir, trash, limit=limit,
                          release_files=release_files), db, output_dir


def test_delete_removes_the_row_and_its_file(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    row = _completed_row(db, output_dir, "p1", "a.png")
    file_path = output_dir / "a.png"

    actions.delete_rows([row])

    assert db.get_generation("p1") is None
    assert not file_path.exists()
    assert actions.can_undo()


def test_undo_restores_the_row_and_its_file(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    row = _completed_row(db, output_dir, "p1", "a.png")
    file_path = output_dir / "a.png"
    actions.delete_rows([row])

    actions.undo()

    restored = db.get_generation("p1")
    assert restored == row  # whole row back, verbatim
    assert file_path.exists() and file_path.read_bytes() == b"data"
    assert not actions.can_undo()


def test_undo_of_a_delete_returns_a_restored_prompt_id(tmp_path):
    # The view uses it to navigate back to the folder the delete emptied.
    actions, db, output_dir = _actions(tmp_path)
    row = _completed_row(db, output_dir, "p1", "a.png")
    actions.delete_rows([row])
    assert actions.undo() == "p1"


def test_undo_of_a_rename_returns_no_focus(tmp_path):
    actions, _db, _out = _actions(tmp_path)
    actions.rename_folder("media/wf/deadbeef", "My Folder")
    assert actions.undo() is None


def test_undo_with_nothing_to_undo_returns_none(tmp_path):
    actions, _db, _out = _actions(tmp_path)
    assert actions.undo() is None


def test_delete_also_takes_the_video_metadata_sidecar(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    row = _completed_row(db, output_dir, "v1", "clip.mp4", subfolder="video")
    sidecar = output_dir / "video" / "clip.png"
    sidecar.write_bytes(b"png")

    actions.delete_rows([row])
    assert not (output_dir / "video" / "clip.mp4").exists()
    assert not sidecar.exists()

    actions.undo()
    assert (output_dir / "video" / "clip.mp4").exists()
    assert sidecar.exists()


def test_delete_trashes_the_thumbnail_and_undo_brings_it_back(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    thumb_dir = tmp_path / "thumbs"
    row = _completed_row(db, output_dir, "p1", "a.png", thumb_dir=thumb_dir)
    thumb = thumb_dir / "p1.jpg"

    actions.delete_rows([row])
    assert not thumb.exists()

    actions.undo()
    assert thumb.exists() and thumb.read_bytes() == b"thumb"


def test_delete_of_a_pending_row_without_files_is_still_undoable(tmp_path):
    actions, db, _ = _actions(tmp_path)
    db.insert_generation(
        prompt_id="pend", workflow_name="sdxl_t2i", workflow_version="v002",
        params_json="{}", workflow_json="{}",
    )
    row = db.get_generation("pend")

    actions.delete_rows([row])
    assert db.get_generation("pend") is None

    actions.undo()
    assert db.get_generation("pend") == row


def test_deleting_many_rows_undoes_as_one_step(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    rows = [
        _completed_row(db, output_dir, "p1", "a.png"),
        _completed_row(db, output_dir, "p2", "b.png"),
    ]
    actions.delete_rows(rows)
    assert db.get_generation("p1") is None and db.get_generation("p2") is None

    actions.undo()  # a single undo brings the whole batch back
    assert db.get_generation("p1") is not None
    assert db.get_generation("p2") is not None
    assert not actions.can_undo()


def test_rename_folder_is_undoable_back_to_the_previous_name(tmp_path):
    actions, db, _ = _actions(tmp_path)
    db.rename_folder("image/sdxl_t2i", "First Name")

    actions.rename_folder("image/sdxl_t2i", "Second Name")
    assert db.folder_meta_map()["image/sdxl_t2i"]["custom_name"] == "Second Name"

    actions.undo()
    assert db.folder_meta_map()["image/sdxl_t2i"]["custom_name"] == "First Name"


def test_undo_label_describes_the_most_recent_action(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    assert actions.undo_label() is None

    actions.rename_folder("image/sdxl_t2i", "Name")
    assert "rename" in actions.undo_label().lower()

    rows = [_completed_row(db, output_dir, "p1", "a.png"),
            _completed_row(db, output_dir, "p2", "b.png")]
    actions.delete_rows(rows)
    assert "2" in actions.undo_label()


def test_eviction_past_the_limit_leaves_the_oldest_in_the_bin(tmp_path):
    actions, db, output_dir = _actions(tmp_path, limit=1)
    first = _completed_row(db, output_dir, "p1", "a.png")
    second = _completed_row(db, output_dir, "p2", "b.png")

    actions.delete_rows([first])   # batch 1 on the stack
    actions.delete_rows([second])  # pushes batch 1 off the (size-1) stack

    # Only the newest deletion is still undoable...
    assert actions.undo_label() is not None
    actions.undo()
    assert db.get_generation("p2") is not None
    assert db.get_generation("p1") is None
    assert not actions.can_undo()
    # ...but falling off the stack no longer ends anything: the evicted delete is
    # held in the bin, files and all, and is restorable from the Trash shelf.
    assert [r["prompt_id"] for r in db.list_deletions()] == ["p1"]
    actions.restore_deleted(["p1"])
    assert db.get_generation("p1") == first
    assert (output_dir / "a.png").read_bytes() == b"data"


def test_a_delete_is_held_in_the_bin_with_the_row_it_dropped(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    row = _completed_row(db, output_dir, "p1", "a.png", thumb_dir=tmp_path / "thumbs")

    actions.delete_rows([row])

    (held,) = db.list_deletions()
    assert held["prompt_id"] == "p1"
    assert held["row"] == row              # the whole row, ready to be put back
    assert held["deleted_at"]              # stamped, so it can age out
    # And the batch says where each file went, so a later session can move it back.
    moved = dict(held["batch"]["moves"])
    assert set(moved) == {str(output_dir / "a.png"), str(tmp_path / "thumbs" / "p1.jpg")}
    assert all(Path(dest).exists() for dest in moved.values())


def test_undoing_a_delete_takes_it_back_out_of_the_bin(tmp_path):
    # Otherwise the Trash shelf would go on offering to restore an item that is
    # already back in the gallery.
    actions, db, output_dir = _actions(tmp_path)
    row = _completed_row(db, output_dir, "p1", "a.png")
    actions.delete_rows([row])

    actions.undo()

    assert db.list_deletions() == []


def test_each_deleted_item_is_held_on_its_own(tmp_path):
    # A folder's delete is one undo step but many bin entries, so one item can be
    # brought back weeks later without dragging the rest of the folder with it.
    actions, db, output_dir = _actions(tmp_path)
    rows = [_completed_row(db, output_dir, "p1", "a.png"),
            _completed_row(db, output_dir, "p2", "b.png")]
    actions.delete_rows(rows)

    actions.restore_deleted(["p2"])

    assert db.get_generation("p2") is not None
    assert (output_dir / "b.png").exists()
    assert db.get_generation("p1") is None            # its neighbor stays deleted...
    assert [r["prompt_id"] for r in db.list_deletions()] == ["p1"]  # ...and held


def test_restoring_returns_the_row_and_the_files_and_clears_the_record(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    thumb_dir = tmp_path / "thumbs"
    row = _completed_row(db, output_dir, "p1", "a.png", thumb_dir=thumb_dir)
    actions.delete_rows([row])

    assert actions.restore_deleted(["p1"]) == "p1"  # the item to navigate back to

    assert db.get_generation("p1") == row  # whole row back, verbatim
    assert (output_dir / "a.png").read_bytes() == b"data"
    assert (thumb_dir / "p1.jpg").read_bytes() == b"thumb"
    assert db.list_deletions() == []


def test_purging_ends_the_files_and_the_record_for_good(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    row = _completed_row(db, output_dir, "p1", "a.png")
    actions.delete_rows([row])
    (held,) = db.list_deletions()
    trashed = Path(held["batch"]["moves"][0][1])
    assert trashed.exists()

    actions.purge_deleted(["p1"])

    assert not trashed.exists()
    assert not (output_dir / "a.png").exists()  # purge is not restore
    assert db.list_deletions() == []
    assert db.get_generation("p1") is None


def test_restoring_or_purging_an_item_the_bin_no_longer_holds_is_a_noop(tmp_path):
    actions, db, _ = _actions(tmp_path)
    assert actions.restore_deleted(["never-deleted"]) is None
    actions.purge_deleted(["never-deleted"])  # must not raise


def test_reject_experiment_trashes_files_but_keeps_the_learning_row(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    row = _completed_row(db, output_dir, "e1", "exp.png",
                         thumb_dir=tmp_path / "thumbs")
    file_path = output_dir / "exp.png"
    thumb_path = tmp_path / "thumbs" / "e1.jpg"

    actions.reject_experiment(row)

    kept = db.get_generation("e1")
    assert kept is not None                      # the row survives...
    assert kept["experiment_verdict"] == "down"  # ...carrying the verdict to learn from
    assert kept["output_files"] is None and kept["thumbnail_path"] is None
    assert not file_path.exists() and not thumb_path.exists()  # the junk is gone
    assert actions.can_undo() and actions.undo_label() == "Reject experiment"


def test_delete_has_the_app_let_go_of_the_files_before_moving_them(tmp_path):
    # Windows refuses to move a file the app itself still holds open — a video
    # being previewed keeps its file open — so every doomed path is handed over
    # to be released first, while it's still where the app is showing it.
    seen = []
    actions, db, output_dir = _actions(
        tmp_path,
        release_files=lambda paths: seen.append([(p, p.exists()) for p in paths]),
    )
    row = _completed_row(db, output_dir, "v1", "clip.mp4", subfolder="video",
                         thumb_dir=tmp_path / "thumbs")

    actions.delete_rows([row])

    assert seen == [[(output_dir / "video" / "clip.mp4", True),
                     (tmp_path / "thumbs" / "v1.jpg", True)]]


def test_rejecting_an_experiment_releases_its_files_too(tmp_path):
    # The Experiments shelf's reject trashes files like any delete, so it needs
    # the same release — the shelf is where an item is most likely on screen.
    seen = []
    actions, db, output_dir = _actions(tmp_path, release_files=seen.extend)
    row = _completed_row(db, output_dir, "e1", "exp.mp4", subfolder="video")

    actions.reject_experiment(row)

    assert seen == [output_dir / "video" / "exp.mp4"]


def test_a_branch_session_deletes_no_files(tmp_path, monkeypatch):
    # A preview's database is a copy of the live install's, so its rows point at
    # the live library; and what a preview generates itself the live app adopts
    # at its next launch. Either way the file is not the preview's to destroy —
    # deleting there forgets the row in the copy and leaves the file alone.
    # Moving it is how the live app ended up showing rows with nothing behind
    # them, and how a rejected experiment kept coming back for review.
    monkeypatch.setenv(ENV_FLAG, "1")
    actions, db, output_dir = _actions(tmp_path)
    row = _completed_row(db, output_dir, "p1", "a.png", thumb_dir=tmp_path / "thumbs")

    actions.delete_rows([row])

    assert db.get_generation("p1") is None            # off the preview's own shelf
    assert (output_dir / "a.png").exists()            # the live install's file stays
    assert (tmp_path / "thumbs" / "p1.jpg").exists()  # and the thumbnail it shows


def test_rejecting_an_experiment_files_nothing_in_the_bin(tmp_path):
    # The bin holds deleted rows so they can be put back; a rejection keeps its
    # row (verdict and all), so there is no orphan for the Trash shelf to offer.
    actions, db, output_dir = _actions(tmp_path)
    row = _completed_row(db, output_dir, "e1", "exp.png")

    actions.reject_experiment(row)

    assert db.list_deletions() == []


def test_undoing_a_rejection_returns_the_experiment_to_review(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    row = _completed_row(db, output_dir, "e1", "exp.png",
                         thumb_dir=tmp_path / "thumbs")
    actions.reject_experiment(row)

    actions.undo()

    restored = db.get_generation("e1")
    assert restored["experiment_verdict"] is None       # unreviewed again
    assert restored["output_files"] == row["output_files"]
    assert restored["thumbnail_path"] == row["thumbnail_path"]
    assert (output_dir / "exp.png").exists()
    assert (tmp_path / "thumbs" / "e1.jpg").exists()


# --- deleting some of one image's versions ---------------------------------

def _enhanced_row(db, output_dir, pid="p1"):
    """An image enhanced once: the enhanced file leads, the original stays."""
    row = _completed_row(db, output_dir, pid, "base.png", subfolder="image")
    (output_dir / "image" / "enhanced.png").write_bytes(b"better")
    db.update_generation(
        pid,
        output_files=json.dumps([
            {"filename": "enhanced.png", "subfolder": "image"},
            {"filename": "base.png", "subfolder": "image"},
        ]),
        original_files=json.dumps([{"filename": "base.png", "subfolder": "image"}]),
        enhance_history=json.dumps([
            {"filename": "enhanced.png", "params": {"enhance_scale": 2.0}},
        ]),
    )
    return db.get_generation(pid)


def test_deleting_a_version_keeps_the_generation(tmp_path):
    # A level is a file, not a generation: the image stays where it is, in its
    # folder, with the versions that weren't picked.
    actions, db, output_dir = _actions(tmp_path)
    row = _enhanced_row(db, output_dir)

    assert actions.delete_enhance_levels(row, ["enhanced.png"]) is True

    updated = db.get_generation("p1")
    assert updated is not None
    assert not (output_dir / "image" / "enhanced.png").exists()
    assert (output_dir / "image" / "base.png").exists()
    assert json.loads(updated["output_files"]) == [
        {"filename": "base.png", "subfolder": "image"}
    ]


def test_deleting_the_last_enhancement_leaves_a_plain_image(tmp_path):
    # With nothing enhanced left, the bookkeeping goes too — otherwise the one
    # remaining file would read as an enhancement of itself.
    from origenerator.gallery import enhance_levels, is_enhanced_row

    actions, db, output_dir = _actions(tmp_path)
    actions.delete_enhance_levels(_enhanced_row(db, output_dir), ["enhanced.png"])

    updated = db.get_generation("p1")
    assert updated["original_files"] is None
    assert updated["enhance_history"] is None
    assert not is_enhanced_row(updated)   # and the green badge is gone with it
    assert enhance_levels(updated) == []


def test_deleting_the_original_keeps_the_enhancement_readable(tmp_path):
    # Binning the pre-enhance file to save the space is a fair thing to want;
    # what is left is still an enhancement, and still says what made it.
    from origenerator.gallery import enhance_levels

    actions, db, output_dir = _actions(tmp_path)
    actions.delete_enhance_levels(_enhanced_row(db, output_dir), ["base.png"])

    updated = db.get_generation("p1")
    (level,) = enhance_levels(updated)
    assert level.label == "Enhance 1"
    assert level.params == {"enhance_scale": 2.0}


def test_deleting_every_version_is_refused(tmp_path):
    # An image with no file left is a deleted generation, and deleting a
    # generation is the gallery's own action — not something a version list does.
    actions, db, output_dir = _actions(tmp_path)
    row = _enhanced_row(db, output_dir)

    assert actions.delete_enhance_levels(row, ["enhanced.png", "base.png"]) is False

    assert db.get_generation("p1")["output_files"] == row["output_files"]
    assert (output_dir / "image" / "enhanced.png").exists()
    assert not actions.can_undo()


def test_undoing_a_version_delete_puts_it_back(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    row = _enhanced_row(db, output_dir)
    actions.delete_enhance_levels(row, ["enhanced.png"])

    actions.undo()

    restored = db.get_generation("p1")
    assert restored["output_files"] == row["output_files"]
    assert restored["original_files"] == row["original_files"]
    assert restored["enhance_history"] == row["enhance_history"]
    assert (output_dir / "image" / "enhanced.png").read_bytes() == b"better"


def test_a_version_delete_leaves_the_row_thumbnail_alone(tmp_path):
    # Only the picked files go: the thumbnail is the row's, and the row stays.
    actions, db, output_dir = _actions(tmp_path)
    row = _completed_row(db, output_dir, "p1", "base.png", subfolder="image",
                         thumb_dir=tmp_path / "thumbs")
    (output_dir / "image" / "enhanced.png").write_bytes(b"better")
    db.update_generation(
        "p1",
        output_files=json.dumps([
            {"filename": "enhanced.png", "subfolder": "image"},
            {"filename": "base.png", "subfolder": "image"},
        ]),
        original_files=json.dumps([{"filename": "base.png", "subfolder": "image"}]),
    )

    actions.delete_enhance_levels(db.get_generation("p1"), ["enhanced.png"])

    assert (tmp_path / "thumbs" / "p1.jpg").exists()
    assert row["thumbnail_path"] == str(tmp_path / "thumbs" / "p1.jpg")
