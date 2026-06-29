import json

from origenerator.gallery import (
    build_gallery_tree,
    child_groups,
    find_source_image_id,
    media_type_of_row,
    resolve_preview,
    rows_under,
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


def test_media_type_of_row_uses_actual_output_file_over_workflow_type():
    # A row tagged with a video workflow whose real output is an image is an
    # image — many imported stills land under video prefixes and must not show
    # up in the Videos folder.
    mislabeled = _row(workflow_name="wan22_flf2v_loop",
                      output_files=json.dumps([{"filename": "flf2v_loop_00001_.png"}]))
    assert media_type_of_row(mislabeled) == "image"

    real_video = _row(workflow_name="wan22_i2v",
                      output_files=json.dumps([{"filename": "wan22_i2v_00001_.mp4"}]))
    assert media_type_of_row(real_video) == "video"


def test_media_type_of_row_falls_back_to_registry_without_output_files():
    # Pending rows have no file yet; the workflow's declared type stands in.
    assert media_type_of_row(_row(workflow_name="sdxl_t2i")) == "image"
    assert media_type_of_row(_row(workflow_name="wan22_i2v")) == "video"


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


def test_build_gallery_tree_assigns_stable_folder_keys():
    tree = build_gallery_tree([_img("i1", "a cat", 50, 1)])
    media = tree[0]
    assert media.key == "image"
    workflow = media.workflow_groups[0]
    assert workflow.key == "image/sdxl_t2i"
    settings = workflow.settings_groups[0]
    assert settings.key.startswith("image/sdxl_t2i/")

    # The settings key is derived from the signature, so it is stable across
    # rebuilds (what lets a rename/star stick to the same folder).
    again = build_gallery_tree([_img("i9", "a cat", 50, 7)])
    assert again[0].workflow_groups[0].settings_groups[0].key == settings.key


def test_build_gallery_tree_applies_custom_names_and_floats_stars_first():
    rows = [_img("i1", "a cat", 50, 1), _img("i2", "a dog", 50, 1)]
    plain = build_gallery_tree(rows)
    cat, dog = plain[0].workflow_groups[0].settings_groups  # newest-first: cat, dog

    meta = {dog.key: {"custom_name": "Doggos", "starred": True}}
    starred_tree = build_gallery_tree(rows, meta)
    settings = starred_tree[0].workflow_groups[0].settings_groups

    assert settings[0].label == "Doggos"      # custom name applied
    assert settings[0].starred is True
    assert settings[0].key == dog.key         # and it floated above the cat
    assert settings[1].starred is False


def test_child_groups_and_rows_under_walk_the_tree():
    rows = [_img("i1", "a cat", 50, 1), _img("i2", "a cat", 50, 2),
            _img("i3", "a dog", 50, 1)]
    media = build_gallery_tree(rows)[0]

    workflows = child_groups(media)
    assert [w.workflow_name for w in workflows] == ["sdxl_t2i"]
    settings = child_groups(workflows[0])
    assert len(settings) == 2
    assert child_groups(settings[0]) == []  # a leaf has no child folders

    assert {r["prompt_id"] for r in rows_under(media)} == {"i1", "i2", "i3"}
    assert {r["prompt_id"] for r in rows_under(settings[0])} == {"i1", "i2"}


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


def test_resolve_preview_returns_full_image_file(tmp_path):
    out = tmp_path / "output"
    (out / "image").mkdir(parents=True)
    full = out / "image" / "sdxl_t2i_1_.png"
    full.write_bytes(b"x")
    row = _row(output_files=json.dumps([{"filename": "sdxl_t2i_1_.png",
                                         "subfolder": "image"}]))
    assert resolve_preview(row, out) == (full, "image")


def test_resolve_preview_returns_full_video_file(tmp_path):
    out = tmp_path / "output"
    (out / "video").mkdir(parents=True)
    full = out / "video" / "wan22_i2v_1_.mp4"
    full.write_bytes(b"x")
    row = _row(output_files=json.dumps([{"filename": "wan22_i2v_1_.mp4",
                                         "subfolder": "video"}]))
    assert resolve_preview(row, out) == (full, "video")


def test_resolve_preview_falls_back_to_thumbnail_when_output_missing(tmp_path):
    out = tmp_path / "output"
    out.mkdir()
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"x")
    # Output references a video that is not on disk; the thumbnail still previews.
    row = _row(output_files=json.dumps([{"filename": "gone_1_.mp4", "subfolder": "video"}]),
               thumbnail_path=str(thumb))
    assert resolve_preview(row, out) == (thumb, "image")


def test_resolve_preview_returns_none_when_nothing_exists(tmp_path):
    out = tmp_path / "output"
    out.mkdir()
    row = _row(output_files=json.dumps([{"filename": "gone.png"}]),
               thumbnail_path=str(tmp_path / "missing.jpg"))
    assert resolve_preview(row, out) is None


def test_resolve_preview_handles_missing_output_files(tmp_path):
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"x")
    row = _row(output_files=None, thumbnail_path=str(thumb))
    assert resolve_preview(row, tmp_path) == (thumb, "image")
