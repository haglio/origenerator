import pytest

from origenerator.db import Database, NewGeneration


def _video(tmp_path):
    db = Database(tmp_path / "test.db")
    db.insert_generation(NewGeneration(
        prompt_id="vid-001", workflow_name="wan22_i2v", workflow_version="v1",
        params_json="{}", workflow_json="{}"))
    return db


def test_sending_down_the_genau_lane_again_after_taking_it_back_retracts_the_withdrawal(tmp_path):
    db = _video(tmp_path)
    db.mark_genau_exported("vid-001")
    db.mark_genau_unsent("vid-001")

    row = db.get_generation("vid-001")
    assert row["genau_exported_at"] is None
    assert row["genau_unsent_at"] is not None

    db.mark_genau_exported("vid-001")

    row = db.get_generation("vid-001")
    assert row["genau_exported_at"] is not None
    assert row["genau_unsent_at"] is None


def test_the_two_lanes_keep_their_own_stamps(tmp_path):
    db = _video(tmp_path)
    db.mark_evolver_exported("vid-001")
    db.mark_genau_exported("vid-001")
    db.mark_genau_unsent("vid-001")

    row = db.get_generation("vid-001")
    assert row["evolver_exported_at"] is not None
    assert row["evolver_unsent_at"] is None


def test_a_videos_watch_counts_are_kept_on_its_row(tmp_path):
    db = _video(tmp_path)

    db.set_watch_counts("vid-001", {"completions": 3, "skips": 1, "locks": 2})

    row = db.get_generation("vid-001")
    assert (row["watch_completions"], row["watch_skips"], row["watch_locks"]) == (3, 1, 2)


def test_what_the_library_records_of_a_video_is_kept_on_its_row(tmp_path):
    db = _video(tmp_path)

    db.set_library_record("vid-001", web_url="https://example.com/watch/101",
                          library_id="made-up-id", upscale_provenance='{"tool": "Example Upscaler"}')

    row = db.get_generation("vid-001")
    assert (row["web_url"], row["library_id"], row["upscale_provenance"]) == (
        "https://example.com/watch/101", "made-up-id", '{"tool": "Example Upscaler"}')


def test_the_library_record_writes_only_its_own_columns(tmp_path):
    db = _video(tmp_path)

    db.set_library_record("vid-001", video_seconds=4.5)
    assert db.get_generation("vid-001")["video_seconds"] == 4.5
    with pytest.raises(ValueError, match="starred"):
        db.set_library_record("vid-001", starred=1)


def test_a_write_to_the_gallery_tells_whoever_asked_and_a_read_tells_no_one(tmp_path):
    db, told = _video(tmp_path), []
    db.when_changed(lambda: told.append("changed"))

    db.get_generation("vid-001")
    db.list_generations()
    reads = list(told)
    db.set_watch_counts("vid-001", {"completions": 1})

    assert (reads, told) == ([], ["changed"])
