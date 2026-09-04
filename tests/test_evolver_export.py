from pathlib import Path

from origenerator import evolver_export
from origenerator.evolver_export import export_video


def test_export_copies_video_into_the_inbox(tmp_path):
    src = tmp_path / "wan22_i2v_00001_.mp4"
    src.write_bytes(b"video-bytes")
    inbox = tmp_path / "0_inbox" / "origenerator"  # does not exist yet

    dest = export_video(src, inbox)

    assert dest == inbox / "wan22_i2v_00001_.mp4"
    assert dest.read_bytes() == b"video-bytes"
    # A copy, not a move: the gallery keeps its own file on disk.
    assert src.exists()


def test_export_writes_a_partial_file_before_finalizing(tmp_path, monkeypatch):
    """The copy must land under a ``.partial.`` name and only be renamed into
    place once complete — Evolver ignores ``.partial.`` files, so it can never
    grab a half-written video. Nothing partial may survive a successful export.
    """
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"data")
    inbox = tmp_path / "inbox"

    seen = {}
    real_copy = evolver_export.shutil.copy2

    def spy_copy(source, dest):
        dest = Path(dest)
        seen["copy_dest"] = dest
        seen["final_present_during_copy"] = (inbox / "clip.mp4").exists()
        return real_copy(source, dest)

    monkeypatch.setattr(evolver_export.shutil, "copy2", spy_copy)

    dest = export_video(src, inbox)

    assert ".partial." in seen["copy_dest"].name  # Evolver skips this mid-copy
    assert seen["final_present_during_copy"] is False
    assert dest.name == "clip.mp4"
    assert [p.name for p in inbox.iterdir()] == ["clip.mp4"]  # no partial left behind


def test_export_does_not_clobber_an_already_queued_video(tmp_path):
    """A second export of a same-named video keeps both — Evolver may not have
    swept the first out of the inbox yet, and overwriting would lose it."""
    inbox = tmp_path / "inbox"
    src = tmp_path / "clip.mp4"

    src.write_bytes(b"first")
    first = export_video(src, inbox)
    src.write_bytes(b"second")
    second = export_video(src, inbox)

    assert first != second
    assert first.read_bytes() == b"first"
    assert second.read_bytes() == b"second"
