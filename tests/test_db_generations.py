import pytest

from origenerator.db import Database, NewGeneration
from origenerator.generation_state import GenerationSource


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


@pytest.mark.parametrize("source", [GenerationSource.REPLACED, GenerationSource.LEFT_OUT])
def test_a_replaced_or_left_out_row_is_left_out_of_the_listing_yet_found_by_its_id(
        tmp_path, source):
    db = _video(tmp_path)
    db.insert_generation(NewGeneration(
        prompt_id="vid-002", workflow_name="wan22_i2v", workflow_version="v1",
        params_json="{}", workflow_json="{}", source=source))

    assert ([row["prompt_id"] for row in db.list_generations()],
            db.get_generation("vid-002")["source"]) == (["vid-001"], source)


def test_a_row_read_out_of_the_gallery_is_a_copy_so_changing_it_writes_nothing(tmp_path):
    db = _video(tmp_path)

    db.get_generation("vid-001")["status"] = "completed"
    db.list_generations()[0]["status"] = "completed"

    assert db.get_generation("vid-001")["status"] == "pending"


def test_a_file_is_traced_to_its_generation_and_a_generation_made_since_is_found_too(tmp_path):
    db = _video(tmp_path)
    db.update_generation("vid-001", output_files='[{"filename": "wan22_i2v_00001_.mp4"}]')
    first = db.generation_of_file("C:/library/videos/wan22_i2v_00001__topaz.mp4")
    db.insert_generation(NewGeneration(
        prompt_id="vid-002", workflow_name="wan22_i2v", workflow_version="v1",
        params_json="{}", workflow_json="{}"))
    db.update_generation("vid-002", output_files='[{"filename": "wan22_i2v_00002_.mp4"}]')

    assert (first, db.generation_of_file("C:/library/videos/wan22_i2v_00002_.mp4"),
            db.generation_of_file("C:/library/videos/no_such_00009_.mp4")) == (
        "vid-001", "vid-002", None)
