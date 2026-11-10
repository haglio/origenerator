from __future__ import annotations

from origenerator.gui.related_media import (
    ANIMATED_FROM,
    ANIMATED_FROM_STARTING_FRAME_OF,
    ANIMATED_USING_VIDEO_SETTINGS_OF,
    TRIMMED_FROM,
    VIDEO_SETTINGS_USED_FOR_ANIMATION_OF,
)
from origenerator.gui.source_tile import SourceTile

_MADE_FROM = (ANIMATED_FROM, ANIMATED_FROM_STARTING_FRAME_OF, TRIMMED_FROM)


class _NoTile:
    _prompt_id = None

    def isHidden(self) -> bool:
        return True


def _tiles(related, headings):
    return [tile for row in (related._animations, related._trims)
            for tile in row.findChildren(SourceTile)
            if not tile.isHidden() and tile.heading in headings]


def source_tile(related):
    return next(iter(_tiles(related, _MADE_FROM)), _NoTile())


def settings_tile(related):
    return next(iter(_tiles(related, (ANIMATED_USING_VIDEO_SETTINGS_OF,))), _NoTile())


def no_sources(related) -> bool:
    return source_tile(related).isHidden() and settings_tile(related).isHidden()


def settings_used_for(related) -> list[tuple[str, str]]:
    return [(tile.heading, tile._prompt_id)
            for tile in _tiles(related, (VIDEO_SETTINGS_USED_FOR_ANIMATION_OF,))]


POINTING_BACK = ("Requested from", "Modified from", *_MADE_FROM, ANIMATED_USING_VIDEO_SETTINGS_OF)


def settings_used_for_tiles(related) -> list:
    return _tiles(related, (VIDEO_SETTINGS_USED_FOR_ANIMATION_OF,))
