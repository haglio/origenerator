from __future__ import annotations

from dataclasses import dataclass

from origenerator.slideshow import SlideshowFilters, SlideshowState


@dataclass(frozen=True)
class RegionLeft:
    state: SlideshowState
    filters: SlideshowFilters

    def saved(self) -> dict:
        return {"state": self.state.saved(), "filters": self.filters.saved()}

    @classmethod
    def restored(cls, saved) -> RegionLeft | None:
        if not isinstance(saved, dict):
            return None
        return cls(SlideshowState.restored(saved.get("state")),
                   SlideshowFilters.restored(saved.get("filters")))


def saved_regions(regions: dict[str, RegionLeft]) -> dict:
    return {shape: left.saved() for shape, left in regions.items()}


def restored_regions(saved, shapes) -> dict[str, RegionLeft]:
    if not isinstance(saved, dict):
        return {}
    restored = ((shape, RegionLeft.restored(saved.get(shape))) for shape in shapes)
    return {shape: left for shape, left in restored if left is not None}
