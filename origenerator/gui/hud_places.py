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


def place_of(places: HudPlaces, shape: str) -> tuple[HudCorner, bool]:
    return (places.corners.get(shape, HudCorner.UPPER_LEFT), places.minimized.get(shape, False))


def has_the_osr2(places: HudPlaces, shape: str) -> bool:
    return places.has_osr2.get(shape, False)


def told(places: HudPlaces, shape: str, action: str, argument: str) -> None:
    if action == HUD_CORNER:
        places.corners[shape] = read_mode(HudCorner, argument, place_of(places, shape)[0])
    elif action == HAS_THE_OSR2:
        places.has_osr2[shape] = argument == "1"
    else:
        places.minimized[shape] = argument == "1"


def moved(places: HudPlaces, shape: str, direction: str) -> None:
    places.corners[shape] = place_of(places, shape)[0].toward(direction)


def collapsed(places: HudPlaces, shape: str, minimized: bool) -> None:
    places.minimized[shape] = minimized


def opened_in(places: HudPlaces, shape: str, corner: HudCorner) -> None:
    places.corners[shape] = corner
    places.minimized[shape] = False


def as_saved(places: HudPlaces) -> dict:
    saved = {}
    for shape in sorted(places.corners.keys() | places.minimized.keys()):
        corner, minimized = place_of(places, shape)
        saved[shape] = {"corner": corner, "minimized": minimized}
    return saved


def restore(places: HudPlaces, saved: object) -> None:
    for shape, place in (saved.items() if isinstance(saved, dict) else ()):
        if isinstance(place, dict):
            places.corners[shape] = read_mode(HudCorner, place.get("corner"), HudCorner.UPPER_LEFT)
            places.minimized[shape] = place.get("minimized") is True
