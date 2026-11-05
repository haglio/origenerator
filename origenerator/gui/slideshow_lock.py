from __future__ import annotations

from collections.abc import Callable

from origenerator import gallery
from origenerator.media import MediaType


def lock_held(row_for: Callable[[str], dict | None], show: Callable[[str], None],
              played: Callable[[list], list], tell_the_session: Callable[[object], bool],
              prompt_id: str) -> None:
    row = row_for(prompt_id)
    if row is None:
        return
    video = _video_played(row, played)
    if video is None or not tell_the_session(video):
        show(prompt_id)


def _video_played(row: dict, played: Callable[[list], list]):
    if gallery.media_type_of_row(row) != MediaType.VIDEO:
        return None
    return next((item[0] for item in played([row])), None)
