import json

from origenerator.gallery import (
    build_gallery_tree,
    find_source_image_id,
    media_type_of_row,
    settings_signature,
)


def _row(**kw):
    base = {
        "prompt_id": "p",
        "workflow_name": "sdxl_t2i",
        "params_json": "{}",
        "output_files": None,
    }
    base.update(kw)
    return base


def test_media_type_of_row_prefers_workflow_registry():
    assert media_type_of_row(_row(workflow_name="sdxl_t2i")) == "image"
    assert media_type_of_row(_row(workflow_name="wan22_i2v")) == "video"
    assert media_type_of_row(_row(workflow_name="wan22_flf2v_loop")) == "video"


def test_media_type_of_row_falls_back_to_output_filename_for_unknown_workflow():
    img = _row(workflow_name="unknown",
               output_files=json.dumps([{"filename": "mystery_00001.png"}]))
    vid = _row(workflow_name="unknown",
               output_files=json.dumps([{"filename": "mystery_00001.mp4"}]))
    assert media_type_of_row(img) == "image"
    assert media_type_of_row(vid) == "video"


def test_settings_signature_ignores_seeds_but_keeps_other_params():
    a = json.dumps({"steps": 50, "cfg": 7.5, "seed": 1, "noise_seed": 99})
    b = json.dumps({"cfg": 7.5, "steps": 50, "seed": 2, "noise_seed": 7})
    c = json.dumps({"steps": 40, "cfg": 7.5, "seed": 1})
    # Same settings, different seeds -> identical signature (order-independent).
    assert settings_signature(a) == settings_signature(b)
    # A real setting differs -> different signature.
    assert settings_signature(a) != settings_signature(c)


def test_settings_signature_tolerates_missing_or_invalid_params():
    assert settings_signature(None) == settings_signature("{}")
    assert settings_signature("not json") == settings_signature("{}")


def test_find_source_image_matches_i2v_input_to_an_image_row_by_basename():
    image = _row(
        prompt_id="img-1",
        workflow_name="sdxl_t2i",
        output_files=json.dumps([{"filename": "sdxl_t2i_00007_.png",
                                  "subfolder": "image"}]),
    )
    other_image = _row(
        prompt_id="img-2",
        workflow_name="sdxl_t2i",
        output_files=json.dumps([{"filename": "sdxl_t2i_00099_.png"}]),
    )
    video = _row(
        prompt_id="vid-1",
        workflow_name="wan22_i2v",
        params_json=json.dumps({"input_image": "sdxl_t2i_00007_.png"}),
    )
    assert find_source_image_id(video, [image, other_image]) == "img-1"


def test_find_source_image_returns_none_without_a_match():
    no_input = _row(prompt_id="vid", workflow_name="wan22_i2v", params_json="{}")
    assert find_source_image_id(no_input, []) is None

    unmatched = _row(prompt_id="vid", workflow_name="wan22_i2v",
                     params_json=json.dumps({"input_image": "elsewhere.png"}))
    image = _row(prompt_id="img",
                 output_files=json.dumps([{"filename": "sdxl_t2i_00007_.png"}]))
    assert find_source_image_id(unmatched, [image]) is None


def _img(prompt_id, prompt, steps, seed):
    return _row(
        prompt_id=prompt_id,
        workflow_name="sdxl_t2i",
        params_json=json.dumps({"positive_prompt": prompt, "steps": steps, "seed": seed}),
        output_files=json.dumps([{"filename": f"sdxl_t2i_{prompt_id}.png"}]),
    )


def test_build_gallery_tree_nests_media_then_workflow_then_settings():
    rows = [
        _img("i1", "a cat", 50, 1),   # same settings as i2, different seed
        _img("i2", "a cat", 50, 2),
        _img("i3", "a cat", 40, 1),   # different steps -> its own settings group
        _row(prompt_id="v1", workflow_name="wan22_i2v",
             params_json=json.dumps({"positive_prompt": "dance", "seed": 5}),
             output_files=json.dumps([{"filename": "wan22_i2v_00001_.mp4"}])),
    ]

    tree = build_gallery_tree(rows)
    media = {m.media_type: m for m in tree}
    assert set(media) == {"image", "video"}

    sdxl_groups = media["image"].workflow_groups
    assert [w.workflow_name for w in sdxl_groups] == ["sdxl_t2i"]
    settings = sdxl_groups[0].settings_groups
    assert len(settings) == 2
    assert {r["prompt_id"] for r in settings[0].rows} == {"i1", "i2"}
    assert {r["prompt_id"] for r in settings[1].rows} == {"i3"}

    video = media["video"]
    assert [w.workflow_name for w in video.workflow_groups] == ["wan22_i2v"]
    assert len(video.workflow_groups[0].settings_groups) == 1


def test_build_gallery_tree_labels_workflow_with_display_name():
    tree = build_gallery_tree([_img("i1", "a cat", 50, 1)])
    wf = tree[0].workflow_groups[0]
    assert wf.label == "SDXL Text-to-Image"
    assert tree[0].label == "Images"


def test_settings_group_labels_disambiguate_same_prompt_different_params():
    # Same prompt, different steps -> two folders that must not share a label.
    tree = build_gallery_tree([_img("i1", "a cat", 50, 1),
                               _img("i2", "a cat", 40, 2)])
    labels = [sg.label for sg in tree[0].workflow_groups[0].settings_groups]
    assert len(labels) == 2
    assert labels[0] != labels[1]
    assert all("a cat" in label for label in labels)
    # the distinguishing param is surfaced so the folders are tellable apart
    assert any("steps" in label for label in labels)


def test_settings_group_label_omits_params_when_only_one_group():
    # A lone settings folder needs no disambiguating suffix.
    tree = build_gallery_tree([_img("i1", "a cat", 50, 1),
                               _img("i2", "a cat", 50, 2)])
    (only,) = tree[0].workflow_groups[0].settings_groups
    assert only.label == "a cat"
