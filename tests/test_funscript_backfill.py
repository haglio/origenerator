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
    def ensure(path, *, loop, hz, output_dir):
        seen.append((path.name, loop))
        dest = funscript_path_for(path, output_dir=output_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
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


def test_the_output_folder_is_resolved_when_the_sweep_runs(tmp_path, monkeypatch):
    """It was a signature default -- ``output_dir: Path = COMFYUI_OUTPUT_DIR`` --
    evaluated at import, from a constant that was itself built by reading the
    content overlay at import. So the sweep could not be pointed anywhere the
    module had not already decided on before anything called it."""
    from origenerator import config, funscript_backfill

    monkeypatch.setattr(config, "COMFYUI_OUTPUT_DIR", tmp_path / "elsewhere")
    seen = []

    funscript_backfill.backfill(
        FakeDB([_row("gen-alpha", "wan22_i2v", "alpha.mp4")]),
        resolve=lambda row, output_dir: seen.append(output_dir) or None,
    )

    assert seen == [tmp_path / "elsewhere"]


def test_the_cadence_is_resolved_when_the_sweep_runs_too(tmp_path, monkeypatch):
    """The same defect on the same line: the stroke rate was bound at import."""
    from origenerator import config, funscript_backfill

    monkeypatch.setattr(config, "STROKE_DEFAULT_HZ", 2.5)
    clip = tmp_path / "alpha.mp4"
    clip.write_bytes(b"not really a video")
    rates = []

    funscript_backfill.backfill(
        FakeDB([_row("gen-alpha", "wan22_i2v", "alpha.mp4")]),
        resolve=lambda row, output_dir: (clip, "video"),
        ensure=lambda path, *, loop, hz, output_dir: rates.append(hz) or None,
    )

    assert rates == [2.5]
