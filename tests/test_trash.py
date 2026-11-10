from __future__ import annotations

import json

from app_support.testing import no_wait_for_a_held_file

import origenerator.trash as trash_mod
from origenerator.trash import Trash, TrashedBatch


def _file(path, data=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_store_moves_files_off_their_original_paths(tmp_path):
    src = _file(tmp_path / "out" / "a.png")
    trash = Trash(tmp_path / "trash")

    batch = trash.store([src])

    assert not src.exists()
    assert len(batch.moves) == 1
    original, trashed = batch.moves[0]
    assert original == src
    assert trashed.exists()
    assert trashed.read_bytes() == b"x"


def test_restore_puts_files_back_where_they_were(tmp_path):
    src = _file(tmp_path / "out" / "a.png", b"hello")
    trash = Trash(tmp_path / "trash")
    batch = trash.store([src])

    batch.restore()

    assert src.exists()
    assert src.read_bytes() == b"hello"


def test_a_file_whose_name_a_newer_file_took_comes_back_under_the_next_number(tmp_path):
    deleted = _file(tmp_path / "images" / "alpha_t2i_00005_.png", b"deleted")
    batch = Trash(tmp_path / "trash").store([deleted])
    _file(deleted, b"newer")

    renamed = batch.restore()

    assert deleted.read_bytes() == b"newer"
    assert (tmp_path / "images" / "alpha_t2i_00006_.png").read_bytes() == b"deleted"
    assert renamed == {"alpha_t2i_00005_.png": "alpha_t2i_00006_.png"}


def test_a_videos_files_come_back_together_under_one_new_number(tmp_path):
    videos = tmp_path / "videos"
    video = _file(videos / "beta_i2v_00005.mp4", b"video")
    batch = Trash(tmp_path / "trash").store([video, _file(videos / "beta_i2v_00005.png")])
    _file(video, b"newer")

    renamed = batch.restore()

    assert renamed == {"beta_i2v_00005.mp4": "beta_i2v_00006.mp4",
                       "beta_i2v_00005.png": "beta_i2v_00006.png"}


def test_a_new_number_passes_over_the_names_other_deleted_files_hold(tmp_path):
    images = tmp_path / "images"
    trash = Trash(tmp_path / "trash")
    deleted = _file(images / "alpha_t2i_00005_.png", b"deleted")
    batch = trash.store([deleted])
    _file(deleted, b"newer")
    trash.store([_file(images / "alpha_t2i_00006_.png", b"also deleted")])

    assert batch.restore() == {"alpha_t2i_00005_.png": "alpha_t2i_00007_.png"}


def test_restore_recreates_a_missing_parent_directory(tmp_path):
    src = _file(tmp_path / "out" / "sub" / "a.png")
    trash = Trash(tmp_path / "trash")
    batch = trash.store([src])
    (tmp_path / "out" / "sub").rmdir()

    batch.restore()

    assert src.exists()


def test_purge_permanently_removes_trashed_files(tmp_path):
    src = _file(tmp_path / "out" / "a.png")
    trash = Trash(tmp_path / "trash")
    batch = trash.store([src])
    _, trashed = batch.moves[0]

    batch.purge()

    assert not trashed.exists()
    assert not src.exists()


def test_store_keeps_same_named_files_from_different_folders_apart(tmp_path):
    a = _file(tmp_path / "one" / "clip.png", b"a")
    b = _file(tmp_path / "two" / "clip.png", b"b")
    trash = Trash(tmp_path / "trash")

    batch = trash.store([a, b])
    batch.restore()

    assert a.read_bytes() == b"a"
    assert b.read_bytes() == b"b"


def test_store_with_no_files_is_a_harmless_noop(tmp_path):
    trash = Trash(tmp_path / "trash")
    batch = trash.store([])
    assert batch.moves == []
    batch.restore()
    batch.purge()


def test_store_retries_a_briefly_locked_file(tmp_path, monkeypatch):
    src = _file(tmp_path / "out" / "clip.mp4")
    trash = Trash(tmp_path / "trash")
    real_move = trash_mod.shutil.move
    attempts = {"n": 0}

    def flaky_move(s, d):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise PermissionError("file is open in another process")
        return real_move(s, d)

    monkeypatch.setattr(trash_mod.shutil, "move", flaky_move)

    with no_wait_for_a_held_file():
        batch = trash.store([src])

    assert attempts["n"] == 2
    assert not src.exists()
    assert batch.moves[0][1].exists()


def test_ending_one_item_leaves_another_holding_a_file_of_the_same_name(tmp_path):
    trash = Trash(tmp_path / "trash")
    one = trash.store([_file(tmp_path / "out" / "image" / "same.png")])
    other = trash.store([_file(tmp_path / "out" / "video" / "same.png")])

    one.purge()

    assert not one.subdir.exists()
    assert [held.name for _was, held in other.moves if held.exists()], (
        "each item has a folder of its own, so items never tread on one another")


def test_purge_orphans_clears_only_the_batches_nothing_names(tmp_path):
    trash = Trash(tmp_path / "trash")
    held = trash.store([_file(tmp_path / "out" / "held.png")])
    orphan = trash.store([_file(tmp_path / "out" / "orphan.png")])

    assert trash.purge_orphans([held.subdir]) == 1

    assert held.subdir.exists()
    assert not orphan.subdir.exists(), (
        "nothing can reach it: an experiment's batch off the undo stack, a batch older than "
        "the Trash, or a folder a crash left between the move and the record")


def test_purge_orphans_on_an_untouched_trash_is_a_harmless_noop(tmp_path):
    assert Trash(tmp_path / "never-used").purge_orphans([]) == 0


def test_a_batch_survives_the_session_that_made_it(tmp_path):
    src = _file(tmp_path / "out" / "a.png", b"hello")
    trash = Trash(tmp_path / "trash")
    record = trash.store([src]).record()

    TrashedBatch.from_record(json.loads(json.dumps(record))).restore()

    assert src.read_bytes() == b"hello"


def test_a_re_made_batch_can_purge_what_it_holds(tmp_path):
    src = _file(tmp_path / "out" / "a.png")
    trash = Trash(tmp_path / "trash")
    batch = trash.store([src])

    TrashedBatch.from_record(batch.record()).purge()

    assert not batch.subdir.exists()
    assert not src.exists()


def test_an_empty_batch_re_makes_into_one_that_moves_nothing(tmp_path):
    batch = TrashedBatch.from_record({"moves": [], "subdir": None})
    batch.restore()
    batch.purge()
    assert batch.moves == [], "a delete whose files were already gone records no moves"
