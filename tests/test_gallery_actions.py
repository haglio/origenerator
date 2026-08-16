import json

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


def test_eviction_past_the_limit_purges_the_oldest_trash(tmp_path):
    actions, db, output_dir = _actions(tmp_path, limit=1)
    first = _completed_row(db, output_dir, "p1", "a.png")
    second = _completed_row(db, output_dir, "p2", "b.png")

    actions.delete_rows([first])   # batch 1 on the stack
    actions.delete_rows([second])  # pushes batch 1 off the (size-1) stack

    # Only the newest deletion remains undoable; the evicted one is gone for good.
    assert actions.undo_label() is not None
    actions.undo()
    assert db.get_generation("p2") is not None
    assert db.get_generation("p1") is None  # batch 1 was committed, not recoverable
    assert not actions.can_undo()


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
