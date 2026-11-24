from __future__ import annotations

from origenerator.gui.related_media import (
    ANIMATED_FROM,
    ANIMATED_FROM_STARTING_FRAME_OF,
    TRIMMED_FROM,
)
from origenerator.gui.source_tile import SourceTile

_MADE_FROM = (ANIMATED_FROM, ANIMATED_FROM_STARTING_FRAME_OF, TRIMMED_FROM)
_USING_SETTINGS_OF = ("Animated using video settings of", "Animated using flick settings of")
_SETTINGS_USED_FOR = ("Video settings used for animation of",
                      "Flick settings used for animation of")


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
    return next(iter(_tiles(related, _USING_SETTINGS_OF)), _NoTile())


def no_sources(related) -> bool:
    return source_tile(related).isHidden() and settings_tile(related).isHidden()


def settings_used_for(related) -> list[tuple[str, str]]:
    return [(tile.heading, tile._prompt_id)
            for tile in _tiles(related, _SETTINGS_USED_FOR)]


POINTING_BACK = ("Requested from", "Batch-modified from", *_MADE_FROM, *_USING_SETTINGS_OF)


def settings_used_for_tiles(related) -> list:
    return _tiles(related, _SETTINGS_USED_FOR)
