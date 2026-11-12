from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

from origenerator import gallery
from origenerator.media import MediaType


class LockedOn(NamedTuple):
    row_for: Callable[[str], dict | None]
    show: Callable[[str], None]
    star: Callable[[str], None]


def lock_held(here: LockedOn, played: Callable[[list], list],
              tell_the_session: Callable[[object], bool], prompt_id: str) -> None:
    row = here.row_for(prompt_id)
    if row is None:
        return
    video = _video_played(row, played)
    if video is not None:
        here.star(prompt_id)
    if video is None or not tell_the_session(video):
        here.show(prompt_id)


def _video_played(row: dict, played: Callable[[list], list]):
    if gallery.media_type_of_row(row) != MediaType.VIDEO:
        return None
    return next((item[0] for item in played([row])), None)
