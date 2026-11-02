from __future__ import annotations

from dataclasses import dataclass, field

from funestra.hud_placement import HudCorner
from funestra.modes import read_mode

from origenerator.slideshow_buttons import HAS_THE_OSR2, HUD_CORNER


@dataclass
class HudPlaces:
    corners: dict[str, HudCorner] = field(default_factory=dict)
    minimized: dict[str, bool] = field(default_factory=dict)
    has_osr2: dict[str, bool] = field(default_factory=dict)


def place_of(places: HudPlaces, side: str) -> tuple[HudCorner, bool]:
    return (places.corners.get(side, HudCorner.UPPER_LEFT), places.minimized.get(side, False))


def has_the_osr2(places: HudPlaces, side: str) -> bool:
    return places.has_osr2.get(side, False)


def told(places: HudPlaces, side: str, action: str, argument: str) -> None:
    if action == HUD_CORNER:
        places.corners[side] = read_mode(HudCorner, argument, place_of(places, side)[0])
    elif action == HAS_THE_OSR2:
        places.has_osr2[side] = argument == "1"
    else:
        places.minimized[side] = argument == "1"


def moved(places: HudPlaces, side: str, direction: str) -> None:
    places.corners[side] = place_of(places, side)[0].toward(direction)


def collapsed(places: HudPlaces, side: str, minimized: bool) -> None:
    places.minimized[side] = minimized


def opened_in(places: HudPlaces, side: str, corner: HudCorner) -> None:
    places.corners[side] = corner
    places.minimized[side] = False


def as_saved(places: HudPlaces) -> dict:
    saved = {}
    for side in sorted(places.corners.keys() | places.minimized.keys()):
        corner, minimized = place_of(places, side)
        saved[side] = {"corner": corner, "minimized": minimized}
    return saved


def restore(places: HudPlaces, saved: object) -> None:
    for side, place in (saved.items() if isinstance(saved, dict) else ()):
        if isinstance(place, dict):
            places.corners[side] = read_mode(HudCorner, place.get("corner"), HudCorner.UPPER_LEFT)
            places.minimized[side] = place.get("minimized") is True
