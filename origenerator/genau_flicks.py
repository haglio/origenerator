from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app_support.gallery_rows import made_here
from funestra.inclusion_pair import BOTH, Included

from origenerator.action_settings import loops
from origenerator.gallery.shapes import PORTRAIT
from origenerator.item_shape import row_shape


@dataclass(frozen=True)
class GenauFilters:
    favorites: bool = False
    enhanced: bool = False
    shapes: Included = BOTH


NO_FILTER = GenauFilters()


def saved(filters: GenauFilters) -> dict:
    return {"favorites": filters.favorites, "enhanced": filters.enhanced,
            "shapes": list(filters.shapes)}


def restored(saved_as) -> GenauFilters:
    if not isinstance(saved_as, dict):
        return NO_FILTER
    shapes = saved_as.get("shapes")
    kept = (tuple(shapes) if isinstance(shapes, list) and len(shapes) == 2
            and all(type(one) is bool for one in shapes) else NO_FILTER.shapes)
    return GenauFilters(favorites=saved_as.get("favorites") is True,
                        enhanced=saved_as.get("enhanced") is True, shapes=kept)


@dataclass(frozen=True)
class Flick:
    path: Path
    prompt_id: str
    flipped: bool = False


class FlicksLibrary(Protocol):
    recent_rows: list[dict]

    def is_enhanced(self, row: dict) -> bool: ...

    def slides_of(self, rows) -> list[tuple]: ...


def _kept(row: dict, library: FlicksLibrary, filters: GenauFilters) -> bool:
    portrait, landscape = filters.shapes
    return (loops(row) and made_here(row)
            and (portrait if row_shape(row) == PORTRAIT else landscape)
            and (not filters.favorites or bool(row.get("starred")))
            and (not filters.enhanced or library.is_enhanced(row)))


def flicks_of(library: FlicksLibrary, filters: GenauFilters) -> list[Flick]:
    rows = [row for row in library.recent_rows if _kept(row, library, filters)]
    flipped = {row["prompt_id"] for row in rows if row.get("genau_flipped")}
    return [Flick(Path(path), prompt_id, prompt_id in flipped)
            for path, _kind, prompt_id, _thumb in library.slides_of(rows)]
