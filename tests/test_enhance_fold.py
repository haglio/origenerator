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


def test_each_version_carries_its_own_file_row(tmp_path):
    # The file information is per enhancement, so it belongs to the level that
    # made the file rather than to one block at the top of the pane. The top
    # block is then left with nothing to say about an image at all.
    from origenerator.generation_metadata import build_sections, file_item

    db = Database(tmp_path / "t.db")
    _add_source(db)
    fold_enhancement(db, _add_enhance(db, "e1", "image/sdxl_t2i_src.png [output]",
                                      "image_enhance_00001_.png"))
    row = db.get_generation("src")
    levels = gallery.displayed_levels(row)
    assert [(lvl.label, file_item(lvl.file).value) for lvl in levels] == [
        ("Enhance 1", "image/image_enhance_00001_.png"),
        ("Original", "image/sdxl_t2i_src.png"),
    ]
    assert build_sections(row) == []


# --- an enhancement the live app never recorded, arriving as a bare file -----

def _enhance_graph(*, scale_by=0.5, steps=20, denoise=0.15,
                   checkpoint="example_xl_v1.safetensors",
                   upscale_model="4xExample_v1.pt", detectors=()):
    """The graph the enhance workflow embeds in every file it saves, as the
    import scan reads it back."""
    graph = {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": checkpoint}},
        "4": {"class_type": "UpscaleModelLoader",
              "inputs": {"model_name": upscale_model}},
        "5": {"class_type": "ImageUpscaleWithModel",
              "inputs": {"upscale_model": ["4", 0], "image": ["2", 0]}},
        "6": {"class_type": "ImageScaleBy",
              "inputs": {"image": ["5", 0], "upscale_method": "lanczos",
                         "scale_by": scale_by}},
        "9": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "seed": 7, "steps": steps,
                         "cfg": 7.5, "sampler_name": "euler",
                         "scheduler": "normal", "denoise": denoise}},
        "12": {"class_type": "SaveImage",
               "inputs": {"images": ["11", 0],
                          "filename_prefix": "image/image_enhance"}},
    }
    # Three nodes per part fixed, exactly as the workflow lays them out: the
    # detailer names no part, so which one it redrew is only readable back
    # through the segs it sampled and the detector that found them.
    for offset, (detector, fix_denoise) in enumerate(detectors):
        base = 13 + offset * 3
        graph[str(base)] = {"class_type": "UltralyticsDetectorProvider",
                            "inputs": {"model_name": f"bbox/{detector}"}}
        graph[str(base + 1)] = {"class_type": "BboxDetectorSEGS",
                                "inputs": {"bbox_detector": [str(base), 0]}}
        graph[str(base + 2)] = {"class_type": "DetailerForEach",
                                "inputs": {"segs": [str(base + 1), 0],
                                           "denoise": fix_denoise}}
    return graph


def _add_reconstructed_enhance(db, prompt_id, input_ref, filename, **graph_kwargs):
    """What the import scan makes of an enhanced file it finds on disk with no
    row claiming it: an image generation of its own, the workflow read off the
    graph as the img2img pass it looks like, and the tail's numbers under the
    generic sampler names."""
    graph = _enhance_graph(**graph_kwargs)
    sampler = graph["9"]["inputs"]
    db.insert_generation(
        prompt_id=prompt_id, workflow_name="sdxl_t2i", workflow_version="imported",
        positive_prompt="a cat", seed=sampler["seed"],
        params_json=json.dumps({
            "positive_prompt": "a cat", "input_image": input_ref,
            "checkpoint": graph["1"]["inputs"]["ckpt_name"],
            "steps": sampler["steps"], "denoise": sampler["denoise"],
            "cfg": sampler["cfg"], "sampler_name": "euler", "scheduler": "normal",
            "seed": sampler["seed"],
        }),
        workflow_json=json.dumps(graph),
        source="imported",
    )
    db.update_generation(
        prompt_id, status="completed", thumbnail_path="imported_thumb.jpg",
        output_files=json.dumps([{"filename": filename, "subfolder": "image",
                                  "type": "output"}]))
    return db.get_generation(prompt_id)


def test_a_reconstructed_enhance_is_recognized_by_its_file(tmp_path):
    # What names an enhancement is the file the enhance workflow wrote, not the
    # workflow the import scan guessed from the graph — which for an enhance is
    # an ordinary low-denoise img2img and reads as one.
    db = Database(tmp_path / "t.db")
    _add_source(db)
    stray = _add_reconstructed_enhance(db, "i1", "image/sdxl_t2i_src.png [output]",
                                       "image_enhance_00001_.png")
    assert gallery.is_enhance_product_row(stray)
    # An ordinary generation is not, whatever it was made from; nor is an image
    # already folded into — there the enhancement is a level, not the row.
    assert not gallery.is_enhance_product_row(db.get_generation("src"))
    fold_enhancement(db, stray)
    assert not gallery.is_enhance_product_row(db.get_generation("src"))


def test_sweep_folds_the_enhancement_the_import_scan_rebuilt(tmp_path):
    # A branch session's enhance folds in the worktree database, which adoption
    # never carries home (a fold creates no row to adopt), so the enhanced file
    # reaches the live install bare and the scan rebuilds it as a standalone
    # image — pointing a start-frame tile at the very picture it is a version of.
    db = Database(tmp_path / "t.db")
    _add_source(db, starred=True)
    _add_reconstructed_enhance(db, "i1", "image/sdxl_t2i_src.png [output]",
                               "image_enhance_00001_.png")

    assert fold_completed_enhancements(db) == 1

    assert db.get_generation("i1") is None  # no separate image any more
    upgraded = db.get_generation("src")
    assert [f["filename"] for f in gallery.row_output_files(upgraded)] == \
        ["image_enhance_00001_.png", "sdxl_t2i_src.png"]
    assert upgraded["starred"] == 1
    assert is_enhanced_row(upgraded)
    assert [lvl.label for lvl in gallery.displayed_levels(upgraded)] == \
        ["Enhance 1", "Original"]


def test_a_rebuilt_level_keeps_the_settings_that_made_it(tmp_path):
    # The row's own params name the sampler numbers generically and the upscale
    # not at all, so the level reads its knobs off the graph that ran: the scale
    # is what the 4x model's output was taken back down to, and the detail pass
    # is there iff its detector nodes are.
    db = Database(tmp_path / "t.db")
    _add_source(db)
    _add_reconstructed_enhance(
        db, "i1", "image/sdxl_t2i_src.png [output]", "image_enhance_00001_.png",
        scale_by=0.375, steps=24, denoise=0.25,
        checkpoint="example_xl_v1.safetensors", upscale_model="4xExample_v1.pt",
        detectors=(("face_example.pt", 0.45), ("hand_example.pt", 0.6)))
    fold_completed_enhancements(db)

    level = gallery.displayed_levels(db.get_generation("src"))[0]
    assert level.params == {
        "checkpoint": "example_xl_v1.safetensors",
        "upscale_model": "4xExample_v1.pt",
        "enhance_scale": 1.5, "enhance_steps": 24, "enhance_denoise": 0.25,
        "enhance_detail_fixes": {"faces": 0.45, "hands": 0.6},
    }


def test_sweep_stacks_a_rebuilt_chain_oldest_first(tmp_path):
    # An enhance made from an enhanced file resolves only once the file it ran
    # on has been folded onto the image, so the sweep works forwards.
    db = Database(tmp_path / "t.db")
    _add_source(db)
    _add_reconstructed_enhance(db, "i1", "image/sdxl_t2i_src.png [output]",
                               "image_enhance_00001_.png")
    _add_reconstructed_enhance(db, "i2", "image/image_enhance_00001_.png [output]",
                               "image_enhance_00002_.png")

    assert fold_completed_enhancements(db) == 2

    upgraded = db.get_generation("src")
    assert [f["filename"] for f in gallery.row_output_files(upgraded)] == \
        ["image_enhance_00002_.png", "image_enhance_00001_.png", "sdxl_t2i_src.png"]
    assert [lvl.label for lvl in gallery.displayed_levels(upgraded)] == \
        ["Enhance 2", "Enhance 1", "Original"]


def test_sweep_leaves_an_ordinary_image_alone(tmp_path):
    # A hand-run img2img in ComfyUI is a picture of its own however low its
    # denoise: the enhance workflow did not write it, and nothing folds it away.
    db = Database(tmp_path / "t.db")
    _add_source(db)
    kept = _add_reconstructed_enhance(db, "i1", "image/sdxl_t2i_src.png [output]",
                                      "sdxl_refine_00001_.png")
    assert not gallery.is_enhance_product_row(kept)
    assert fold_completed_enhancements(db) == 0
    assert db.get_generation("i1") is not None
