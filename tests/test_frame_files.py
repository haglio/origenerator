from __future__ import annotations

from pathlib import Path

from origenerator.gui.frame_files import FrameFiles

JPEG = b"\xff\xd8\xff\xe0 a fabricated frame"
PNG = b"\x89PNG\r\n\x1a\n a fabricated frame"


def test_a_frame_is_written_where_a_player_can_open_it(tmp_path):
    frames = FrameFiles(tmp_path / "frames")

    path = frames.write("run-1", JPEG)

    assert path.read_bytes() == JPEG
    assert path.suffix == ".jpg"


def test_a_new_frame_is_a_new_file_and_the_same_frame_again_is_not(tmp_path):
    frames = FrameFiles(tmp_path / "frames")

    first = frames.write("run-1", PNG)
    again = frames.write("run-1", PNG)
    newer = frames.write("run-1", PNG + b" one step further")

    assert again == first
    assert newer != first
    assert newer.read_bytes() == PNG + b" one step further"


def test_a_runs_first_frame_stays_and_only_the_newest_two_after_it(tmp_path):
    frames = FrameFiles(tmp_path / "frames")

    written = [frames.write("run-1", PNG + bytes([step])) for step in range(5)]

    assert frames.first_of("run-1") == written[0]
    assert [path.exists() for path in written] == [True, False, False, True, True]


def test_a_forgotten_runs_files_go_once_the_player_lets_go_of_them(tmp_path, monkeypatch):
    frames = FrameFiles(tmp_path / "frames")
    held = frames.write("run-1", PNG)
    newer = frames.write("run-1", PNG + b" one step further")
    still_open = {held}
    unlink = Path.unlink

    def unlink_unless_open(path, missing_ok=False):
        if path in still_open:
            raise PermissionError("a player has it open")
        unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink_unless_open)
    frames.forget("run-1")
    assert frames.first_of("run-1") is None
    assert held.exists() and not newer.exists()

    still_open.clear()
    frames.write("run-2", PNG)
    assert not held.exists()


def test_forgetting_every_run_leaves_the_folder_empty(tmp_path):
    frames = FrameFiles(tmp_path / "frames")
    frames.write("run-1", PNG)
    frames.write("run-2", JPEG)

    frames.forget_all()

    assert list((tmp_path / "frames").iterdir()) == []


def test_frames_left_behind_by_an_earlier_show_are_cleared_away(tmp_path):
    folder = tmp_path / "frames"
    folder.mkdir()
    (folder / "run-0-7.png").write_bytes(PNG)

    FrameFiles(folder)

    assert list(folder.iterdir()) == []


def test_a_frame_that_cannot_be_written_is_no_file(tmp_path):
    blocked = tmp_path / "frames"
    blocked.write_bytes(b"a file where the folder would go")

    assert FrameFiles(blocked).write("run-1", PNG) is None
