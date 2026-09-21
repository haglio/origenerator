"""The document this repo publishes about its gallery database, held against the code.

Evolver mounts ``state/origenerator.db`` read-only and selects columns off
``generations`` by name -- the prompts and the model a clip was made with, for
the sidecar it files; the two withdrawal stamps, for the sends it has to take
back.  It cannot import this package, so this document is the whole agreement,
and a rename here that the document does not carry is exactly the silent break
it exists to end: a column gone, every row reading as never sent, every suite
green through it.

These hold the document to the schema this app actually writes.
"""
from __future__ import annotations

import json
from pathlib import Path

from origenerator import db_schema
from origenerator import gallery_contract as contract
from origenerator.gui.export_lane import EXPORT_LANES

REPO_ROOT = Path(__file__).resolve().parents[1]


def _document() -> dict:
    return json.loads(
        contract.contract_path(REPO_ROOT).read_text(encoding="utf-8"))


def test_the_tracked_copy_is_what_publishing_writes(tmp_path):
    """Run ``origenerator.gallery_contract.publish()`` when this fails: a
    document that has drifted from this module tells a reader something untrue."""
    tracked = contract.contract_path(REPO_ROOT)

    assert (contract.publish(tmp_path).read_text(encoding="utf-8")
            == tracked.read_text(encoding="utf-8"))


def test_every_column_the_document_names_is_one_this_app_writes():
    """A column promised to a reader and absent from the table is a SELECT that
    raises on the reader's next run."""
    document = _document()
    declared = {*document["columns"], *document["optional_columns"]}

    assert declared <= set(db_schema.GENERATION_COLUMNS)


def test_every_lane_the_document_names_stamps_the_columns_it_promises():
    """The send and its withdrawal are one fact spelled in two places -- the
    button's column here, the reader's column over there.  A lane whose stamps
    are not the promised ones is a send the reader never sees."""
    stamped = {lane.source_key: {"sent": lane.flag, "unsent": lane.unsent_flag}
               for lane in EXPORT_LANES}

    assert stamped == _document()["lanes"]
