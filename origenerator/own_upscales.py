from __future__ import annotations

from origenerator.evolver_upscales import filed_at
from origenerator.library_views import LibrarySnapshot


def mark_own_upscales(db) -> int:
    library = LibrarySnapshot(db.list_generations())
    marked = 0
    for row in library.video_rows:
        upscale = library.upscale_of_row(row)
        if upscale is None:
            continue
        when = filed_at(upscale)
        mark = (str(upscale), when.isoformat() if when is not None else None)
        if mark != (row.get("evolver_upscale"), row.get("evolver_upscaled_at")):
            db.set_evolver_upscale(row["prompt_id"], *mark)
            marked += 1
    return marked
