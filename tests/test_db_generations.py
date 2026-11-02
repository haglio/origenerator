from origenerator.db import Database


def _video(tmp_path):
    db = Database(tmp_path / "test.db")
    db.insert_generation(
        prompt_id="vid-001", workflow_name="wan22_i2v", workflow_version="v1",
        params_json="{}", workflow_json="{}")
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
