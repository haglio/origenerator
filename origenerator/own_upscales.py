from __future__ import annotations

from origenerator.library_views import LibrarySnapshot


def mark_own_upscales(db) -> int:
    library = LibrarySnapshot(db.list_generations())
    marked = 0
    for row in library.video_rows:
        upscale = library.upscale_of_row(row)
        if upscale is not None and str(upscale) != row.get("evolver_upscale"):
            db.set_evolver_upscale(row["prompt_id"], str(upscale))
            marked += 1
    return marked
