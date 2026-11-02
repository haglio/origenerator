"""What Combine's Recent dropdown lists: every video of the selected kind.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

from origenerator.act_settings import GENAU, VIDEO
from origenerator.db import Database
from origenerator.video_history import video_history

_LOOPING = "wan22_flf2v_loop"
_FULL_LENGTH = "wan22_i2v"


def _video(prompt_id, created_at="2026-10-01 00:00:00", workflow_name=_FULL_LENGTH):
    return {"prompt_id": prompt_id, "created_at": created_at, "workflow_name": workflow_name}


def _listed(videos, intent, combinations=(), uses=()):
    return [row["prompt_id"] for row in video_history(videos, intent, combinations, uses)]


def _made_from(video, created_at):
    return {"prompt_id": "gen-1", "source_video": video, "created_at": created_at}


def _use(intent, video, created_at):
    return {"intent": intent, "video_prompt_id": video, "generation_prompt_id": None,
            "created_at": created_at}


def test_a_video_nobody_ever_used_is_listed_however_old_it_is():
    assert _listed([_video("old", "2026-04-10 04:29:35")], VIDEO) == ["old"]


def test_a_full_length_video_is_listed_under_kino_alone():
    videos = [_video("vid-1")]

    assert _listed(videos, VIDEO) == ["vid-1"]
    assert _listed(videos, GENAU) == []


def test_a_looping_video_is_listed_under_genau_alone():
    videos = [_video("vid-1", workflow_name=_LOOPING)]

    assert _listed(videos, GENAU) == ["vid-1"]
    assert _listed(videos, VIDEO) == []


def test_a_looping_video_used_under_kino_is_listed_under_genau():
    videos = [_video("vid-1", workflow_name=_LOOPING)]
    uses = [_use(VIDEO, "vid-1", "2026-10-02 00:00:00")]

    assert _listed(videos, GENAU, uses=uses) == ["vid-1"]
    assert _listed(videos, VIDEO, uses=uses) == []


def test_the_newest_come_first_by_when_each_was_made_or_last_used():
    videos = [_video("made-last", "2026-10-05 00:00:00"),
              _video("used-last", "2026-10-01 00:00:00"),
              _video("made-from-last", "2026-10-02 00:00:00"),
              _video("untouched", "2026-10-03 00:00:00")]
    uses = [_use(VIDEO, "used-last", "2026-10-07 00:00:00"),
            _use(VIDEO, "used-last", "2026-10-04 00:00:00")]
    combinations = [_made_from("made-from-last", "2026-10-06 00:00:00")]

    assert _listed(videos, VIDEO, combinations, uses) == [
        "used-last", "made-from-last", "made-last", "untouched"]


def test_a_use_older_than_the_video_leaves_it_where_it_was_made():
    videos = [_video("vid-1", "2026-10-03 00:00:00"), _video("vid-2", "2026-10-02 00:00:00")]
    uses = [_use(VIDEO, "vid-1", "2026-10-01 00:00:00")]

    assert _listed(videos, VIDEO, uses=uses) == ["vid-1", "vid-2"]


def test_a_use_of_a_video_gone_from_the_library_lists_nothing():
    uses = [_use(VIDEO, "gone", "2026-10-01 00:00:00")]

    assert _listed([], VIDEO, uses=uses) == []


def test_an_acts_generation_does_not_count_as_a_use_of_its_video(tmp_path):
    db = Database(tmp_path / "test.db")
    for prompt_id, category in (("custom", None), ("act", "alpha")):
        db.insert_generation(prompt_id=prompt_id, workflow_name=_FULL_LENGTH,
                             workflow_version="v001", params_json="{}", workflow_json="{}")
        db.set_settings_source(prompt_id, category=category, video_prompt_id=f"vid-{prompt_id}")

    assert [made["source_video"] for made in db.custom_combinations()] == ["vid-custom"]
