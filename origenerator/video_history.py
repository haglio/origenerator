from __future__ import annotations

from origenerator.act_settings import lane_of


def video_history(combinations, intent: str, uses=()) -> list[str]:
    lane_noted = {use["generation_prompt_id"] for use in uses if use["generation_prompt_id"]}
    used = [*((use["video_prompt_id"], use["created_at"]) for use in uses
              if use["intent"] == intent),
            *((made["source_video"], made["created_at"]) for made in combinations
              if made["prompt_id"] not in lane_noted
              and lane_of(made) == intent)]
    last_used: dict[str, str] = {}
    for video, when in used:
        last_used[video] = max(last_used.get(video, ""), when)
    return sorted(last_used, key=last_used.__getitem__, reverse=True)
