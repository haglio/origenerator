import json

from origenerator.gallery import (
    SettingsGroup,
    build_gallery_tree,
    child_groups,
    config_tab_title,
    find_source_image_id,
    media_type_of_row,
    lora_label,
    lora_signature,
    model_label,
    model_signature,
    output_disk_files,
    output_file_reference,
    resolve_preview,
    row_output_files,
    rows_under,
    settings_signature,
    source_image_id_for,
)


def test_config_tab_title_leads_with_model_then_prompt():
    title = config_tab_title("sdxl_t2i", {"positive_prompt": "a cat in a hat", "seed": 5})
    assert title == "SDXL Text-to-Image › a cat in a hat"


def test_config_tab_title_is_just_the_model_without_a_prompt():
    assert config_tab_title("sdxl_t2i", {"seed": 5}) == "SDXL Text-to-Image"


def test_config_tab_title_handles_unknown_workflow():
    assert config_tab_title("nope", {}) == "nope"


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


def test_settings_signature_ignores_input_image_like_a_seed():
    # An i2v re-roll regenerates its input image, so two videos that differ only
    # by their (freshly generated) input image are the same recipe and belong in
    # one settings folder — input_image is instance-level, like the seed.
    a = json.dumps({"steps": 20, "input_image": "img_a.png", "seed": 1})
    b = json.dumps({"steps": 20, "input_image": "image/img_b.png [output]", "seed": 2})
    c = json.dumps({"steps": 30, "input_image": "img_a.png", "seed": 1})
    assert settings_signature(a) == settings_signature(b)  # only the image/seed differ
    assert settings_signature(a) != settings_signature(c)  # a real setting differs


def test_settings_signature_tolerates_missing_or_invalid_params():
    assert settings_signature(None) == settings_signature("{}")
    assert settings_signature("not json") == settings_signature("{}")


def test_model_signature_groups_by_model_params_only():
    a = json.dumps({"checkpoint": "reapony_v80.safetensors", "steps": 50, "seed": 1})
    b = json.dumps({"checkpoint": "reapony_v80.safetensors", "steps": 40, "seed": 2})
    c = json.dumps({"checkpoint": "dreamshaper.safetensors", "steps": 50})
    # Same model, different settings/seed -> identical model signature.
    assert model_signature("sdxl_t2i", a) == model_signature("sdxl_t2i", b)
    # A different checkpoint -> different model signature.
    assert model_signature("sdxl_t2i", a) != model_signature("sdxl_t2i", c)


def test_model_signature_spans_every_model_key():
    base = {"unet_high": "h1.safetensors", "unet_low": "l1.safetensors"}
    same = model_signature("wan22_i2v", json.dumps(base))
    diff_low = model_signature("wan22_i2v", json.dumps({**base, "unet_low": "l2.safetensors"}))
    # The low-noise UNET is part of the model identity, so changing it splits.
    assert same != diff_low


def test_lora_signature_groups_by_lora_params_only():
    base = {"lora_high": "styleA_high.safetensors", "lora_low": "styleA_low.safetensors"}
    a = json.dumps({**base, "steps": 20, "seed": 1})
    b = json.dumps({**base, "steps": 30, "seed": 2})  # same LoRAs, other settings
    c = json.dumps({**base, "lora_low": "styleB_low.safetensors"})  # a LoRA differs
    # Same LoRAs, different settings/seed -> identical LoRA signature.
    assert lora_signature("wan22_i2v", a) == lora_signature("wan22_i2v", b)
    # A different LoRA file -> different LoRA signature.
    assert lora_signature("wan22_i2v", a) != lora_signature("wan22_i2v", c)


def test_lora_signature_is_empty_for_a_workflow_without_lora_keys():
    # SDXL declares no LoRA keys, so every row shares one (empty) LoRA signature
    # and no LoRA level is ever drawn.
    a = json.dumps({"lora_high": "x.safetensors", "steps": 20})
    b = json.dumps({"steps": 30})
    assert lora_signature("sdxl_t2i", a) == lora_signature("sdxl_t2i", b)


def test_model_label_strips_directory_and_extension():
    assert model_label("sdxl_t2i", {"checkpoint": "reapony_v80.safetensors"}) == "reapony_v80"


def test_model_label_joins_multiple_model_keys():
    label = model_label("wan22_i2v", {
        "unet_high": "split_files\\diffusion_models\\wan_high_14B.safetensors",
        "unet_low": "split_files\\diffusion_models\\wan_low_14B.safetensors",
    })
    assert label == "wan_high_14B / wan_low_14B"


def test_model_label_falls_back_when_model_is_unknown():
    # No model param recorded (e.g. an imported file that didn't carry it)...
    assert model_label("sdxl_t2i", {}) == "(unknown model)"
    # ...or a workflow that declares no model keys at all.
    assert model_label("nope", {"checkpoint": "x.safetensors"}) == "(unknown model)"


def test_lora_label_joins_cleaned_lora_filenames():
    label = lora_label("wan22_i2v", {
        "lora_high": "loras\\styleA-high-k3nk.safetensors",
        "lora_low": "styleA-low-k3nk.safetensors",
    })
    assert label == "styleA-high-k3nk / styleA-low-k3nk"


def test_lora_label_falls_back_when_no_lora_recorded():
    # A row that carried no LoRA value (e.g. an older import) reads as "(no LoRA)"
    # rather than an empty name.
    assert lora_label("wan22_i2v", {}) == "(no LoRA)"


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


def test_source_image_id_for_resolves_a_bare_input_value():
    # The Generate tab knows only the input_image value (not a whole row), yet
    # must resolve it the same way — through the "[output]" annotation too.
    image = _row(prompt_id="img-1", workflow_name="sdxl_t2i",
                 output_files=json.dumps([{"filename": "sdxl_t2i_00007_.png",
                                           "subfolder": "image"}]))
    assert source_image_id_for("image/sdxl_t2i_00007_.png [output]", [image]) == "img-1"
    assert source_image_id_for("", [image]) is None
    assert source_image_id_for("elsewhere.png", [image]) is None


def test_find_source_image_matches_through_an_output_annotation():
    # A re-rolled i2v references its freshly generated input by an annotated
    # output path ("subfolder/name [output]"); the link must still resolve it
    # back to the image generation by basename.
    image = _row(
        prompt_id="img-1",
        workflow_name="sdxl_t2i",
        output_files=json.dumps([{"filename": "sdxl_t2i_00007_.png",
                                  "subfolder": "image"}]),
    )
    video = _row(
        prompt_id="vid-1",
        workflow_name="wan22_i2v",
        params_json=json.dumps(
            {"input_image": "image/sdxl_t2i_00007_.png [output]"}
        ),
    )
    assert find_source_image_id(video, [image]) == "img-1"


def test_output_file_reference_annotates_the_first_output_for_loadimage():
    # A generation's saved file lives in the output dir; LoadImage resolves it
    # only when the reference carries its subfolder and an "[output]" tag.
    files = [{"filename": "sdxl_t2i_00007_.png", "subfolder": "image",
              "type": "output"}]
    assert output_file_reference(files) == "image/sdxl_t2i_00007_.png [output]"


def test_output_file_reference_without_subfolder_defaults_to_output():
    assert output_file_reference([{"filename": "img.png"}]) == "img.png [output]"


def test_output_file_reference_is_none_when_no_usable_file():
    assert output_file_reference([]) is None
    assert output_file_reference([{"subfolder": "image"}]) is None  # no filename


def test_output_reference_round_trips_back_to_its_source_image():
    # The reference a re-roll writes into a video's input_image must resolve back
    # to the very image it was built from — the contract between the two helpers.
    image = _row(
        prompt_id="img-1", workflow_name="sdxl_t2i",
        output_files=json.dumps([{"filename": "sdxl_t2i_00007_.png",
                                  "subfolder": "image", "type": "output"}]),
    )
    ref = output_file_reference(row_output_files(image))
    video = _row(prompt_id="vid", workflow_name="wan22_i2v",
                 params_json=json.dumps({"input_image": ref}))
    assert find_source_image_id(video, [image]) == "img-1"


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


def _img_model(prompt_id, prompt, checkpoint, steps, seed):
    return _row(
        prompt_id=prompt_id,
        workflow_name="sdxl_t2i",
        params_json=json.dumps({
            "positive_prompt": prompt, "checkpoint": checkpoint,
            "steps": steps, "seed": seed,
        }),
        output_files=json.dumps([{"filename": f"sdxl_t2i_{prompt_id}.png"}]),
    )


def _i2v(prompt_id, lora, prompt="dance", steps=20, seed=1):
    return _row(
        prompt_id=prompt_id,
        workflow_name="wan22_i2v",
        params_json=json.dumps({
            "positive_prompt": prompt,
            "unet_high": "wan_high.safetensors",
            "unet_low": "wan_low.safetensors",
            "lora_high": f"{lora}_high.safetensors",
            "lora_low": f"{lora}_low.safetensors",
            "steps": steps, "seed": seed,
        }),
        output_files=json.dumps([{"filename": f"wan22_i2v_{prompt_id}.mp4"}]),
    )


def test_build_gallery_tree_nests_lora_under_model_for_lora_workflows():
    rows = [
        _i2v("v1", "styleA"),
        _i2v("v2", "styleA", seed=2),   # same LoRA + settings, different seed
        _i2v("v3", "styleB"),           # same base model, different LoRA
    ]
    workflow = build_gallery_tree(rows)[0].workflow_groups[0]
    (model,) = workflow.model_groups                       # one shared base model
    loras = {lg.label: lg for lg in model.children}
    assert set(loras) == {"styleA_high / styleA_low", "styleB_high / styleB_low"}

    (a_settings,) = loras["styleA_high / styleA_low"].children  # the two seeds collapse
    assert {r["prompt_id"] for r in a_settings.rows} == {"v1", "v2"}
    assert {r["prompt_id"] for r in rows_under(loras["styleB_high / styleB_low"])} == {"v3"}


def test_settings_folder_key_matches_the_rows_tree_leaf():
    # A completed row's settings-folder key equals the leaf key build_gallery_tree
    # gives it, so an in-flight sibling (absent from the tree) can be matched to it.
    from origenerator.gallery import settings_folder_key
    row = _img_model("i1", "a cat", "reapony_v80.safetensors", 50, 1)
    (leaf,) = build_gallery_tree([row])[0].workflow_groups[0].model_groups[0].children
    assert settings_folder_key(row) == leaf.key


def test_build_gallery_tree_grows_no_lora_level_without_lora_keys():
    # SDXL declares no LoRA keys, so a model folder holds settings leaves directly
    # — no intervening LoRA level to click through.
    rows = [_img_model("i1", "a cat", "reapony_v80.safetensors", 50, 1)]
    (model,) = build_gallery_tree(rows)[0].workflow_groups[0].model_groups
    assert all(isinstance(child, SettingsGroup) for child in model.children)


def test_lora_folders_get_stable_keys_and_apply_custom_names_and_stars():
    rows = [_i2v("v1", "styleA"), _i2v("v2", "styleB")]
    model = build_gallery_tree(rows)[0].workflow_groups[0].model_groups[0]
    a, b = model.children
    assert a.key.startswith("video/wan22_i2v/l")  # the LoRA level tags its key with 'l'
    assert a.key != b.key

    meta = {b.key: {"custom_name": "Style B", "starred": True}}
    loras = build_gallery_tree(rows, meta)[0].workflow_groups[0].model_groups[0].children
    assert loras[0].label == "Style B"     # custom name applied
    assert loras[0].starred is True
    assert loras[0].key == b.key           # and the star floated it to the top
    assert loras[1].starred is False


def test_settings_labels_drop_the_lora_pinned_by_the_folder_above():
    # Two LoRAs, identical prompt/settings otherwise: the split is at the LoRA
    # level, so neither settings leaf needs the LoRA name in it.
    rows = [_i2v("v1", "styleA"), _i2v("v2", "styleB")]
    model = build_gallery_tree(rows)[0].workflow_groups[0].model_groups[0]
    for lora in model.children:
        (settings,) = lora.children
        assert settings.label == "dance"
        assert "safetensors" not in settings.label


def test_build_gallery_tree_nests_workflow_then_model_then_settings():
    rows = [
        _img_model("i1", "a cat", "reapony_v80.safetensors", 50, 1),
        _img_model("i2", "a cat", "reapony_v80.safetensors", 50, 2),  # same model+settings
        _img_model("i3", "a cat", "dreamshaper.safetensors", 50, 1),  # same prompt, other model
    ]
    workflow = build_gallery_tree(rows)[0].workflow_groups[0]

    models = {m.label: m for m in workflow.model_groups}
    assert set(models) == {"reapony_v80", "dreamshaper"}

    reapony = models["reapony_v80"]
    assert len(reapony.children) == 1  # the two seeds collapse
    assert {r["prompt_id"] for r in reapony.children[0].rows} == {"i1", "i2"}
    assert {r["prompt_id"] for r in rows_under(models["dreamshaper"])} == {"i3"}


def test_model_folders_get_stable_keys_and_apply_custom_names_and_stars():
    rows = [
        _img_model("i1", "a cat", "reapony_v80.safetensors", 50, 1),
        _img_model("i2", "a cat", "dreamshaper.safetensors", 50, 1),
    ]
    reapony, dream = build_gallery_tree(rows)[0].workflow_groups[0].model_groups
    assert reapony.key.startswith("image/sdxl_t2i/")
    assert reapony.key != dream.key

    meta = {dream.key: {"custom_name": "Dreamy", "starred": True}}
    models = build_gallery_tree(rows, meta)[0].workflow_groups[0].model_groups
    assert models[0].label == "Dreamy"     # custom name applied
    assert models[0].starred is True
    assert models[0].key == dream.key       # and the star floated it to the top
    assert models[1].starred is False


def test_settings_labels_drop_the_model_pinned_by_the_folder_above():
    # Two checkpoints, identical prompt/settings otherwise: the split is at the
    # model level, so neither settings leaf needs the checkpoint in its name.
    rows = [
        _img_model("i1", "a cat", "reapony_v80.safetensors", 50, 1),
        _img_model("i2", "a cat", "dreamshaper.safetensors", 50, 1),
    ]
    workflow = build_gallery_tree(rows)[0].workflow_groups[0]
    for model in workflow.model_groups:
        (settings,) = model.children
        assert settings.label == "a cat"
        assert "safetensors" not in settings.label


def test_build_gallery_tree_excludes_rows_that_produced_no_output():
    # A failed generation never wrote a file. The gallery shows results, so a
    # file-less row must not surface as an empty, output-less entry — not even
    # the media-type folder it would otherwise create.
    rows = [
        _img("i1", "a cat", 50, 1),                          # real result: has a file
        _row(prompt_id="boom", workflow_name="wan22_i2v",
             status="error",
             params_json=json.dumps({"positive_prompt": "dance", "seed": 5}),
             output_files=None),                             # failed: no file
    ]
    tree = build_gallery_tree(rows)
    surfaced = {r["prompt_id"] for media in tree for r in rows_under(media)}
    assert surfaced == {"i1"}
    assert [m.media_type for m in tree] == ["image"]  # no Videos folder for the dead row


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
    (model,) = sdxl_groups[0].model_groups  # no checkpoint recorded -> one model
    settings = model.children
    assert len(settings) == 2
    assert {r["prompt_id"] for r in settings[0].rows} == {"i1", "i2"}
    assert {r["prompt_id"] for r in settings[1].rows} == {"i3"}

    video = media["video"]
    assert [w.workflow_name for w in video.workflow_groups] == ["wan22_i2v"]
    (video_model,) = video.workflow_groups[0].model_groups
    (video_lora,) = video_model.children  # wan22_i2v grows a LoRA level ("(no LoRA)" here)
    assert len(video_lora.children) == 1


def test_build_gallery_tree_assigns_stable_folder_keys():
    tree = build_gallery_tree([_img("i1", "a cat", 50, 1)])
    media = tree[0]
    assert media.key == "image"
    workflow = media.workflow_groups[0]
    assert workflow.key == "image/sdxl_t2i"
    model = workflow.model_groups[0]
    assert model.key.startswith("image/sdxl_t2i/")
    settings = model.children[0]
    assert settings.key.startswith("image/sdxl_t2i/")

    # The model and settings keys are derived from signatures, so they are
    # stable across rebuilds (what lets a rename/star stick to the same folder).
    again_model = build_gallery_tree([_img("i9", "a cat", 50, 7)])[0] \
        .workflow_groups[0].model_groups[0]
    assert again_model.key == model.key
    assert again_model.children[0].key == settings.key


def test_build_gallery_tree_applies_custom_names_and_floats_stars_first():
    rows = [_img("i1", "a cat", 50, 1), _img("i2", "a dog", 50, 1)]
    plain_model = build_gallery_tree(rows)[0].workflow_groups[0].model_groups[0]
    cat, dog = plain_model.children  # newest-first: cat, dog

    meta = {dog.key: {"custom_name": "Doggos", "starred": True}}
    settings = build_gallery_tree(rows, meta)[0] \
        .workflow_groups[0].model_groups[0].children

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
    (model,) = child_groups(workflows[0])  # no checkpoint recorded -> one model
    settings = child_groups(model)
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
    labels = [sg.label for sg in
              tree[0].workflow_groups[0].model_groups[0].children]
    assert len(labels) == 2
    assert labels[0] != labels[1]
    assert all("a cat" in label for label in labels)
    # the distinguishing param is surfaced so the folders are tellable apart
    assert any("steps" in label for label in labels)


def test_settings_group_label_omits_params_when_only_one_group():
    # A lone settings folder needs no disambiguating suffix.
    tree = build_gallery_tree([_img("i1", "a cat", 50, 1),
                               _img("i2", "a cat", 50, 2)])
    (only,) = tree[0].workflow_groups[0].model_groups[0].children
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


def test_output_disk_files_returns_the_referenced_file(tmp_path):
    out = tmp_path / "output"
    (out / "image").mkdir(parents=True)
    png = out / "image" / "sdxl_t2i_1_.png"
    png.write_bytes(b"x")
    row = _row(output_files=json.dumps([{"filename": "sdxl_t2i_1_.png",
                                         "subfolder": "image"}]))
    assert output_disk_files(row, out) == [png]


def test_output_disk_files_includes_a_video_metadata_sidecar(tmp_path):
    out = tmp_path / "output"
    (out / "video").mkdir(parents=True)
    mp4 = out / "video" / "wan22_i2v_1_.mp4"
    mp4.write_bytes(b"v")
    sidecar = out / "video" / "wan22_i2v_1_.png"  # VHS_VideoCombine writes this
    sidecar.write_bytes(b"p")
    # The consolidated row points at the video; deleting it must also take the
    # PNG, or the next import would resurrect the orphaned still as an image.
    row = _row(output_files=json.dumps([{"filename": "wan22_i2v_1_.mp4",
                                         "subfolder": "video"}]))
    assert output_disk_files(row, out) == [mp4, sidecar]


def test_output_disk_files_omits_files_not_on_disk(tmp_path):
    out = tmp_path / "output"
    out.mkdir()
    row = _row(output_files=json.dumps([{"filename": "gone.png", "subfolder": ""}]))
    assert output_disk_files(row, out) == []
