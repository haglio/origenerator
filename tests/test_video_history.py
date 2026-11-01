"""What Combine's Recent dropdown lists: the videos each lane's slot has been given.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

from origenerator.act_settings import GENAU, VIDEO
from origenerator.db import Database
from origenerator.video_history import video_history


def test_a_video_put_in_the_slot_is_listed_under_the_lane_it_went_in_under(tmp_path):
    db = Database(tmp_path / "test.db")

    db.record_combine_video_use(VIDEO, "vid-1")

    assert video_history(db.custom_combinations(), VIDEO,
                         db.list_combine_video_uses()) == ["vid-1"]


def _made_from(video, prompt_id="gen-1", created_at="2026-10-01 00:00:00",
               workflow_name="wan22_i2v"):
    return {"prompt_id": prompt_id, "source_video": video, "created_at": created_at,
            "workflow_name": workflow_name}


def test_a_generation_with_no_lane_noted_lists_its_video_under_kino_when_it_does_not_loop():
    made = [_made_from("vid-1")]

    assert video_history(made, VIDEO) == ["vid-1"]
    assert video_history(made, GENAU) == []


def test_a_generation_with_no_lane_noted_lists_its_video_under_genau_when_it_loops():
    made = [_made_from("vid-1", workflow_name="wan22_flf2v_loop")]

    assert video_history(made, GENAU) == ["vid-1"]
    assert video_history(made, VIDEO) == []


def _use(intent, video, created_at, generation=None):
    return {"intent": intent, "video_prompt_id": video, "generation_prompt_id": generation,
            "created_at": created_at}


def test_a_generation_whose_lane_was_noted_is_listed_under_that_lane_alone():
    made = [_made_from("vid-1", "gen-1")]
    uses = [_use(GENAU, "vid-1", "2026-10-01 00:00:00", generation="gen-1")]

    assert video_history(made, GENAU, uses) == ["vid-1"]
    assert video_history(made, VIDEO, uses) == []


def test_each_video_is_listed_once_at_its_last_use_the_newest_first():
    made = [_made_from("vid-2", "gen-1", "2026-10-01 00:00:03")]
    uses = [_use(VIDEO, "vid-1", "2026-10-01 00:00:04"),
            _use(VIDEO, "vid-3", "2026-10-01 00:00:02"),
            _use(VIDEO, "vid-2", "2026-10-01 00:00:01")]

    assert video_history(made, VIDEO, uses) == ["vid-1", "vid-2", "vid-3"]


def test_an_acts_generation_lends_the_slot_no_video(tmp_path):
    db = Database(tmp_path / "test.db")
    for prompt_id, category in (("custom", None), ("act", "alpha")):
        db.insert_generation(prompt_id=prompt_id, workflow_name="wan22_i2v",
                             workflow_version="v001", params_json="{}", workflow_json="{}")
        db.set_settings_source(prompt_id, category=category, video_prompt_id=f"vid-{prompt_id}")

    assert video_history(db.custom_combinations(), VIDEO) == ["vid-custom"]
