from __future__ import annotations

import json
from typing import NamedTuple

from origenerator import gallery
from origenerator.db import Database, NewGeneration
from origenerator.gallery import (
    fold_completed_enhancements,
    fold_enhancement,
    is_enhanced_row,
)
from origenerator.generation_metadata import basic_facts, file_item
from origenerator.generation_state import GenerationSource
from origenerator.output_places import OutputPlaces


def _add_source(db, prompt_id="src", filename="sdxl_t2i_src.png", favorite=False):
    db.insert_generation(NewGeneration(
        prompt_id=prompt_id, workflow_name="sdxl_t2i", workflow_version="v002",
        positive_prompt="a cat", seed=1,
        params_json=json.dumps({"positive_prompt": "a cat", "steps": 30, "seed": 1}),
        workflow_json="{}",
    ))
    db.update_generation(prompt_id, status="completed", thumbnail_path="src_thumb.jpg",
                         output_files=json.dumps([{"filename": filename,
                                                   "subfolder": "image",
                                                   "type": "output"}]))
    if favorite:
        db.set_generation_favorite(prompt_id, True)
    return db.get_generation(prompt_id)


def _add_enhance(db, prompt_id, input_ref, filename, status="completed"):
    db.insert_generation(NewGeneration(
        prompt_id=prompt_id, workflow_name="image_enhance", workflow_version="v001",
        params_json=json.dumps({"input_image": input_ref, "positive_prompt": "a cat"}),
        workflow_json="{}",
    ))
    fields = {"status": status}
    if status == "completed":
        fields.update(
            output_files=json.dumps([{"filename": filename, "subfolder": "image",
                                      "type": "output"}]),
            thumbnail_path="enh_thumb.jpg",
        )
    db.update_generation(prompt_id, **fields)
    return db.get_generation(prompt_id)


def test_fold_upgrades_the_source_row_in_place(tmp_path):
    db = Database(tmp_path / "t.db")
    source = _add_source(db, favorite=True)
    key_before = gallery.settings_folder_key(source)
    enhance = _add_enhance(db, "e1", "image/sdxl_t2i_src.png [output]",
                           "image_enhance_00001_.png")

    assert fold_enhancement(db, enhance) == "src"

    upgraded = db.get_generation("src")
    files = gallery.row_output_files(upgraded)
    assert [f["filename"] for f in files] == \
        ["image_enhance_00001_.png", "sdxl_t2i_src.png"]
    assert json.loads(upgraded["original_files"]) == \
        [{"filename": "sdxl_t2i_src.png", "subfolder": "image", "type": "output"}]
    assert upgraded["thumbnail_path"] == "enh_thumb.jpg"
    assert upgraded["starred"] == 1
    assert is_enhanced_row(upgraded)
    assert gallery.settings_folder_key(upgraded) == key_before
    assert db.get_generation("e1") is None


def _latest(db):
    return [row["prompt_id"] for row in gallery.recent_generations(db.list_generations())]


def test_an_enhancement_the_backfill_made_leaves_its_image_where_it_sat_in_latest(tmp_path):
    db = Database(tmp_path / "t.db")
    _add_source(db)
    _add_source(db, prompt_id="made later", filename="sdxl_t2i_later.png")
    _add_enhance(db, "e1", "image/sdxl_t2i_src.png [output]", "image_enhance_00001_.png")
    db.set_source("e1", GenerationSource.BACKFILL)

    fold_enhancement(db, db.get_generation("e1"))

    assert _latest(db) == ["made later", "src"]


def test_the_places_an_enhancements_fixes_found_stay_with_its_file_once_folded(tmp_path):
    db = Database(tmp_path / "t.db")
    _add_source(db)
    _add_enhance(db, "e1", "image/sdxl_t2i_src.png [output]", "image_enhance_00001_.png")
    places = [{"part": "faces", "left": 0.1, "top": 0.1, "right": 0.3, "bottom": 0.5}]
    db.update_generation("e1", output_files=json.dumps([
        {"filename": "image_enhance_00001_.png", "subfolder": "image", "type": "output",
         "points_of_interest": places}]))

    fold_enhancement(db, db.get_generation("e1"))

    enhanced, original = gallery.row_output_files(db.get_generation("src"))
    assert enhanced["points_of_interest"] == places
    assert "points_of_interest" not in original


def test_refold_keeps_the_true_original_and_leads_with_the_newest(tmp_path):
    db = Database(tmp_path / "t.db")
    _add_source(db)
    first = _add_enhance(db, "e1", "image/sdxl_t2i_src.png [output]",
                         "image_enhance_00001_.png")
    fold_enhancement(db, first)

    second = _add_enhance(db, "e2", "image/sdxl_t2i_src.png [output]",
                          "image_enhance_00002_.png")
    assert fold_enhancement(db, second) == "src"

    upgraded = db.get_generation("src")
    names = [f["filename"] for f in gallery.row_output_files(upgraded)]
    assert names == ["image_enhance_00002_.png", "image_enhance_00001_.png",
                     "sdxl_t2i_src.png"]
    assert [f["filename"] for f in json.loads(upgraded["original_files"])] == \
        ["sdxl_t2i_src.png"]


def test_an_enhancement_folded_again_after_a_stop_between_its_saves_is_listed_once(tmp_path):
    db = Database(tmp_path / "t.db")
    _add_source(db)
    enhance = _add_enhance(db, "e1", "image/sdxl_t2i_src.png [output]",
                           "image_enhance_00001_.png")
    fold_enhancement(db, enhance)
    db.restore_generation(enhance)

    fold_completed_enhancements(db)

    upgraded = db.get_generation("src")
    assert [f["filename"] for f in gallery.row_output_files(upgraded)] == \
        ["image_enhance_00001_.png", "sdxl_t2i_src.png"]
    assert [entry["filename"] for entry in json.loads(upgraded["enhance_history"])] == \
        ["image_enhance_00001_.png"]
    assert db.get_generation("e1") is None


def test_fold_records_where_the_run_fell_in_the_librarys_order(tmp_path):
    db = Database(tmp_path / "t.db")
    _add_source(db)
    enhance = _add_enhance(db, "e1", "image/sdxl_t2i_src.png [output]",
                           "image_enhance_00001_.png")

    fold_enhancement(db, enhance)

    (version,) = json.loads(db.get_generation("src")["enhance_history"])
    assert version["run_id"] == enhance["id"]
    assert gallery.recent_generations(db.list_generations())[0]["prompt_id"] == "src"


def test_fold_records_when_the_run_finished_since_the_row_that_said_so_is_deleted(tmp_path):
    db = Database(tmp_path / "t.db")
    _add_source(db)
    _add_enhance(db, "e1", "image/sdxl_t2i_src.png [output]", "image_enhance_00001_.png")
    db.update_generation("e1", completed_at="2026-09-12T19:40:00+00:00")

    fold_enhancement(db, db.get_generation("e1"))

    (version,) = json.loads(db.get_generation("src")["enhance_history"])
    assert version["finished_at"] == "2026-09-12T19:40:00+00:00"


def test_fold_lands_on_the_image_the_run_was_stamped_with(tmp_path):
    db = Database(tmp_path / "t.db")
    _add_source(db, "first", filename="sdxl_t2i_twin.png")
    _add_source(db, "second", filename="sdxl_t2i_twin.png")
    _add_enhance(db, "e1", "image/sdxl_t2i_twin.png [output]", "image_enhance_e1.png")
    db.set_enhance_target("e1", "second")

    assert fold_enhancement(db, db.get_generation("e1")) == "second"

    assert is_enhanced_row(db.get_generation("second"))
    assert not is_enhanced_row(db.get_generation("first"))
    assert db.get_generation("e1") is None


def test_a_stamp_naming_a_deleted_image_folds_nothing(tmp_path):
    db = Database(tmp_path / "t.db")
    _add_source(db, "lookalike", filename="sdxl_t2i_twin.png")
    _add_enhance(db, "e1", "image/sdxl_t2i_twin.png [output]", "image_enhance_e1.png")
    db.set_enhance_target("e1", "deleted-long-ago")

    assert fold_enhancement(db, db.get_generation("e1")) is None
    assert not is_enhanced_row(db.get_generation("lookalike"))


def test_an_unstamped_run_still_folds_by_the_file_it_read(tmp_path):
    db = Database(tmp_path / "t.db")
    _add_source(db, "src")
    enhance = _add_enhance(db, "e1", "image/sdxl_t2i_src.png [output]", "image_enhance_e1.png")
    assert gallery.enhance_target_id(enhance, db.list_generations()) == "src"


def test_a_stamped_run_is_awaited_by_id_not_by_file(tmp_path):
    db = Database(tmp_path / "t.db")
    first = _add_source(db, "first", filename="sdxl_t2i_twin.png")
    second = _add_source(db, "second", filename="sdxl_t2i_twin.png")
    _add_enhance(db, "e1", "image/sdxl_t2i_twin.png [output]", "", status="running")
    db.set_enhance_target("e1", "second")

    awaiting = gallery.rows_awaiting_enhancement([first, second], db.list_generations())

    assert [r["prompt_id"] for r in awaiting] == ["first"]


def test_a_stamped_run_moves_its_own_image_up_the_collection(tmp_path):
    db = Database(tmp_path / "t.db")
    _add_source(db, "first", filename="sdxl_t2i_twin.png")
    _add_source(db, "second", filename="sdxl_t2i_twin.png")
    _add_enhance(db, "e1", "image/sdxl_t2i_twin.png [output]", "", status="running")
    db.set_enhance_target("e1", "second")
    rows = db.list_generations()
    run_id = next(r["id"] for r in rows if r["prompt_id"] == "e1")

    lifted = {image: run for image, (_finished, run) in gallery.enhancement_recency(rows).items()}
    assert lifted == {"second": run_id}


def test_a_run_id_this_table_never_issued_comes_off_the_version(tmp_path):
    db = Database(tmp_path / "t.db")
    _add_source(db, "adopted")
    db.update_generation("adopted", enhance_history=json.dumps(
        [{"filename": "e.png", "params": {"enhance_scale": 2.0},
          "run_id": db.highest_id_issued() + 30}]))

    assert gallery.disown_foreign_runs(db) == 1

    version, = json.loads(db.get_generation("adopted")["enhance_history"])
    assert version["run_id"] is None
    assert version["params"] == {"enhance_scale": 2.0}
    assert version["filename"] == "e.png"
    assert gallery.disown_foreign_runs(db) == 0


def test_a_run_this_table_really_issued_is_left_where_it_is(tmp_path):
    db = Database(tmp_path / "t.db")
    _add_source(db, "mine")
    _add_enhance(db, "transient", "image/sdxl_t2i_src.png [output]", "e.png")
    ran_as = db.get_generation("transient")["id"]
    db.delete_generation("transient")
    db.update_generation("mine", enhance_history=json.dumps(
        [{"filename": "e.png", "params": {}, "run_id": ran_as}]))

    assert gallery.disown_foreign_runs(db) == 0

    version, = json.loads(db.get_generation("mine")["enhance_history"])
    assert version["run_id"] == ran_as


def test_fold_leaves_a_sourceless_enhance_alone(tmp_path):
    db = Database(tmp_path / "t.db")
    enhance = _add_enhance(db, "e1", "image/sdxl_t2i_gone.png [output]",
                           "image_enhance_00001_.png")
    assert fold_enhancement(db, enhance) is None
    assert db.get_generation("e1") is not None


def test_fold_completed_enhancements_sweeps_only_finished_rows(tmp_path):
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


def test_an_enhancement_whose_image_is_gone_is_one_to_scrap(tmp_path):
    output_dir = tmp_path / "output"
    (output_dir / "image").mkdir(parents=True)
    (output_dir / "image" / "sdxl_t2i_here.png").write_bytes(b"still here")
    db = Database(tmp_path / "t.db")
    _add_enhance(db, "of_a_deleted_image", "image/sdxl_t2i_gone.png [output]", "e1.png")
    _add_enhance(db, "of_an_image_on_disk", "image/sdxl_t2i_here.png [output]", "e2.png")
    _add_enhance(db, "still_running", "image/sdxl_t2i_gone.png [output]", "e3.png",
                 status="running")

    gone = gallery.enhancements_of_images_gone(
        db.list_generations(), places=OutputPlaces.in_one_folder(output_dir), input_dir=tmp_path / "input")

    assert [row["prompt_id"] for row in gone] == ["of_a_deleted_image"]


def test_tree_never_grows_a_folder_for_a_running_enhance(tmp_path):
    db = Database(tmp_path / "t.db")
    _add_source(db)
    _add_enhance(db, "running", "image/sdxl_t2i_src.png [output]", "x.png",
                 status="running")
    (images,) = gallery.build_gallery_tree(db.list_generations())
    assert [w.workflow_name for w in images.children] == ["sdxl_t2i"]

    _add_enhance(db, "orphan", "image/sdxl_t2i_gone.png [output]",
                 "image_enhance_o.png")
    (images,) = gallery.build_gallery_tree(db.list_generations())
    assert sorted(w.workflow_name for w in images.children) == ["image_enhance", "sdxl_t2i"]


def test_original_files_survives_capture_and_restore(tmp_path):
    db = Database(tmp_path / "t.db")
    _add_source(db)
    fold_enhancement(db, _add_enhance(db, "e1", "image/sdxl_t2i_src.png [output]",
                                      "image_enhance_00001_.png"))
    row = db.get_generation("src")
    db.delete_generation("src")
    db.restore_generation(row)
    assert db.get_generation("src")["original_files"] == row["original_files"]


def test_each_version_carries_its_own_file_row(tmp_path):
    db = Database(tmp_path / "t.db")
    _add_source(db)
    fold_enhancement(db, _add_enhance(db, "e1", "image/sdxl_t2i_src.png [output]",
                                      "image_enhance_00001_.png"))
    row = db.get_generation("src")
    versions = gallery.displayed_versions(row)
    assert [(lvl.label, file_item(lvl.file).value) for lvl in versions] == [
        ("Enhancement 1/1", "image/image_enhance_00001_.png"),
        ("Original", "image/sdxl_t2i_src.png"),
    ]
    assert basic_facts(row) is None


class _EnhanceLook(NamedTuple):
    scale_by: float = 0.5
    steps: int = 20
    denoise: float = 0.15
    checkpoint: str = "example_xl_v1.safetensors"
    upscale_model: str = "4xExample_v1.pt"
    detectors: tuple = ()


_USUAL_LOOK = _EnhanceLook()


def _enhance_graph(look):
    scale_by, steps, denoise, checkpoint, upscale_model, detectors = look
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


def _add_reconstructed_enhance(db, prompt_id, input_ref, filename, look=_USUAL_LOOK):
    graph = _enhance_graph(look)
    sampler = graph["9"]["inputs"]
    db.insert_generation(NewGeneration(
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
    ))
    db.update_generation(
        prompt_id, status="completed", thumbnail_path="imported_thumb.jpg",
        output_files=json.dumps([{"filename": filename, "subfolder": "image",
                                  "type": "output"}]))
    return db.get_generation(prompt_id)


def test_a_reconstructed_enhance_is_recognized_by_its_file(tmp_path):
    db = Database(tmp_path / "t.db")
    _add_source(db)
    stray = _add_reconstructed_enhance(db, "i1", "image/sdxl_t2i_src.png [output]",
                                       "image_enhance_00001_.png")
    assert gallery.is_enhance_product_row(stray)
    assert not gallery.is_enhance_product_row(db.get_generation("src"))
    fold_enhancement(db, stray)
    assert not gallery.is_enhance_product_row(db.get_generation("src"))


def test_sweep_folds_the_enhancement_the_import_scan_rebuilt(tmp_path):
    db = Database(tmp_path / "t.db")
    _add_source(db, favorite=True)
    _add_reconstructed_enhance(db, "i1", "image/sdxl_t2i_src.png [output]",
                               "image_enhance_00001_.png")

    assert fold_completed_enhancements(db) == 1

    assert db.get_generation("i1") is None
    upgraded = db.get_generation("src")
    assert [f["filename"] for f in gallery.row_output_files(upgraded)] == \
        ["image_enhance_00001_.png", "sdxl_t2i_src.png"]
    assert upgraded["starred"] == 1
    assert is_enhanced_row(upgraded)
    assert [lvl.label for lvl in gallery.displayed_versions(upgraded)] == \
        ["Enhancement 1/1", "Original"]


def test_a_rebuilt_version_keeps_the_settings_that_made_it(tmp_path):
    db = Database(tmp_path / "t.db")
    _add_source(db)
    _add_reconstructed_enhance(
        db, "i1", "image/sdxl_t2i_src.png [output]", "image_enhance_00001_.png",
        _EnhanceLook(scale_by=0.375, steps=24, denoise=0.25,
                     detectors=(("face_example.pt", 0.45), ("hand_example.pt", 0.6))))
    fold_completed_enhancements(db)

    version = gallery.displayed_versions(db.get_generation("src"))[0]
    assert version.params == {
        "checkpoint": "example_xl_v1.safetensors",
        "upscale_model": "4xExample_v1.pt",
        "enhance_scale": 1.5, "enhance_steps": 24, "enhance_denoise": 0.25,
        "enhance_detail_fixes": {"faces": 0.45, "hands": 0.6},
    }


def test_sweep_stacks_a_rebuilt_chain_oldest_first(tmp_path):
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
    assert [lvl.label for lvl in gallery.displayed_versions(upgraded)] == \
        ["Enhancement 2/2", "Enhancement 1/2", "Original"]


def test_sweep_leaves_an_ordinary_image_alone(tmp_path):
    db = Database(tmp_path / "t.db")
    _add_source(db)
    kept = _add_reconstructed_enhance(db, "i1", "image/sdxl_t2i_src.png [output]",
                                      "sdxl_refine_00001_.png")
    assert not gallery.is_enhance_product_row(kept)
    assert fold_completed_enhancements(db) == 0
    assert db.get_generation("i1") is not None


def test_a_folded_images_plain_version_is_superseded_by_its_enhancement(tmp_path):
    db = Database(tmp_path / "t.db")
    plain = _add_source(db)
    fold_enhancement(db, _add_enhance(db, "enh", "image/sdxl_t2i_src.png [output]",
                                      "image_enhance_00001_.png"))
    enhanced = db.get_generation("src")

    assert gallery.enhanced_version_of("image/sdxl_t2i_src.png [output]", enhanced) \
        == "image/image_enhance_00001_.png [output]"
    assert gallery.enhanced_version_of("image/image_enhance_00001_.png [output]",
                                       enhanced) is None
    assert gallery.enhanced_version_of("image/sdxl_t2i_src.png [output]", plain) is None
