"""Re-derive the missing base render for images the inline enhance tail finished.

Before enhancement became a layer, a workflow with ``enhance`` on saved only the
enhanced picture: the base render was made on the way through and discarded, so
those rows carry one file and no "before" to compare it against. The library
here has 95 of them.

They are recoverable, because they are reproducible. Diffusion is deterministic
given the same seed, model, sampler, scheduler, steps and cfg — and the enhance
tail hangs off the base pass without altering it, so re-running the recorded
recipe with the tail switched off produces exactly the pixels that pass produced
the first time. This queues one such run per row and folds the result in as the
row's original, giving it the ``Original`` / ``Enhance 1`` pair it should have
had.

It is GPU work, not a data migration: one full render per row, at whatever that
row's step count was. Run it with the app closed, and expect it to take as long
as generating the images did.

    python tools/backfill_base_renders.py                # what it would do
    python tools/backfill_base_renders.py --apply        # do it
    python tools/backfill_base_renders.py --apply --limit 5

``--db`` points it at another checkout's database, because the rows that need
this are the live install's and a worktree's copy is a throwaway. Run it from
the primary checkout once this has landed rather than pointing branch code at
the live library — a branch is unfinished code, and writing back into the
library is the one thing a preview must never do.

A row is skipped when its workflow isn't registered (an import the app can't
rebuild), when it already kept an original, or when it produced no file. Runs
are submitted one at a time and waited on, so this never competes with itself
for the GPU; interrupting it is safe — each row is folded as it lands, and a
re-run picks up whatever is left.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from origenerator import gallery  # noqa: E402
from origenerator.comfyui_client import ComfyUIClient  # noqa: E402
from origenerator.completion import extract_completion  # noqa: E402
from origenerator.config import COMFYUI_OUTPUT_DIR, DB_PATH, THUMB_DIR  # noqa: E402
from origenerator.db import Database  # noqa: E402
from origenerator.workflows import WORKFLOW_REGISTRY  # noqa: E402

_POLL_SECONDS = 2.0
_TIMEOUT_SECONDS = 900  # a single still, however slow the model


def rows_missing_their_base(db: Database) -> list[dict]:
    """Enhanced images that kept no original and whose recipe can be rebuilt.

    The badge says an enhancement happened; the absence of an original says the
    tail baked it in. Those two together are exactly the rows this can help.
    """
    out = []
    for row in db.list_generations():
        if gallery.media_type_of_row(row) != "image":
            continue
        if not gallery.is_enhanced_row(row) or gallery.original_files_of(row):
            continue
        if not gallery.produced_output(row):
            continue
        workflow = WORKFLOW_REGISTRY.get(row.get("workflow_name") or "")
        if workflow is None or "enhance" not in workflow.default_params():
            continue
        out.append(row)
    return out


def base_params_for(row: dict, workflow) -> dict:
    """The row's own recipe with the enhance tail switched off.

    Every other param — the seed above all — is reproduced exactly, because
    that is the whole basis for expecting the same pixels back.
    """
    params = dict(workflow.default_params())
    params.update(gallery.parse_params(row.get("params_json")))
    params["enhance"] = False
    return params


def fold_base_into(db: Database, row: dict, files: list[dict]) -> None:
    """Record a re-derived base render as the row's original.

    The enhanced file keeps its place at the head of ``output_files`` — it is
    still what the row shows — and the base joins behind it as the version the
    info pane offers as ``Original``.
    """
    base = [dict(f, role="original") for f in files]
    db.update_generation(
        row["prompt_id"],
        output_files=json.dumps(gallery.row_output_files(row) + base),
        original_files=json.dumps(base),
    )


def run_one(client: ComfyUIClient, workflow, params: dict) -> list[dict]:
    """Submit one base render and wait for its files. ``[]`` on failure."""
    prompt_id = str(uuid.uuid4())
    client.submit_job(workflow.build_api_payload(params), prompt_id)
    deadline = time.monotonic() + _TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(_POLL_SECONDS)
        history = client.fetch_history(prompt_id)
        if not history:
            continue
        files, _thumb, _duration = extract_completion(
            workflow, history, COMFYUI_OUTPUT_DIR, THUMB_DIR, prompt_id, params=params
        )
        return files
    return []


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
    rows = rows_missing_their_base(db)
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
        try:
            files = run_one(client, workflow, base_params_for(row, workflow))
        except Exception as e:
            print(f" failed: {e}")
            failed += 1
            continue
        if not files:
            print(" produced nothing")
            failed += 1
            continue
        fold_base_into(db, row, files)
        done += 1
        print(f" -> {files[0].get('filename')}")
    print(f"folded {done} base render(s); {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
