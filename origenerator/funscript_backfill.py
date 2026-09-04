"""One-shot: synthesize a funscript for every already-generated video without one.

New videos get a funscript at completion (see ``completion.py``); this sweeps the
videos that predate that. It's GPU-free (the script is authored from each clip's
duration, not measured) and idempotent — a video that already has a sidecar is
left untouched — so it's safe to re-run.

    python -m origenerator.funscript_backfill
"""

from __future__ import annotations

import logging
from pathlib import Path

from origenerator import config
from origenerator.db import Database
from origenerator.funscript import ensure_funscript, funscript_of
from origenerator.gallery import media_type_of_row, resolve_preview
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)


def backfill(db, output_dir: Path | None = None, *, hz: float | None = None,
             ensure=ensure_funscript, resolve=resolve_preview) -> dict:
    """Script every video generation that has none. Returns a counts summary.

    ``ensure``/``resolve`` are injectable so the sweep logic can be tested without
    real videos. The loop flag for each row comes from its workflow, so loop clips
    get a seamlessly-tiling script.

    ``output_dir`` and ``hz`` resolve from config when the caller names neither.
    Resolved HERE rather than as signature defaults: a default is evaluated at
    import, from constants that were themselves built by reading the content
    overlay at import, so the sweep could not be pointed anywhere this module had
    not decided on before anything called it.
    """
    output_dir = config.COMFYUI_OUTPUT_DIR if output_dir is None else output_dir
    hz = config.STROKE_DEFAULT_HZ if hz is None else hz
    result = {"written": 0, "skipped": 0, "missing": 0, "failed": 0}
    for row in db.list_generations():
        if media_type_of_row(row) != "video":
            continue
        preview = resolve(row, output_dir)
        if preview is None or preview[1] != "video":
            result["missing"] += 1
            continue
        path = preview[0]
        workflow = WORKFLOW_REGISTRY.get(row.get("workflow_name") or "")
        existed = funscript_of(path, output_dir=output_dir) is not None
        dest = ensure(path, loop=bool(workflow and workflow.looping), hz=hz,
                      output_dir=output_dir)
        if dest is None:
            result["failed"] += 1
        elif existed:
            result["skipped"] += 1
        else:
            result["written"] += 1
    return result


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = backfill(Database(config.DB_PATH))
    logger.info(
        "Funscript backfill: %d written, %d already present, %d missing file, %d failed",
        result["written"], result["skipped"], result["missing"], result["failed"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
