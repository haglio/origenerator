"""What a reader of this app's gallery database must know, published for it.

Evolver mounts the gallery read-only and reads two things out of it: the row
that made a clip, which becomes that clip's metadata sidecar, and the stamp
that says a send has been taken back, which tells it to delete the copies it is
holding.  It cannot import this package -- no app here reaches into another's
repo -- so it worked from names spelled on its own side: a table, nine columns,
two withdrawal stamps and the param keys a model is named under.

Spelled over there, those names were a copy of these, and nothing compared the
two: a column renamed here left every row reading as never sent, with both
suites green.  Spelled here they are the promise this app makes, and
``origenerator_gallery_contract.json`` at the checkout root is how they travel.
Run ``python -c "from origenerator.gallery_contract import publish; publish()"``
to rewrite it; the suite fails on a copy that no longer matches, and on a
promise the table cannot keep.

What is NOT here is the inbox folder each lane's clips arrive under.  That name
is library vocabulary, which the sanitize blocklist keeps out of a tracked file;
both apps read it from their own content overlay and the two must agree.
"""
from __future__ import annotations

import json
from pathlib import Path

#: At the checkout root beside the launcher, which is the path a reader that
#: resolves this checkout at all already has.
CONTRACT_FILE = "origenerator_gallery_contract.json"

#: Where the database sits inside this checkout.
DATABASE_PATH = "state/origenerator.db"

#: The one table a reader is promised.
TABLE = "generations"

#: Columns every gallery has, which a reader may select without guarding.
COLUMNS = (
    "prompt_id",
    "workflow_name",
    "workflow_version",
    "positive_prompt",
    "negative_prompt",
    "seed",
    "params_json",
    "output_files",
    "created_at",
)

#: Columns added after the table first shipped: a gallery old enough to predate
#: one simply does not have it, and selecting it there raises.  A reader asks
#: ``PRAGMA table_info`` and takes whichever are present.
OPTIONAL_COLUMNS = (
    "provenance",
    "evolver_exported_at",
    "evolver_unsent_at",
    "genau_exported_at",
    "genau_unsent_at",
)

#: Inside ``params_json``, the keys a run's model is named under, most specific
#: first: the WAN video workflows use ``unet_high``, Flux ``unet``, SDXL
#: ``checkpoint``.  The first present is the model.
PARAMS_MODEL_KEYS = ("unet_high", "unet", "checkpoint", "unet_low")

#: Inside ``params_json``, the start frame an image-to-video run was animated
#: from, as ComfyUI's LoadImage recorded it.
PARAMS_INPUT_IMAGE_KEY = "input_image"

#: Each lane a clip is handed down, and the pair of stamps that records its
#: send: ``sent`` while the copy is over there, ``unsent`` once it has been
#: taken back.  The reader deletes what it holds for a row whose ``unsent`` is
#: set, so these two names are the whole of what passes back.
LANES = {
    "evolver": {"sent": "evolver_exported_at", "unsent": "evolver_unsent_at"},
    "genau": {"sent": "genau_exported_at", "unsent": "genau_unsent_at"},
}

PROJECT_DIR = Path(__file__).resolve().parent.parent


def declaration() -> dict:
    """The published document, as a reader reads it."""
    return {
        "database_path": DATABASE_PATH,
        "table": TABLE,
        "columns": list(COLUMNS),
        "optional_columns": list(OPTIONAL_COLUMNS),
        "params_model_keys": list(PARAMS_MODEL_KEYS),
        "params_input_image_key": PARAMS_INPUT_IMAGE_KEY,
        "lanes": {lane: dict(stamps) for lane, stamps in LANES.items()},
    }


def published_text() -> str:
    return json.dumps(declaration(), indent=2) + "\n"


def contract_path(root: Path | None = None) -> Path:
    return (root if root is not None else PROJECT_DIR) / CONTRACT_FILE


def publish(root: Path | None = None) -> Path:
    """Write the document out, in the shape the tracked copy holds."""
    path = contract_path(root)
    path.write_text(published_text(), encoding="utf-8")
    return path
