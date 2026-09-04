"""Cut the clips already sent to Genau down to one stroke, after the fact.

The Genau lane sends one stroke of a clip now rather than the whole loop (see
:mod:`origenerator.stroke_trim` for why). Everything sent before it learned to
went whole, so Genau has been steering however many strokes those clips hold as
though each were one. This makes the cut those clips never got.

    python tools/backfill_genau_trims.py            # what it would do
    python tools/backfill_genau_trims.py --apply    # do it

It is ffmpeg on a clip a second or two long, so it is seconds per row rather
than the minutes a base render costs, and it can run with the app open: the
files land beside their clips in ComfyUI's output folder and the rows appear in
the gallery at its next refresh.

``--db`` points it at another checkout's database, because the rows that need
this are the live install's and a worktree's copy is a throwaway.

It does NOT send the cuts anywhere. The clips it cuts are already in Genau's
folder whole, and putting a second version of each beside them is a decision
about that folder rather than about this library -- press Send to Genau on the
cut when that is what you want.

Nothing about a cut is decided here. Which rows want one, where the stroke is,
how the file is made and how it is recorded are all
:mod:`origenerator.stroke_trim`, the same module the lane itself asks, so this
cannot answer a question differently from the way the app answers it; what is
here is the argument parsing and the report.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from origenerator.config import COMFYUI_OUTPUT_DIR, DB_PATH, THUMB_DIR
from origenerator.db import Database
from origenerator.gallery import resolve_preview
from origenerator.stroke_trim import NoSingleStroke, clips_sent_whole, single_stroke_clip


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="actually cut them; without this, only report")
    parser.add_argument("--limit", type=int, default=0,
                        help="stop after this many clips (0 = all)")
    parser.add_argument("--db", type=Path, default=DB_PATH,
                        help="the database to cut in (default: this checkout's)")
    args = parser.parse_args(argv)

    db = Database(args.db)
    rows = clips_sent_whole(db.list_generations())
    if args.limit:
        rows = rows[:args.limit]
    print(f"{len(rows)} clip(s) sent to Genau with no single-stroke cut")
    if not args.apply:
        for row in rows:
            preview = resolve_preview(row, COMFYUI_OUTPUT_DIR)
            name = preview[0].name if preview else "(file missing)"
            print(f"  {row['genau_exported_at']}  {name}")
        print("re-run with --apply to cut them")
        return 0

    done = failed = 0
    for i, row in enumerate(rows, 1):
        preview = resolve_preview(row, COMFYUI_OUTPUT_DIR)
        print(f"[{i}/{len(rows)}] {row['prompt_id'][:8]} ...", end="", flush=True)
        if preview is None or preview[1] != "video":
            print(" no video file on disk")
            failed += 1
            continue
        try:
            cut = single_stroke_clip(row, preview[0], db,
                                    output_dir=COMFYUI_OUTPUT_DIR, thumb_dir=THUMB_DIR)
        except NoSingleStroke as e:
            print(f" not cut: {e}")
            failed += 1
            continue
        except Exception as e:
            print(f" failed: {e}")
            failed += 1
            continue
        print(f" -> {cut.name}")
        done += 1
    print(f"cut {done} clip(s); {failed} left alone")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
