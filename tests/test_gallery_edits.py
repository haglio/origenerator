from __future__ import annotations

import json
from pathlib import Path

from origenerator.db import Database, NewGeneration
from origenerator.gallery import enhancement_versions, is_enhanced_row
from origenerator.gallery_edits import GalleryEdits, GalleryEnvironment
from origenerator.output_places import OutputPlaces
from origenerator.trash import Trash


def _completed_row(db, output_dir, pid, file, *, thumb_dir=None):
    subfolder, _, filename = file.rpartition("/")
    db.insert_generation(NewGeneration(
        prompt_id=pid, workflow_name="sdxl_t2i", workflow_version="v002",
        params_json="{}", workflow_json="{}",
    ))
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


def _actions(tmp_path, limit=50, release_files=None, cancel_enhancements=None, thumb_dir=None):
    db = Database(tmp_path / "test.db")
    output_dir = tmp_path / "output"
    trash = Trash(tmp_path / "trash")
    environment = GalleryEnvironment(release_files=release_files,
                                     cancel_enhancements=cancel_enhancements,
                                     thumb_dir=thumb_dir)
    return GalleryEdits(db, OutputPlaces.in_one_folder(output_dir), trash, limit=limit,
                          environment=environment), db, output_dir


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
    assert restored == row
    assert file_path.exists()
    assert file_path.read_bytes() == b"data"
    assert not actions.can_undo()


def test_undoing_a_delete_after_a_newer_image_took_its_name_lists_its_new_name(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    actions.delete_rows([_completed_row(db, output_dir, "p1", "alpha_t2i_00005_.png")])
    (output_dir / "alpha_t2i_00005_.png").write_bytes(b"newer")

    actions.undo()

    assert json.loads(db.get_generation("p1")["output_files"]) == [
        {"filename": "alpha_t2i_00006_.png", "subfolder": ""}]
    assert (output_dir / "alpha_t2i_00005_.png").read_bytes() == b"newer"


def test_undoing_a_delete_says_which_generation_came_back(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    row = _completed_row(db, output_dir, "p1", "a.png")
    actions.delete_rows([row])
    assert actions.undo() == "p1"


def test_undoing_a_folder_made_by_hand_moves_the_selection_nowhere(tmp_path):
    actions, _db, _out = _actions(tmp_path)
    actions.custom_collections.create("Keepers", [])
    assert actions.undo() is None


def test_undo_with_an_empty_stack_does_nothing(tmp_path):
    actions, _db, _out = _actions(tmp_path)
    assert actions.undo() is None


def test_delete_also_takes_the_video_metadata_sidecar(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    row = _completed_row(db, output_dir, "v1", "video/clip.mp4")
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
    assert thumb.exists()
    assert thumb.read_bytes() == b"thumb"


def test_delete_of_a_pending_row_without_files_is_still_undoable(tmp_path):
    actions, db, _ = _actions(tmp_path)
    db.insert_generation(NewGeneration(
        prompt_id="pend", workflow_name="sdxl_t2i", workflow_version="v002",
        params_json="{}", workflow_json="{}",
    ))
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
    assert db.get_generation("p1") is None
    assert db.get_generation("p2") is None

    actions.undo()
    assert db.get_generation("p1") is not None
    assert db.get_generation("p2") is not None
    assert not actions.can_undo()


def test_undo_label_describes_the_most_recent_action(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    assert actions.undo_label() is None

    actions.custom_collections.create("Keepers", [])
    assert "create folder" in actions.undo_label().lower()

    rows = [_completed_row(db, output_dir, "p1", "a.png"),
            _completed_row(db, output_dir, "p2", "b.png")]
    actions.delete_rows(rows)
    assert "2" in actions.undo_label()


def test_redo_re_applies_an_undone_delete(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    row = _completed_row(db, output_dir, "p1", "a.png")
    file_path = output_dir / "a.png"
    actions.delete_rows([row])
    actions.undo()
    assert actions.can_redo()
    assert not actions.can_undo()

    actions.redo()

    assert db.get_generation("p1") is None
    assert not file_path.exists()
    assert actions.can_undo()
    assert not actions.can_redo()


def test_a_delete_can_be_undone_and_redone_over_and_over(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    row = _completed_row(db, output_dir, "p1", "a.png")
    file_path = output_dir / "a.png"
    actions.delete_rows([row])

    for _ in range(3):
        actions.undo()
        assert db.get_generation("p1") == row
        assert file_path.exists()
        actions.redo()
        assert db.get_generation("p1") is None
        assert not file_path.exists()


def test_redo_walks_back_up_several_undos_in_order(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    first = _completed_row(db, output_dir, "p1", "a.png")
    second = _completed_row(db, output_dir, "p2", "b.png")
    actions.delete_rows([first])
    actions.delete_rows([second])
    actions.undo()
    actions.undo()

    actions.redo()
    assert db.get_generation("p1") is None
    assert db.get_generation("p2") is not None
    actions.redo()
    assert db.get_generation("p2") is None


def test_a_new_action_forks_history_and_drops_the_redo(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    row = _completed_row(db, output_dir, "p1", "a.png")
    actions.delete_rows([row])
    actions.undo()
    assert actions.can_redo()

    actions.custom_collections.create("Keepers", [])

    assert not actions.can_redo()


def test_redo_label_names_the_step_it_would_re_apply(tmp_path):
    actions, _db, _output_dir = _actions(tmp_path)
    assert actions.redo_label() is None
    assert not actions.can_redo()
    actions.custom_collections.create("Keepers", [])
    actions.undo()
    assert "create folder" in actions.redo_label().lower()


def test_redo_with_nothing_undone_is_a_noop(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    row = _completed_row(db, output_dir, "p1", "a.png")
    actions.delete_rows([row])
    actions.redo()
    assert db.get_generation("p1") is None
    assert actions.can_undo()


def test_eviction_past_the_limit_leaves_the_oldest_in_the_trash(tmp_path):
    actions, db, output_dir = _actions(tmp_path, limit=1)
    first = _completed_row(db, output_dir, "p1", "a.png")
    second = _completed_row(db, output_dir, "p2", "b.png")

    actions.delete_rows([first])
    actions.delete_rows([second])

    assert actions.undo_label() is not None
    actions.undo()
    assert db.get_generation("p2") is not None
    assert db.get_generation("p1") is None
    assert not actions.can_undo()
    assert [r["prompt_id"] for r in db.list_trashed()] == ["p1"]
    actions.restore_deleted(["p1"])
    assert db.get_generation("p1") == first
    assert (output_dir / "a.png").read_bytes() == b"data"


def test_a_delete_is_held_in_the_trash_with_the_row_it_dropped(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    row = _completed_row(db, output_dir, "p1", "a.png", thumb_dir=tmp_path / "thumbs")

    actions.delete_rows([row])

    (held,) = db.list_trashed()
    assert held["prompt_id"] == "p1"
    assert held["row"] == row
    assert held["deleted_at"]
    moved = dict(held["batch"]["moves"])
    assert set(moved) == {str(output_dir / "a.png"), str(tmp_path / "thumbs" / "p1.jpg")}
    assert all(Path(dest).exists() for dest in moved.values())


def test_undoing_a_delete_takes_it_back_out_of_the_trash(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    row = _completed_row(db, output_dir, "p1", "a.png")
    actions.delete_rows([row])

    actions.undo()

    assert db.list_trashed() == []


def test_each_deleted_item_is_held_on_its_own(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    rows = [_completed_row(db, output_dir, "p1", "a.png"),
            _completed_row(db, output_dir, "p2", "b.png")]
    actions.delete_rows(rows)

    actions.restore_deleted(["p2"])

    assert db.get_generation("p2") is not None
    assert (output_dir / "b.png").exists()
    assert db.get_generation("p1") is None
    assert [r["prompt_id"] for r in db.list_trashed()] == ["p1"]


def test_restoring_returns_the_row_and_the_files_and_clears_the_record(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    thumb_dir = tmp_path / "thumbs"
    row = _completed_row(db, output_dir, "p1", "a.png", thumb_dir=thumb_dir)
    actions.delete_rows([row])

    assert actions.restore_deleted(["p1"]) == "p1"

    assert db.get_generation("p1") == row
    assert (output_dir / "a.png").read_bytes() == b"data"
    assert (thumb_dir / "p1.jpg").read_bytes() == b"thumb"
    assert db.list_trashed() == []


def test_purging_ends_the_files_and_the_record_for_good(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    row = _completed_row(db, output_dir, "p1", "a.png")
    actions.delete_rows([row])
    (held,) = db.list_trashed()
    trashed = Path(held["batch"]["moves"][0][1])
    assert trashed.exists()

    actions.purge_deleted(["p1"])

    assert not trashed.exists()
    assert not (output_dir / "a.png").exists()
    assert db.list_trashed() == []
    assert db.get_generation("p1") is None


def test_restoring_from_the_trash_is_not_an_undo_step(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    first = _completed_row(db, output_dir, "p1", "a.png")
    second = _completed_row(db, output_dir, "p2", "b.png")
    actions.delete_rows([first])
    actions.delete_rows([second])

    actions.restore_deleted(["p1"])

    assert actions.undo_label() == "Delete 1 item"


def test_two_rows_claiming_one_file_move_it_once_and_both_come_back(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    first = _completed_row(db, output_dir, "p1", "shared.png")
    second = _completed_row(db, output_dir, "p2", "shared.png")

    actions.delete_rows([first, second])
    actions.undo()

    assert (output_dir / "shared.png").read_bytes() == b"data"
    assert db.get_generation("p1") == first
    assert db.get_generation("p2") == second


def test_restoring_or_purging_an_item_the_trash_no_longer_holds_is_a_noop(tmp_path):
    actions, _db, _ = _actions(tmp_path)
    assert actions.restore_deleted(["never-deleted"]) is None
    actions.purge_deleted(["never-deleted"])


def test_reject_experiment_trashes_files_but_keeps_the_learning_row(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    row = _completed_row(db, output_dir, "e1", "exp.png",
                         thumb_dir=tmp_path / "thumbs")
    file_path = output_dir / "exp.png"
    thumb_path = tmp_path / "thumbs" / "e1.jpg"

    actions.reject_experiment(row)

    kept = db.get_generation("e1")
    assert kept is not None
    assert kept["experiment_verdict"] == "down"
    assert kept["output_files"] is None
    assert kept["thumbnail_path"] is None
    assert not file_path.exists()
    assert not thumb_path.exists()
    assert actions.can_undo()
    assert actions.undo_label() == "Reject experiment"


def test_delete_has_the_app_let_go_of_the_files_before_moving_them(tmp_path):
    seen = []
    actions, db, output_dir = _actions(
        tmp_path,
        release_files=lambda paths, **_: seen.append([(p, p.exists()) for p in paths]),
    )
    row = _completed_row(db, output_dir, "v1", "video/clip.mp4",
                         thumb_dir=tmp_path / "thumbs")

    actions.delete_rows([row])

    assert seen == [[(output_dir / "video" / "clip.mp4", True),
                     (tmp_path / "thumbs" / "v1.jpg", True)]]


def test_delete_stops_an_enhancement_being_made_of_what_it_takes(tmp_path):
    seen = []
    actions, db, output_dir = _actions(
        tmp_path,
        cancel_enhancements=lambda rows: seen.append(
            [(r["prompt_id"], (output_dir / "a.png").exists()) for r in rows]),
    )
    row = _completed_row(db, output_dir, "p1", "a.png")

    actions.delete_rows([row])

    assert seen == [[("p1", True)]]


def test_rejecting_an_experiment_stops_its_enhancement_too(tmp_path):
    seen = []
    actions, db, output_dir = _actions(tmp_path, cancel_enhancements=seen.extend)
    row = _completed_row(db, output_dir, "e1", "exp.png")

    actions.reject_experiment(row)

    assert [r["prompt_id"] for r in seen] == ["e1"]


def test_deleting_a_version_leaves_a_running_enhancement_alone(tmp_path):
    seen = []
    actions, db, output_dir = _actions(tmp_path, cancel_enhancements=seen.extend)

    actions.delete_enhance_versions(_enhanced_row(db, output_dir), ["enhanced.png"])

    assert seen == []


def test_deleting_a_version_lets_go_of_it_as_a_file_of_an_item_that_stays(tmp_path):
    seen = []
    actions, db, output_dir = _actions(
        tmp_path, release_files=lambda paths, **told: seen.append((list(paths), told)))

    actions.delete_enhance_versions(_enhanced_row(db, output_dir), ["enhanced.png"])

    assert seen == [([output_dir / "image" / "enhanced.png"], {"the_item_stays": True})]


def test_rejecting_an_experiment_releases_its_files_too(tmp_path):
    seen = []
    actions, db, output_dir = _actions(tmp_path, release_files=lambda paths, **_: seen.extend(paths))
    row = _completed_row(db, output_dir, "e1", "video/exp.mp4")

    actions.reject_experiment(row)

    assert seen == [output_dir / "video" / "exp.mp4"]


def test_rejecting_an_experiment_files_nothing_in_the_trash(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    row = _completed_row(db, output_dir, "e1", "exp.png")

    actions.reject_experiment(row)

    assert db.list_trashed() == []


def test_undoing_a_rejection_returns_the_experiment_to_review(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    row = _completed_row(db, output_dir, "e1", "exp.png",
                         thumb_dir=tmp_path / "thumbs")
    actions.reject_experiment(row)

    actions.undo()

    restored = db.get_generation("e1")
    assert restored["experiment_verdict"] is None
    assert restored["output_files"] == row["output_files"]
    assert restored["thumbnail_path"] == row["thumbnail_path"]
    assert (output_dir / "exp.png").exists()
    assert (tmp_path / "thumbs" / "e1.jpg").exists()


def test_undoing_a_rejection_after_a_newer_image_took_its_name_lists_its_new_name(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    actions.reject_experiment(_completed_row(db, output_dir, "e1", "alpha_t2i_00005_.png"))
    (output_dir / "alpha_t2i_00005_.png").write_bytes(b"newer")

    actions.undo()

    assert json.loads(db.get_generation("e1")["output_files"]) == [
        {"filename": "alpha_t2i_00006_.png", "subfolder": ""}]


def _enhanced_row(db, output_dir, pid="p1"):
    _completed_row(db, output_dir, pid, "image/base.png")
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
    actions, db, output_dir = _actions(tmp_path)
    row = _enhanced_row(db, output_dir)

    assert actions.delete_enhance_versions(row, ["enhanced.png"]) is True

    updated = db.get_generation("p1")
    assert updated is not None
    assert not (output_dir / "image" / "enhanced.png").exists()
    assert (output_dir / "image" / "base.png").exists()
    assert json.loads(updated["output_files"]) == [
        {"filename": "base.png", "subfolder": "image"}
    ]


def test_deleting_the_last_enhancement_leaves_a_plain_image(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    actions.delete_enhance_versions(_enhanced_row(db, output_dir), ["enhanced.png"])

    updated = db.get_generation("p1")
    assert updated["original_files"] is None
    assert updated["enhance_history"] is None
    assert not is_enhanced_row(updated)
    assert enhancement_versions(updated) == []


def test_deleting_the_original_keeps_the_enhancement_readable(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    actions.delete_enhance_versions(_enhanced_row(db, output_dir), ["base.png"])

    updated = db.get_generation("p1")
    (level,) = enhancement_versions(updated)
    assert level.label == "Enhancement 1/1"
    assert level.params == {"enhance_scale": 2.0}


def test_deleting_every_version_is_refused(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    row = _enhanced_row(db, output_dir)

    assert actions.delete_enhance_versions(row, ["enhanced.png", "base.png"]) is False

    assert db.get_generation("p1")["output_files"] == row["output_files"]
    assert (output_dir / "image" / "enhanced.png").exists()
    assert not actions.can_undo()


def test_deleting_a_name_the_row_does_not_hold_deletes_nothing(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    row = _enhanced_row(db, output_dir)

    assert actions.delete_enhance_versions(row, ["never_held.png"]) is False

    assert not actions.can_undo()


def test_deleting_a_version_files_nothing_in_the_trash_collection(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    row = _enhanced_row(db, output_dir)

    actions.delete_enhance_versions(row, ["enhanced.png"])

    assert db.list_trashed() == []


def test_a_versions_files_are_ended_once_its_undo_entry_falls_off_the_stack(tmp_path):
    actions, db, output_dir = _actions(tmp_path, limit=1)
    first = _enhanced_row(db, output_dir, "p1")
    (output_dir / "image" / "enhanced2.png").write_bytes(b"better")
    _completed_row(db, output_dir, "p2", "image/base2.png")
    db.update_generation(
        "p2",
        output_files=json.dumps([{"filename": "enhanced2.png", "subfolder": "image"},
                                 {"filename": "base2.png", "subfolder": "image"}]),
        original_files=json.dumps([{"filename": "base2.png", "subfolder": "image"}]))
    second = db.get_generation("p2")

    def held():
        return [path for path in (tmp_path / "trash").rglob("*") if path.is_file()]

    actions.delete_enhance_versions(first, ["enhanced.png"])
    assert len(held()) == 1
    actions.delete_enhance_versions(second, ["enhanced2.png"])

    assert len(held()) == 1


def test_a_thumbnail_that_cannot_be_redrawn_stays_as_it_was(tmp_path):
    thumb_dir = tmp_path / "thumbs"
    actions, db, output_dir = _actions(tmp_path, thumb_dir=thumb_dir)
    _completed_row(db, output_dir, "p1", "image/base.png", thumb_dir=thumb_dir)
    (output_dir / "image" / "enhanced.png").write_bytes(b"not a picture")
    db.update_generation(
        "p1",
        output_files=json.dumps([{"filename": "enhanced.png", "subfolder": "image"},
                                 {"filename": "base.png", "subfolder": "image"}]),
        original_files=json.dumps([{"filename": "base.png", "subfolder": "image"}]))
    before = db.get_generation("p1")["thumbnail_path"]

    assert actions.delete_enhance_versions(db.get_generation("p1"), ["enhanced.png"]) is True

    assert db.get_generation("p1")["thumbnail_path"] == before


def test_undoing_a_version_delete_puts_it_back(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    row = _enhanced_row(db, output_dir)
    actions.delete_enhance_versions(row, ["enhanced.png"])

    actions.undo()

    restored = db.get_generation("p1")
    assert restored["output_files"] == row["output_files"]
    assert restored["original_files"] == row["original_files"]
    assert restored["enhance_history"] == row["enhance_history"]
    assert (output_dir / "image" / "enhanced.png").read_bytes() == b"better"


def test_undoing_a_version_delete_after_a_newer_image_took_its_name_lists_its_new_name(
        tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    _completed_row(db, output_dir, "p1", "image/alpha_t2i_00004_.png")
    (output_dir / "image" / "alpha_t2i_00005_.png").write_bytes(b"better")
    db.update_generation(
        "p1",
        output_files=json.dumps([{"filename": "alpha_t2i_00005_.png", "subfolder": "image"},
                                 {"filename": "alpha_t2i_00004_.png", "subfolder": "image"}]),
        original_files=json.dumps([{"filename": "alpha_t2i_00004_.png", "subfolder": "image"}]),
        enhance_history=json.dumps([{"filename": "alpha_t2i_00005_.png", "params": {}}]),
    )
    actions.delete_enhance_versions(db.get_generation("p1"), ["alpha_t2i_00005_.png"])
    (output_dir / "image" / "alpha_t2i_00005_.png").write_bytes(b"newer")

    actions.undo()

    restored = db.get_generation("p1")
    assert [f["filename"] for f in json.loads(restored["output_files"])] == [
        "alpha_t2i_00006_.png", "alpha_t2i_00004_.png"]
    assert json.loads(restored["enhance_history"])[0]["filename"] == "alpha_t2i_00006_.png"
    assert (output_dir / "image" / "alpha_t2i_00005_.png").read_bytes() == b"newer"


def test_a_version_delete_leaves_the_row_thumbnail_alone(tmp_path):
    actions, db, output_dir = _actions(tmp_path)
    row = _completed_row(db, output_dir, "p1", "image/base.png",
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

    actions.delete_enhance_versions(db.get_generation("p1"), ["enhanced.png"])

    assert (tmp_path / "thumbs" / "p1.jpg").exists()
    assert row["thumbnail_path"] == str(tmp_path / "thumbs" / "p1.jpg")


class TestTheFoldersItWasGiven:
    def test_the_output_places_are_the_ones_it_was_built_with(self, tmp_path):
        places = OutputPlaces.in_one_folder(tmp_path / "output")
        actions = GalleryEdits(Database(tmp_path / "test.db"), places, Trash(tmp_path / "trash"))

        assert actions.places == places

    def test_the_thumbnail_folder_comes_from_the_environment_it_was_given(self, tmp_path):
        actions = GalleryEdits(
            Database(tmp_path / "test.db"), OutputPlaces.in_one_folder(tmp_path / "output"),
            Trash(tmp_path / "trash"),
            environment=GalleryEnvironment(thumb_dir=tmp_path / "thumbs"))

        assert actions.thumb_dir == tmp_path / "thumbs"

    def test_no_thumbnail_folder_is_answered_rather_than_raised(self, tmp_path):
        actions = GalleryEdits(Database(tmp_path / "test.db"), OutputPlaces.in_one_folder(tmp_path / "output"), Trash(tmp_path / "trash"))

        assert actions.thumb_dir is None
