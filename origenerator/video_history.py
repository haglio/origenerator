from __future__ import annotations

from origenerator.act_settings import lane_of


def video_history(videos, intent: str, combinations=(), uses=()) -> list[dict]:
    listed = [row for row in videos if lane_of(row) == intent]
    last_touched = {row["prompt_id"]: row.get("created_at") or "" for row in listed}
    used = [*((use["video_prompt_id"], use["created_at"]) for use in uses),
            *((made["source_video"], made["created_at"]) for made in combinations)]
    for video, when in used:
        if video in last_touched:
            last_touched[video] = max(last_touched[video], when)
    return sorted(listed, key=lambda row: last_touched[row["prompt_id"]], reverse=True)
