import json

from origenerator.trash import Trash, TrashedBatch


def _file(path, data=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_store_moves_files_off_their_original_paths(tmp_path):
    src = _file(tmp_path / "out" / "a.png")
    trash = Trash(tmp_path / "trash")

    batch = trash.store([src])

    assert not src.exists()  # gone from where the user had it
    assert len(batch.moves) == 1
    original, trashed = batch.moves[0]
    assert original == src
    assert trashed.exists() and trashed.read_bytes() == b"x"


def test_restore_puts_files_back_where_they_were(tmp_path):
    src = _file(tmp_path / "out" / "a.png", b"hello")
    trash = Trash(tmp_path / "trash")
    batch = trash.store([src])

    batch.restore()

    assert src.exists() and src.read_bytes() == b"hello"


def test_restore_recreates_a_missing_parent_directory(tmp_path):
    src = _file(tmp_path / "out" / "sub" / "a.png")
    trash = Trash(tmp_path / "trash")
    batch = trash.store([src])
    # The folder emptied out after the move; restore must rebuild the path.
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
    assert not src.exists()  # purge is the opposite of restore — nothing comes back


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
    batch.restore()  # must not raise
    batch.purge()    # must not raise


def test_store_retries_a_briefly_locked_file(tmp_path, monkeypatch):
    import origenerator.trash as trash_mod

    src = _file(tmp_path / "out" / "clip.mp4")
    trash = Trash(tmp_path / "trash")
    real_move = trash_mod.shutil.move
    attempts = {"n": 0}

    def flaky_move(s, d):
        attempts["n"] += 1
        if attempts["n"] == 1:  # the media backend hasn't let go of the file yet
            raise PermissionError("file is open in another process")
        return real_move(s, d)

    monkeypatch.setattr(trash_mod.shutil, "move", flaky_move)
    monkeypatch.setattr(trash_mod.time, "sleep", lambda _s: None)

    batch = trash.store([src])

    assert attempts["n"] == 2  # retried once, then succeeded
    assert not src.exists()
    assert batch.moves[0][1].exists()


def test_purge_orphans_clears_only_the_batches_nothing_names(tmp_path):
    # The recovery bin names the batches it still holds; everything else in the
    # trash is unreachable and is what this reclaims.
    trash = Trash(tmp_path / "trash")
    held = trash.store([_file(tmp_path / "out" / "held.png")])
    orphan = trash.store([_file(tmp_path / "out" / "orphan.png")])

    assert trash.purge_orphans([held.subdir]) == 1

    assert held.subdir.exists()
    assert not orphan.subdir.exists()


def test_purge_orphans_on_an_untouched_trash_is_a_harmless_noop(tmp_path):
    assert Trash(tmp_path / "never-used").purge_orphans([]) == 0


def test_a_batch_survives_the_session_that_made_it(tmp_path):
    # The bin stores a batch as plain data and re-makes it launches later, so a
    # delete stays undoable long after the objects that performed it are gone.
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
    # What a branch session's NoTrash records: nothing was taken, so nothing is
    # restored or purged, and neither call may raise.
    batch = TrashedBatch.from_record({"moves": [], "subdir": None})
    batch.restore()
    batch.purge()
    assert batch.moves == []
