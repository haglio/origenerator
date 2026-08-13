"""Folding a finished standalone enhance into the image it upgraded.

An enhancement is an upgraded layer on an existing image, not a generation of
its own: the fold moves the enhanced file onto the source row (same folder,
same star, same identity), keeps the pre-enhance original listed and on disk,
and deletes the transient job row. The startup sweep does the same for
completions that landed while the app was closed — and retroactively for rows
recorded back when Image Enhance was presented as its own workflow.
"""

import json

from origenerator import gallery
from origenerator.db import Database
from origenerator.gallery import (
    fold_completed_enhancements,
    fold_enhancement,
    is_enhanced_row,
)


def _add_source(db, prompt_id="src", filename="sdxl_t2i_src.png", starred=False):
    db.insert_generation(
        prompt_id=prompt_id, workflow_name="sdxl_t2i", workflow_version="v002",
        positive_prompt="a cat", seed=1,
        params_json=json.dumps({"positive_prompt": "a cat", "steps": 30, "seed": 1}),
        workflow_json="{}",
    )
    db.update_generation(prompt_id, status="completed", thumbnail_path="src_thumb.jpg",
                         output_files=json.dumps([{"filename": filename,
                                                   "subfolder": "image",
                                                   "type": "output"}]))
    if starred:
        db.set_generation_starred(prompt_id, True)
    return db.get_generation(prompt_id)


def _add_enhance(db, prompt_id, input_ref, filename, status="completed",
                 thumbnail="enh_thumb.jpg"):
    db.insert_generation(
        prompt_id=prompt_id, workflow_name="image_enhance", workflow_version="v001",
        params_json=json.dumps({"input_image": input_ref, "positive_prompt": "a cat"}),
        workflow_json="{}",
    )
    fields = {"status": status}
    if status == "completed":
        fields.update(
            output_files=json.dumps([{"filename": filename, "subfolder": "image",
                                      "type": "output"}]),
            thumbnail_path=thumbnail,
        )
    db.update_generation(prompt_id, **fields)
    return db.get_generation(prompt_id)


def test_fold_upgrades_the_source_row_in_place(tmp_path):
    db = Database(tmp_path / "t.db")
    source = _add_source(db, starred=True)
    key_before = gallery.settings_folder_key(source)
    enhance = _add_enhance(db, "e1", "image/sdxl_t2i_src.png [output]",
                           "image_enhance_00001_.png")

    assert fold_enhancement(db, enhance) == "src"

    upgraded = db.get_generation("src")
    files = gallery.row_output_files(upgraded)
    # The enhanced file leads (previews and thumbnails use it); the original
    # stays listed, reachable and safe from re-import as an orphan.
    assert [f["filename"] for f in files] == \
        ["image_enhance_00001_.png", "sdxl_t2i_src.png"]
    assert json.loads(upgraded["original_files"]) == \
        [{"filename": "sdxl_t2i_src.png", "subfolder": "image", "type": "output"}]
    assert upgraded["thumbnail_path"] == "enh_thumb.jpg"  # shows enhanced pixels
    assert upgraded["starred"] == 1                       # the star survived
    assert is_enhanced_row(upgraded)                      # wears the badge now
    # Same node in the same folder: params and identity untouched.
    assert gallery.settings_folder_key(upgraded) == key_before
    # The transient job row is gone.
    assert db.get_generation("e1") is None


def test_refold_keeps_the_true_original_and_leads_with_the_newest(tmp_path):
    db = Database(tmp_path / "t.db")
    _add_source(db)
    first = _add_enhance(db, "e1", "image/sdxl_t2i_src.png [output]",
                         "image_enhance_00001_.png")
    fold_enhancement(db, first)

    # A deliberate re-enhance runs on the original and folds again.
    second = _add_enhance(db, "e2", "image/sdxl_t2i_src.png [output]",
                          "image_enhance_00002_.png")
    assert fold_enhancement(db, second) == "src"

    upgraded = db.get_generation("src")
    names = [f["filename"] for f in gallery.row_output_files(upgraded)]
    assert names == ["image_enhance_00002_.png", "image_enhance_00001_.png",
                     "sdxl_t2i_src.png"]
    # original_files still names the pre-ANY-enhance file, not the first enhance.
    assert [f["filename"] for f in json.loads(upgraded["original_files"])] == \
        ["sdxl_t2i_src.png"]


def test_fold_leaves_a_sourceless_enhance_alone(tmp_path):
    # The enhanced image's source was deleted: nothing to fold onto, so the row
    # stays as it is (visible and deletable) rather than half-migrated.
    db = Database(tmp_path / "t.db")
    enhance = _add_enhance(db, "e1", "image/sdxl_t2i_gone.png [output]",
                           "image_enhance_00001_.png")
    assert fold_enhancement(db, enhance) is None
    assert db.get_generation("e1") is not None


def test_fold_completed_enhancements_sweeps_only_finished_rows(tmp_path):
    # The startup sweep: folds completions that landed while the app was closed
    # (and the retroactive "Image Enhance generation" rows), leaves in-flight
    # jobs for their live completion and sourceless rows as they are.
    db = Database(tmp_path / "t.db")
    _add_source(db, "src_a", "sdxl_t2i_a.png")
    _add_source(db, "src_b", "sdxl_t2i_b.png")
    _add_enhance(db, "done_a", "image/sdxl_t2i_a.png [output]", "image_enhance_a.png")
    _add_enhance(db, "done_b", "image/sdxl_t2i_b.png [output]", "image_enhance_b.png")
    _add_enhance(db, "running", "image/sdxl_t2i_a.png [output]", "x.png", status="running")
    _add_enhance(db, "orphan", "image/sdxl_t2i_gone.png [output]", "image_enhance_o.png")

    assert fold_completed_enhancements(db) == 2

    assert db.get_generation("done_a") is None
    assert db.get_generation("done_b") is None
    assert db.get_generation("running")["status"] == "running"
    assert db.get_generation("orphan") is not None
    assert is_enhanced_row(db.get_generation("src_a"))
    assert is_enhanced_row(db.get_generation("src_b"))


def test_tree_never_grows_a_folder_for_a_running_enhance(tmp_path):
    # The transient job row shows as an in-flight card on Recents, never as an
    # "Image Enhance" folder in the tree; a completed-but-sourceless orphan
    # still renders, so it can be found and deleted.
    db = Database(tmp_path / "t.db")
    _add_source(db)
    _add_enhance(db, "running", "image/sdxl_t2i_src.png [output]", "x.png",
                 status="running")
    tree = gallery.build_gallery_tree(db.list_generations())
    workflows = [w.workflow_name for m in tree for w in m.workflow_groups]
    assert workflows == ["sdxl_t2i"]

    _add_enhance(db, "orphan", "image/sdxl_t2i_gone.png [output]",
                 "image_enhance_o.png")
    tree = gallery.build_gallery_tree(db.list_generations())
    workflows = [w.workflow_name for m in tree for w in m.workflow_groups]
    assert sorted(workflows) == ["image_enhance", "sdxl_t2i"]


def test_original_files_survives_capture_and_restore(tmp_path):
    # The undoable-delete path restores rows verbatim; the enhanced marker (and
    # with it the badge and the original's listing) must survive the round trip.
    db = Database(tmp_path / "t.db")
    _add_source(db)
    fold_enhancement(db, _add_enhance(db, "e1", "image/sdxl_t2i_src.png [output]",
                                      "image_enhance_00001_.png"))
    row = db.get_generation("src")
    db.delete_generation("src")
    db.restore_generation(row)
    assert db.get_generation("src")["original_files"] == row["original_files"]


def test_metadata_labels_the_pre_enhance_file_original(tmp_path):
    from origenerator.generation_metadata import build_sections

    db = Database(tmp_path / "t.db")
    _add_source(db)
    fold_enhancement(db, _add_enhance(db, "e1", "image/sdxl_t2i_src.png [output]",
                                      "image_enhance_00001_.png"))
    (basic,) = build_sections(db.get_generation("src"))
    labels = [(item.label, item.value) for item in basic.items]
    assert ("File", "image/image_enhance_00001_.png") == labels[0]
    assert ("Original", "image/sdxl_t2i_src.png") == labels[1]
