"""Which images still want an action said for them, and in what order."""
from __future__ import annotations

from origenerator import gallery
from origenerator.generation_state import GenerationStatus, in_sight
from origenerator.media import MediaType


def _wants_sorting(row: dict) -> bool:
    return (row.get("status") == GenerationStatus.COMPLETED
            and in_sight(row)
            and not row.get("image_state")
            and gallery.produced_output(row)
            and gallery.media_type_of_row(row) == MediaType.IMAGE
            and not gallery.is_enhance_product_row(row))


def images_to_sort(rows: list[dict]) -> list[dict]:
    """Every image nobody has said an action for: the favorites first, newest
    backwards, and then the rest, newest backwards."""
    waiting = [row for row in rows if _wants_sorting(row)]
    return sorted(waiting, reverse=True,
                  key=lambda row: (bool(row.get("starred")),
                                   row.get("created_at") or ""))
