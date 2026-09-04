"""Re-derive missing base renders now, instead of waiting for absences.

The app does this on its own: closing it hands ComfyUI a batch of re-renders to
work through while nothing else wants the GPU, and the next launch folds them in
(:mod:`origenerator.base_backfill`, which is where the whole of how and why
lives). A few rows a night, no wait ever paid for them.

This is the same work run to completion in one sitting, for when you would
rather have the backlog gone than have it drain quietly. It is GPU-bound — one
full render per row, at whatever step count that row recorded — so run it with
the app closed and expect it to take as long as generating the images did.

    python tools/backfill_base_renders.py                # what it would do
    python tools/backfill_base_renders.py --apply        # do it
    python tools/backfill_base_renders.py --apply --limit 5

``--db`` points it at another checkout's database, because the rows that need
this are the live install's and a worktree's copy is a throwaway.

Interrupting is safe: each row is folded as it lands, and a re-run — or the next
absence — picks up whatever is left.

Nothing about a repair is decided here. Which rows need one, what recipe
reproduces it, how one is run and how the result is attached are all
:mod:`origenerator.base_backfill`, so this cannot answer a question differently
from the way the app answers it; what is here is the argument parsing and the
report.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from origenerator.base_backfill import (
    attach_base,
    base_params_for,
    render_base_now,
    rows_missing_their_base,
)
from origenerator.comfyui_client import ComfyUIClient
from origenerator.config import DB_PATH
from origenerator.db import Database
from origenerator.workflows import WORKFLOW_REGISTRY


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="actually run them; without this, only report")
    parser.add_argument("--limit", type=int, default=0,
                        help="stop after this many rows (0 = all)")
    parser.add_argument("--db", type=Path, default=DB_PATH,
                        help="the database to repair (default: this checkout's)")
    args = parser.parse_args(argv)

    db = Database(args.db)
    rows = rows_missing_their_base(db.list_generations())
    if args.limit:
        rows = rows[:args.limit]
    print(f"{len(rows)} enhanced image(s) with no base render kept")
    if not args.apply:
        by_workflow: dict[str, int] = {}
        for row in rows:
            name = row.get("workflow_name") or "?"
            by_workflow[name] = by_workflow.get(name, 0) + 1
        for name, count in sorted(by_workflow.items()):
            print(f"  {name}: {count}")
        print("re-run with --apply to generate them")
        return 0

    client = ComfyUIClient()
    done = failed = 0
    for i, row in enumerate(rows, 1):
        workflow = WORKFLOW_REGISTRY[row["workflow_name"]]
        print(f"[{i}/{len(rows)}] {row['prompt_id'][:8]} {workflow.name} ...",
              end="", flush=True)
        params = base_params_for(row, workflow)
        try:
            files = render_base_now(client, workflow, params)
        except Exception as e:
            print(f" failed: {e}")
            failed += 1
            continue
        if not files:
            print(" produced nothing")
            failed += 1
            continue
        # Attached through the app's own path, so a row repaired from here is
        # indistinguishable from one repaired during an absence.
        attach_base(db, row["prompt_id"], files)
        done += 1
        print(f" -> {files[0].get('filename')}")
    print(f"folded {done} base render(s); {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
