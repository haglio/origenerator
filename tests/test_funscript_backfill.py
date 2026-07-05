import json

from origenerator.funscript import funscript_path_for
from origenerator.funscript_backfill import backfill


class FakeDB:
    def __init__(self, rows):
        self._rows = rows

    def list_generations(self):
        return list(self._rows)


def _row(prompt_id, workflow_name, filename):
    return {
        "prompt_id": prompt_id,
        "workflow_name": workflow_name,
        "output_files": json.dumps([{"filename": filename, "subfolder": ""}]),
        "thumbnail_path": None,
    }


def _recording_ensure(seen):
    def ensure(path, *, loop, hz):
        seen.append((path.name, loop))
        dest = funscript_path_for(path)
        dest.write_text("{}", encoding="utf-8")
        return dest
    return ensure


def test_backfill_scripts_each_video_with_its_loop_flag_and_skips_images(tmp_path):
    (tmp_path / "v_i2v.mp4").write_bytes(b"v")
    (tmp_path / "v_loop.mp4").write_bytes(b"v")
    (tmp_path / "still.png").write_bytes(b"p")
    db = FakeDB([
        _row("1", "wan22_i2v", "v_i2v.mp4"),
        _row("2", "wan22_flf2v_loop", "v_loop.mp4"),
        _row("3", "sdxl_t2i", "still.png"),
    ])
    seen = []
    result = backfill(db, tmp_path, ensure=_recording_ensure(seen))

    # Each video is scripted with its workflow's loop flag; the still image isn't.
    assert sorted(seen) == [("v_i2v.mp4", False), ("v_loop.mp4", True)]
    assert result["written"] == 2 and result["skipped"] == 0


def test_backfill_is_idempotent(tmp_path):
    (tmp_path / "v.mp4").write_bytes(b"v")
    db = FakeDB([_row("1", "wan22_i2v", "v.mp4")])
    backfill(db, tmp_path, ensure=_recording_ensure([]))

    seen = []
    result = backfill(db, tmp_path, ensure=_recording_ensure(seen))
    assert result["written"] == 0 and result["skipped"] == 1


def test_backfill_counts_a_video_whose_file_is_missing(tmp_path):
    db = FakeDB([_row("1", "wan22_i2v", "gone.mp4")])  # no file on disk
    seen = []
    result = backfill(db, tmp_path, ensure=_recording_ensure(seen))
    assert seen == []  # nothing to script
    assert result["missing"] == 1 and result["written"] == 0
