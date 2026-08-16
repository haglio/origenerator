"""Re-deriving the base render for images the inline enhance tail finished.

Those rows kept one file and no "before". The base is recoverable because it is
reproducible: the same seed and recipe with the tail off reproduces the pixels
that pass made, and attaching it gives the row the ``Original`` / ``Enhance 1``
pair it should have had. The work rides the absence the background experimenter
uses, since it is a full render per row and there are a great many of them.
"""

import json

from origenerator import gallery
from origenerator.base_backfill import (
    SOURCE, TARGET_KEY, attach_base, base_params_for, cancel_base_renders,
    fold_base_render, fold_completed_base_renders, queue_base_renders,
    rows_missing_their_base,
)
from origenerator.db import Database
from origenerator.workflows import WORKFLOW_REGISTRY

_SDXL = WORKFLOW_REGISTRY["sdxl_t2i"]


def _add(db, prompt_id, *, params, files, original_files=None, workflow="sdxl_t2i",
         source="generated", status="completed"):
    db.insert_generation(
        prompt_id=prompt_id, workflow_name=workflow, workflow_version="v004",
        positive_prompt=params.get("positive_prompt", ""), seed=params.get("seed"),
        params_json=json.dumps(params), workflow_json="{}", source=source,
    )
    fields = {"status": status}
    if files is not None:
        fields["output_files"] = json.dumps(files)
    if original_files is not None:
        fields["original_files"] = json.dumps(original_files)
    db.update_generation(prompt_id, **fields)
    return db.get_generation(prompt_id)


def _file(name):
    return {"filename": name, "subfolder": "image", "type": "output"}


def _baked(db, prompt_id="baked", seed=1, filename=None):
    return _add(db, prompt_id,
                params=dict(_SDXL.default_params(), enhance=True, seed=seed),
                files=[_file(filename or f"sdxl_t2i_{prompt_id}.png")])


# --- which rows need one ---------------------------------------------------


def test_it_picks_exactly_the_rows_that_lost_their_base(tmp_path):
    db = Database(tmp_path / "t.db")
    _baked(db, "baked")
    _add(db, "plain", params=dict(_SDXL.default_params(), enhance=False, seed=2),
         files=[_file("sdxl_t2i_b.png")])
    _add(db, "layered", params=dict(_SDXL.default_params(), enhance=False, seed=3),
         files=[_file("image_enhance_1.png"), _file("sdxl_t2i_c.png")],
         original_files=[_file("sdxl_t2i_c.png")])

    assert [r["prompt_id"] for r in rows_missing_their_base(db.list_generations())] \
        == ["baked"]


def test_an_unrebuildable_import_is_left_alone(tmp_path):
    # No registered template, so there is no recipe to re-run — and guessing one
    # would produce a "base" that is not this image's base at all.
    db = Database(tmp_path / "t.db")
    _add(db, "import", params={"enhance": True}, files=[_file("mystery.png")],
         workflow="unknown")
    assert rows_missing_their_base(db.list_generations()) == []


def test_a_re_render_in_flight_is_not_itself_something_to_repair(tmp_path):
    db = Database(tmp_path / "t.db")
    _baked(db, "baked")
    _add(db, "repair", params=dict(_SDXL.default_params(), enhance=False,
                                   **{TARGET_KEY: "baked"}),
         files=None, source=SOURCE, status="running")
    assert [r["prompt_id"] for r in rows_missing_their_base(db.list_generations())] \
        == ["baked"]


# --- what one runs at ------------------------------------------------------


def test_the_rerun_is_the_recorded_recipe_with_the_tail_off(tmp_path):
    db = Database(tmp_path / "t.db")
    row = _add(db, "baked",
               params=dict(_SDXL.default_params(), enhance=True, seed=4242,
                           steps=37, cfg=6.5, positive_prompt="a lantern"),
               files=[_file("sdxl_t2i_a.png")])

    params = base_params_for(row, _SDXL)

    assert params["enhance"] is False   # the one thing that changes
    # Everything the pixels depend on is reproduced exactly, the seed above all.
    assert params["seed"] == 4242
    assert params["steps"] == 37
    assert params["cfg"] == 6.5
    assert params["positive_prompt"] == "a lantern"
    assert params[TARGET_KEY] == "baked"   # and it knows what it repairs


def test_the_target_key_cannot_split_a_folder(tmp_path):
    # It rides in the params, so it has to be invisible to the grouping: the
    # gallery only ever asks a workflow for the keys it declares.
    db = Database(tmp_path / "t.db")
    row = _baked(db, "baked")
    before = gallery.settings_folder_key(row)
    repaired = dict(row, params_json=json.dumps(base_params_for(row, _SDXL)))
    assert gallery.settings_folder_key(repaired) == before


# --- the absence batch -----------------------------------------------------


def test_an_absence_queues_a_batch_and_stops_at_the_limit(tmp_path):
    db = Database(tmp_path / "t.db")
    for i in range(5):
        _baked(db, f"baked{i}", seed=i)
    launched = []

    queued = queue_base_renders(
        db.list_generations(),
        lambda wf, params: launched.append(params[TARGET_KEY]) or "p",
        limit=3,
    )

    assert queued == 3 and len(launched) == 3


def test_a_refused_launch_is_not_counted(tmp_path):
    db = Database(tmp_path / "t.db")
    _baked(db, "baked")
    assert queue_base_renders(db.list_generations(), lambda wf, p: None) == 0


def test_a_row_already_being_repaired_is_not_queued_again(tmp_path):
    # Two short absences in a row must not put the same repair in twice.
    db = Database(tmp_path / "t.db")
    _baked(db, "baked")
    _add(db, "repair", params={TARGET_KEY: "baked"}, files=None,
         source=SOURCE, status="running")

    assert queue_base_renders(db.list_generations(), lambda wf, p: "p") == 0


# --- folding what the absence finished -------------------------------------


def test_attaching_the_base_gives_the_row_its_two_levels(tmp_path):
    db = Database(tmp_path / "t.db")
    _baked(db, "baked", filename="sdxl_t2i_a.png")

    assert attach_base(db, "baked", [_file("sdxl_t2i_a_base.png")]) is True

    upgraded = db.get_generation("baked")
    # The enhanced file keeps its place at the head — it is still what the row
    # shows — and the base joins behind it as the original.
    assert [f["filename"] for f in gallery.row_output_files(upgraded)] == \
        ["sdxl_t2i_a.png", "sdxl_t2i_a_base.png"]
    assert [lvl.label for lvl in gallery.enhance_levels(upgraded)] == \
        ["Enhance 1", "Original"]
    assert gallery.original_files_of(upgraded)[0]["filename"] == "sdxl_t2i_a_base.png"


def test_a_repaired_row_is_not_offered_again(tmp_path):
    # Interrupting is safe: each row is attached as it lands, and the next
    # absence picks up only what is left.
    db = Database(tmp_path / "t.db")
    _baked(db, "baked", filename="sdxl_t2i_a.png")
    attach_base(db, "baked", [_file("sdxl_t2i_a_base.png")])
    assert rows_missing_their_base(db.list_generations()) == []


def test_folding_drops_the_repair_row_it_came_from(tmp_path):
    db = Database(tmp_path / "t.db")
    _baked(db, "baked", filename="sdxl_t2i_a.png")
    repair = _add(db, "repair", params={TARGET_KEY: "baked"},
                  files=[_file("sdxl_t2i_a_base.png")], source=SOURCE)

    assert fold_base_render(db, repair) == "baked"

    assert db.get_generation("repair") is None   # a repair leaves no trace
    assert gallery.original_files_of(db.get_generation("baked"))


def test_a_repair_whose_target_is_gone_is_left_alone(tmp_path):
    # Deleted while the absence ran: leave the row rather than half-migrate it,
    # so it can be found and cleared by hand.
    db = Database(tmp_path / "t.db")
    repair = _add(db, "repair", params={TARGET_KEY: "vanished"},
                  files=[_file("orphan_base.png")], source=SOURCE)
    assert fold_base_render(db, repair) is None
    assert db.get_generation("repair") is not None


def test_the_startup_sweep_folds_the_finished_and_leaves_the_running(tmp_path):
    db = Database(tmp_path / "t.db")
    _baked(db, "one", filename="sdxl_t2i_one.png")
    _baked(db, "two", filename="sdxl_t2i_two.png")
    _add(db, "done", params={TARGET_KEY: "one"},
         files=[_file("sdxl_t2i_one_base.png")], source=SOURCE)
    _add(db, "running", params={TARGET_KEY: "two"}, files=None,
         source=SOURCE, status="running")

    assert fold_completed_base_renders(db) == 1

    assert db.get_generation("done") is None
    assert db.get_generation("running")["status"] == "running"
    assert gallery.original_files_of(db.get_generation("one"))
    assert not gallery.original_files_of(db.get_generation("two"))


# --- and clearing the rest when the app opens ------------------------------


class _FakeClient:
    def __init__(self, running=()):
        self._running = set(running)
        self.cancelled, self.interrupts = [], 0

    def fetch_running(self):
        return self._running

    def cancel_prompt(self, prompt_id):
        self.cancelled.append(prompt_id)

    def interrupt(self):
        self.interrupts += 1


def test_opening_the_app_drops_what_the_absence_had_not_reached(tmp_path):
    db = Database(tmp_path / "t.db")
    _baked(db, "one")
    _add(db, "queued", params={TARGET_KEY: "one"}, files=None,
         source=SOURCE, status="pending")
    _add(db, "done", params={TARGET_KEY: "one"},
         files=[_file("sdxl_t2i_one_base.png")], source=SOURCE)
    client = _FakeClient()

    assert cancel_base_renders(db, client) == 1

    assert client.cancelled == ["queued"]
    assert db.get_generation("queued") is None
    assert db.get_generation("done") is not None  # a finished repair still folds


def test_one_caught_mid_render_is_interrupted_too(tmp_path):
    # Dequeuing alone would leave it holding the GPU the user just came back for.
    db = Database(tmp_path / "t.db")
    _baked(db, "one")
    _add(db, "running", params={TARGET_KEY: "one"}, files=None,
         source=SOURCE, status="running")
    client = _FakeClient(running={"running"})

    assert cancel_base_renders(db, client) == 1
    assert client.interrupts == 1


def test_a_repair_never_grows_a_folder_of_its_own(tmp_path):
    # It is a repair of an existing image, not an image: a half-finished one
    # must never show as a duplicate tile beside what it repairs.
    db = Database(tmp_path / "t.db")
    _baked(db, "one")
    _add(db, "running", params=dict(_SDXL.default_params(), enhance=False,
                                    **{TARGET_KEY: "one"}),
         files=None, source=SOURCE, status="running")
    _add(db, "landed", params=dict(_SDXL.default_params(), enhance=False,
                                   **{TARGET_KEY: "one"}),
         files=[_file("sdxl_t2i_one_base.png")], source=SOURCE)

    tree = gallery.build_gallery_tree(db.list_generations())
    shown = [r["prompt_id"] for media in tree for r in gallery.rows_under(media)]
    assert shown == ["one"]
