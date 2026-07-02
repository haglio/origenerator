import json
from unittest.mock import MagicMock

from origenerator.gallery import (
    LoraGroup,
    MediaGroup,
    ModelGroup,
    SettingsGroup,
    SourceImageGroup,
    WorkflowGroup,
    animated_preview_path,
    build_gallery_tree,
    build_image_config_index,
    child_groups,
    config_tab_title,
    folder_level,
    find_source_image_id,
    media_type_of_row,
    lora_label,
    lora_signature,
    model_label,
    model_signature,
    output_disk_files,
    output_file_reference,
    recent_generations,
    resolve_preview,
    row_output_files,
    rows_under,
    settings_signature,
    source_image_id_for,
    starred_folders,
    videos_from_source_image,
)


def test_folder_level_names_the_recipe_levels_and_nothing_else():
    # The workflow -> model -> LoRA -> source-image folders each report their
    # level; the media roots and the settings leaves report none (no badge).
    assert folder_level(WorkflowGroup("k", "wf", "WF", [])) == "workflow"
    assert folder_level(ModelGroup("k", "M", [])) == "model"
    assert folder_level(LoraGroup("k", "L", [])) == "lora"
    assert folder_level(SourceImageGroup("k", "I", [])) == "source_image"
    assert folder_level(SettingsGroup("k", "S", [])) is None
    assert folder_level(MediaGroup("image", "image", "Images", [])) is None


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


def test_animated_preview_path_generates_a_cached_webp_for_a_video(tmp_path, monkeypatch):
    """A video row resolves to its looping WebP, generated from the on-disk file."""
    from origenerator.gallery import output as gallery_output
    video = tmp_path / "wan22_i2v_v1.mp4"
    video.write_bytes(b"fake video")
    row = _row(prompt_id="v1", workflow_name="wan22_i2v",
               output_files=json.dumps([{"filename": "wan22_i2v_v1.mp4"}]))
    calls = []

    def fake_generate(source, thumb_dir, *, name):
        calls.append((source, thumb_dir, name))
        return thumb_dir / f"{name}_anim.webp"

    monkeypatch.setattr(gallery_output, "generate_animated_thumbnail", fake_generate)

    result = animated_preview_path(row, tmp_path, tmp_path / "thumbs")

    assert result == str(tmp_path / "thumbs" / "v1_anim.webp")
    assert calls == [(video, tmp_path / "thumbs", "v1")]  # generated from the real file


def test_animated_preview_path_is_none_for_an_image(tmp_path, monkeypatch):
    """An image row has nothing to animate, so no WebP is generated."""
    from origenerator.gallery import output as gallery_output
    image = tmp_path / "sdxl_t2i_i1.png"
    image.write_bytes(b"fake image")
    row = _row(prompt_id="i1", output_files=json.dumps([{"filename": "sdxl_t2i_i1.png"}]))
    generate = MagicMock()
    monkeypatch.setattr(gallery_output, "generate_animated_thumbnail", generate)

    assert animated_preview_path(row, tmp_path, tmp_path / "thumbs") is None
    generate.assert_not_called()


def test_animated_preview_path_is_none_when_the_video_yields_no_frames(tmp_path, monkeypatch):
    """An unreadable video yields no WebP, so the caller falls back to the still."""
    from origenerator.gallery import output as gallery_output
    video = tmp_path / "wan22_i2v_v1.mp4"
    video.write_bytes(b"fake video")
    row = _row(prompt_id="v1", workflow_name="wan22_i2v",
               output_files=json.dumps([{"filename": "wan22_i2v_v1.mp4"}]))
    monkeypatch.setattr(gallery_output, "generate_animated_thumbnail",
                        lambda *a, **k: None)

    assert animated_preview_path(row, tmp_path, tmp_path / "thumbs") is None


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
    assert settings_signature(None, a) == settings_signature(None, b)
    # A real setting differs -> different signature.
    assert settings_signature(None, a) != settings_signature(None, c)


def test_settings_signature_drops_input_image_for_an_unknown_workflow():
    # With no registered workflow the grouping can't tell an i2v from anything
    # else, so it falls back to dropping input_image (instance-level, like the
    # seed): two rows differing only by image/seed still share one folder.
    a = json.dumps({"steps": 20, "input_image": "img_a.png", "seed": 1})
    b = json.dumps({"steps": 20, "input_image": "image/img_b.png [output]", "seed": 2})
    c = json.dumps({"steps": 30, "input_image": "img_a.png", "seed": 1})
    assert settings_signature(None, a) == settings_signature(None, b)  # only image/seed differ
    assert settings_signature(None, a) != settings_signature(None, c)  # a real setting differs


def test_settings_signature_folds_the_start_frames_config_for_i2v():
    # An i2v groups by the *configuration* that produced its start frame: two
    # videos with identical video settings split when their frames were generated
    # from different image configs, and rejoin when the frames share one config
    # (a re-roll of a single image).
    face1 = _img("face1", "a face", 30, 1)      # sdxl_t2i_face1.png
    face2 = _img("face2", "a face", 30, 2)      # same image config, re-rolled file
    scene = _img("scene", "a landscape", 30, 1)  # a differently configured frame
    index = build_image_config_index([face1, face2, scene])

    def vid(frame):
        return json.dumps({"positive_prompt": "", "steps": 20, "input_image": frame})

    sig_face1 = settings_signature("wan22_i2v", vid("sdxl_t2i_face1.png"), index)
    sig_face2 = settings_signature("wan22_i2v", vid("sdxl_t2i_face2.png"), index)
    sig_scene = settings_signature("wan22_i2v", vid("sdxl_t2i_scene.png"), index)
    assert sig_face1 == sig_face2  # re-rolled frame, same config -> one folder
    assert sig_face1 != sig_scene  # differently configured frame -> a new folder


def test_settings_signature_falls_back_to_the_frame_filename_when_unresolvable():
    # A hand-picked or since-deleted frame isn't a known generation, so it can't
    # resolve to a config; distinct filenames still separate rather than collapse.
    def vid(frame):
        return json.dumps({"positive_prompt": "", "input_image": frame})

    same = settings_signature("wan22_i2v", vid("hand_picked.png"), {})
    also = settings_signature("wan22_i2v", vid("input/hand_picked.png [input]"), {})
    other = settings_signature("wan22_i2v", vid("someone_else.png"), {})
    assert same == also   # the same external frame -> one folder
    assert same != other  # a different external frame -> a new folder


def test_settings_signature_tolerates_missing_or_invalid_params():
    assert settings_signature(None, None) == settings_signature(None, "{}")
    assert settings_signature(None, "not json") == settings_signature(None, "{}")


def test_reroll_regenerates_its_frame_and_stays_in_its_folder():
    # A re-roll regenerates the start frame (same image config, a fresh file) then
    # runs the video on it, building params via prepared_params (which fills every
    # workflow default). The re-roll must land in the original's folder despite
    # both the fresh filename and the default-filling: it keys on the frame's
    # *config*, not its file, and canonical settings absorb the default-filling.
    from origenerator.gallery import settings_folder_key
    from origenerator.generation_config import prepared_params
    from origenerator.workflows import WORKFLOW_REGISTRY

    wf = WORKFLOW_REGISTRY["wan22_i2v"]
    frame_a = _img("fa", "a face", 30, 1)  # sdxl_t2i_fa.png
    frame_b = _img("fb", "a face", 30, 2)  # same config, re-rolled -> sdxl_t2i_fb.png
    index = build_image_config_index([frame_a, frame_b])

    sparse = _row(
        workflow_name="wan22_i2v",
        params_json=json.dumps({"positive_prompt": "a wave", "input_image": "sdxl_t2i_fa.png"}),
        output_files=json.dumps([{"filename": "wan22_i2v_a.mp4"}]),
    )
    reroll_params = prepared_params(sparse, wf)  # exactly what the gallery re-roll runs
    reroll_params["input_image"] = "sdxl_t2i_fb.png"  # the freshly regenerated frame
    reroll = _row(
        workflow_name="wan22_i2v",
        params_json=json.dumps(reroll_params),
        output_files=json.dumps([{"filename": "wan22_i2v_b.mp4"}]),
    )
    assert settings_folder_key(reroll, index) == settings_folder_key(sparse, index)


def test_i2v_import_with_derived_size_shares_a_folder_with_a_generation():
    # i2v derives width/height in-graph from the input image, so a generation
    # never stores them — but an imported graph does, along with raw sampler-node
    # fields. Those keys the workflow doesn't define must not split the import
    # into a folder of its own, away from an otherwise identical generation.
    from origenerator.gallery import settings_folder_key
    from origenerator.workflows import WORKFLOW_REGISTRY

    generated_params = dict(WORKFLOW_REGISTRY["wan22_i2v"].default_params())
    generated_params["positive_prompt"] = "a wave"
    imported_params = {**generated_params, "width": 720, "height": 544, "add_noise": "enable"}
    generated = _row(
        workflow_name="wan22_i2v",
        params_json=json.dumps(generated_params),
        output_files=json.dumps([{"filename": "wan22_i2v_g.mp4"}]),
    )
    imported = _row(
        workflow_name="wan22_i2v",
        params_json=json.dumps(imported_params),
        output_files=json.dumps([{"filename": "wan22_i2v_i.mp4"}]),
    )
    assert settings_folder_key(imported) == settings_folder_key(generated)


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


def test_lora_label_treats_the_none_sentinel_as_no_lora():
    # Picking "None" for a LoRA is not a file: it reads as no LoRA, not a literal
    # "None" folder. Both off -> "(no LoRA)"; one off -> just the real one.
    from origenerator.workflows.model_files import NO_LORA
    assert lora_label("wan22_i2v", {"lora_high": NO_LORA, "lora_low": NO_LORA}) == "(no LoRA)"
    label = lora_label("wan22_i2v", {"lora_high": "styleA-high.safetensors", "lora_low": NO_LORA})
    assert label == "styleA-high"


def test_lora_signature_merges_the_none_sentinel_with_no_lora():
    # A run generated with "None" LoRAs and a no-LoRA import (whose graph carried
    # no LoRA node, so no lora_* keys) are the same "no LoRA" bucket: one folder.
    from origenerator.workflows.model_files import NO_LORA
    generated = json.dumps({"lora_high": NO_LORA, "lora_low": NO_LORA, "steps": 20})
    imported = json.dumps({"steps": 30})  # no lora keys at all
    assert lora_signature("wan22_i2v", generated) == lora_signature("wan22_i2v", imported)
    # ...but still distinct from a real LoRA.
    real = json.dumps({"lora_high": "styleA_high.safetensors", "lora_low": "styleA_low.safetensors"})
    assert lora_signature("wan22_i2v", generated) != lora_signature("wan22_i2v", real)


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


def test_videos_from_source_image_lists_the_videos_that_animated_it():
    image = _row(prompt_id="img-1", workflow_name="sdxl_t2i",
                 output_files=json.dumps([{"filename": "sdxl_t2i_00007_.png",
                                           "subfolder": "image"}]))
    used = _row(prompt_id="v-used", workflow_name="wan22_i2v",
                params_json=json.dumps({"input_image": "image/sdxl_t2i_00007_.png [output]"}))
    other = _row(prompt_id="v-other", workflow_name="wan22_i2v",
                 params_json=json.dumps({"input_image": "somethingelse.png"}))
    assert videos_from_source_image(image, [used, other]) == [used]
    assert videos_from_source_image(image, [other]) == []


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


def _i2v_frame(prompt_id, frame_file, prompt=""):
    """An i2v video sharing one model/LoRA/settings, distinguished only by the
    start frame it animates."""
    return _row(
        prompt_id=prompt_id,
        workflow_name="wan22_i2v",
        params_json=json.dumps({
            "positive_prompt": prompt,
            "unet_high": "wan_high.safetensors",
            "unet_low": "wan_low.safetensors",
            "lora_high": "styleA_high.safetensors",
            "lora_low": "styleA_low.safetensors",
            "steps": 20, "seed": 1, "input_image": frame_file,
        }),
        output_files=json.dumps([{"filename": f"wan22_i2v_{prompt_id}.mp4"}]),
    )


def _i2v_source_folders(rows):
    """The source-image folders of the sole video/workflow/model/LoRA path."""
    video = build_gallery_tree(rows)[0]
    return video.workflow_groups[0].model_groups[0].children[0].children


def _i2v_leaves(rows):
    """The settings leaves under the sole video/workflow/model/LoRA/source path."""
    (source,) = _i2v_source_folders(rows)
    return source.children


def test_i2v_videos_split_into_a_folder_per_input_image_config():
    # Two i2v videos sharing every video setting but built from differently
    # configured frames land in separate source-image folders.
    face = _img("face", "a face", 30, 1)
    scene = _img("scene", "a landscape", 30, 1)
    sources = _i2v_source_folders([
        _i2v_frame("vface", "sdxl_t2i_face.png"),
        _i2v_frame("vscene", "sdxl_t2i_scene.png"),
        face, scene,
    ])
    assert len(sources) == 2
    assert {frozenset(r["prompt_id"] for r in rows_under(s)) for s in sources} == {
        frozenset({"vface"}), frozenset({"vscene"}),
    }


def test_i2v_videos_from_rerolls_of_one_image_share_a_source_folder():
    # A frame re-rolled (same image config, fresh file) keeps its videos in one
    # source-image folder, collapsed into a single settings leaf beneath it.
    face1 = _img("face1", "a face", 30, 1)
    face2 = _img("face2", "a face", 30, 2)  # re-roll of the same image config
    (source,) = _i2v_source_folders([
        _i2v_frame("v1", "sdxl_t2i_face1.png"),
        _i2v_frame("v2", "sdxl_t2i_face2.png"),
        face1, face2,
    ])
    (leaf,) = source.children
    assert {r["prompt_id"] for r in leaf.rows} == {"v1", "v2"}


def test_i2v_source_folder_is_named_by_the_image_it_animates():
    # A source-image folder takes the name of the image generation it animates, so
    # sibling folders built from different images read apart — the same label that
    # image's own settings folder carries.
    face = _img("face", "a smiling face", 30, 1)
    (source,) = _i2v_source_folders([_i2v_frame("vf", "sdxl_t2i_face.png"), face])
    assert "smiling face" in source.label


def test_i2v_settings_leaf_names_itself_by_video_prompt_not_the_frame():
    # The source-image folder pins the frame, so the leaf beneath drops it and is
    # named by the video's own prompt instead.
    face = _img("face", "a smiling face", 30, 1)
    (source,) = _i2v_source_folders(
        [_i2v_frame("vf", "sdxl_t2i_face.png", prompt="a slow zoom"), face]
    )
    (leaf,) = source.children
    assert leaf.label == "a slow zoom"
    assert "smiling face" not in leaf.label


def test_i2v_source_folder_labels_a_hand_picked_frame_by_its_filename():
    # A frame that isn't a known generation can't borrow an image's folder name, so
    # the source folder falls back to the bare filename (distinct frames still read
    # apart) rather than a blank or collapsed name.
    (source,) = _i2v_source_folders([_i2v_frame("vf", "input/hand_picked.png [input]")])
    assert source.label == "hand_picked.png"


def test_folder_key_at_level_source_image_resolves_the_frame_through_the_index():
    # A source-image bookmark's key is recomputed from a member row; it depends on
    # the start frame's config, so folder_key_at_level must resolve it through the
    # image index — matching the tree, not the bare filename.
    from origenerator.gallery import folder_key_at_level
    face = _img("face", "a face", 30, 1)
    video = _i2v_frame("vf", "sdxl_t2i_face.png")
    index = build_image_config_index([face])
    (source,) = _i2v_source_folders([video, face])
    assert source.key.startswith("video/wan22_i2v/i")  # the source level tags its key with 'i'
    assert folder_key_at_level(video, "source_image", index) == source.key
    # Without the index it falls back to the filename and misses the real folder.
    assert folder_key_at_level(video, "source_image", index) != \
        folder_key_at_level(video, "source_image")


def test_settings_folder_key_matches_an_i2v_leaf_under_its_source_folder():
    # The leaf key is independent of the new source-image parent, so an in-flight
    # i2v (absent from the tree) still matches the exact leaf it will join — the
    # invariant the Generate tab and re-roll reconnection rely on.
    from origenerator.gallery import settings_folder_key
    face = _img("face", "a face", 30, 1)
    video = _i2v_frame("vf", "sdxl_t2i_face.png")
    index = build_image_config_index([face])
    (leaf,) = _i2v_leaves([video, face])
    assert settings_folder_key(video, index) == leaf.key


def test_an_i2v_workflow_still_gets_no_source_image_level_under_images():
    # An image-conditioned WORKFLOW can output a still — an imported PNG under a
    # video prefix — which classifies as an image. A still animates nothing, so it
    # must not grow a source-image level: under Images it goes straight from LoRA to
    # its settings leaf, exactly like any other image.
    still = _row(
        prompt_id="still",
        workflow_name="wan22_flf2v_loop",
        params_json=json.dumps(
            {"positive_prompt": "a cat", "input_image": "sdxl_t2i_1_.png", "seed": 2}
        ),
        output_files=json.dumps([{"filename": "flf2v_loop_00001_.png"}]),
    )
    (media,) = build_gallery_tree([still])
    assert media.media_type == "image"
    (lora,) = media.workflow_groups[0].model_groups[0].children
    assert all(isinstance(child, SettingsGroup) for child in lora.children)


def test_folder_key_at_level_settings_resolves_the_frame_through_the_index():
    # The reconcile recomputes a settings bookmark's key from a member row; for an
    # i2v that key depends on the start frame's config, so folder_key_at_level must
    # resolve it through the image index — matching the tree, not the bare filename.
    from origenerator.gallery import folder_key_at_level, settings_folder_key
    face = _img("face", "a face", 30, 1)
    video = _i2v_frame("vf", "sdxl_t2i_face.png")
    index = build_image_config_index([face])
    assert folder_key_at_level(video, "settings", index) == settings_folder_key(video, index)
    # Without the index it falls back to the filename and misses the real folder.
    assert folder_key_at_level(video, "settings", index) != settings_folder_key(video)


def test_legacy_preframe_settings_folder_key_drops_the_frame():
    # The pre-frame-config key hashes the video's own settings with the input image
    # dropped — distinct from the current key, which folds the frame's config in.
    from origenerator.gallery import legacy_preframe_settings_folder_key, settings_folder_key
    face = _img("face", "a face", 30, 1)
    video = _i2v_frame("vf", "sdxl_t2i_face.png")
    index = build_image_config_index([face])
    assert legacy_preframe_settings_folder_key(video) != settings_folder_key(video, index)
    # A non-image-conditioned row never folded a frame, so its key is unchanged.
    image = _img("cat", "a cat", 20, 1)
    assert legacy_preframe_settings_folder_key(image) == settings_folder_key(image)


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

    (a_source,) = loras["styleA_high / styleA_low"].children  # one "(no input image)" source
    (a_settings,) = a_source.children                          # the two seeds collapse
    assert {r["prompt_id"] for r in a_settings.rows} == {"v1", "v2"}
    assert {r["prompt_id"] for r in rows_under(loras["styleB_high / styleB_low"])} == {"v3"}


def test_settings_folder_key_matches_the_rows_tree_leaf():
    # A completed row's settings-folder key equals the leaf key build_gallery_tree
    # gives it, so an in-flight sibling (absent from the tree) can be matched to it.
    from origenerator.gallery import settings_folder_key
    row = _img_model("i1", "a cat", "reapony_v80.safetensors", 50, 1)
    (lora,) = build_gallery_tree([row])[0].workflow_groups[0].model_groups[0].children
    (leaf,) = lora.children
    assert settings_folder_key(row) == leaf.key


def test_group_level_names_each_tier():
    from origenerator.gallery import group_level
    rows = [_i2v("v1", "styleA")]  # video -> wan22_i2v -> model -> lora -> source -> settings
    media = build_gallery_tree(rows)[0]
    wf = media.workflow_groups[0]
    model = wf.model_groups[0]
    lora = model.children[0]
    source = lora.children[0]
    settings = source.children[0]
    assert [group_level(g) for g in (media, wf, model, lora, source, settings)] == \
        ["media", "workflow", "model", "lora", "source_image", "settings"]


def test_folder_key_at_level_recomputes_each_tiers_key_from_a_member_row():
    # A bookmark stores its tier + a member row; recomputing the key from that row
    # must reproduce the folder's key at every tier, so the star can follow it.
    from origenerator.gallery import folder_key_at_level, group_level
    rows = [_i2v("v1", "styleA")]
    media = build_gallery_tree(rows)[0]
    wf = media.workflow_groups[0]
    model = wf.model_groups[0]
    lora = model.children[0]
    source = lora.children[0]
    settings = source.children[0]
    for g in (media, wf, model, lora, source, settings):
        assert folder_key_at_level(rows[0], group_level(g)) == g.key


def test_legacy_settings_key_differs_from_the_current_normalized_key():
    # canonical_settings changed the settings hash, so the legacy formula yields a
    # different key for the same row — exactly why a star set before the change no
    # longer matches its folder, and what the reconcile recomputes to re-point it.
    from origenerator.gallery import legacy_settings_folder_key, settings_folder_key
    row = _img("i1", "a cat", 50, 1)
    assert legacy_settings_folder_key(row) != settings_folder_key(row)
    assert legacy_settings_folder_key(row).startswith("image/sdxl_t2i/")


def test_build_gallery_tree_collapses_the_lora_level_without_lora_keys():
    # SDXL declares no LoRA keys, so its model folder still grows a LoRA level — a
    # single "(no LoRA)" folder wrapping the settings leaves — so every branch of
    # the tree nests to the same depth whether or not the pipeline uses a LoRA.
    rows = [_img_model("i1", "a cat", "reapony_v80.safetensors", 50, 1)]
    (model,) = build_gallery_tree(rows)[0].workflow_groups[0].model_groups
    (lora,) = model.children
    assert isinstance(lora, LoraGroup)
    assert lora.label == "(no LoRA)"
    assert all(isinstance(child, SettingsGroup) for child in lora.children)


def test_lora_folders_get_stable_keys_and_apply_custom_names_and_stars():
    rows = [_i2v("v1", "styleA"), _i2v("v2", "styleB")]
    model = build_gallery_tree(rows)[0].workflow_groups[0].model_groups[0]
    a, b = model.children
    assert a.key.startswith("video/wan22_i2v/l")  # the LoRA level tags its key with 'l'
    assert a.key != b.key

    meta = {b.key: {"custom_name": "Style B", "starred": True}}
    loras = build_gallery_tree(rows, meta)[0].workflow_groups[0].model_groups[0].children
    assert [lora.key for lora in loras] == [a.key, b.key]  # order unchanged — no reshuffle
    assert loras[1].label == "Style B"     # custom name applied in place
    assert loras[1].starred is True
    assert loras[0].starred is False


def test_settings_labels_drop_the_lora_pinned_by_the_folder_above():
    # Two LoRAs, identical prompt/settings otherwise: the split is at the LoRA
    # level, so neither settings leaf needs the LoRA name in it.
    rows = [_i2v("v1", "styleA"), _i2v("v2", "styleB")]
    model = build_gallery_tree(rows)[0].workflow_groups[0].model_groups[0]
    for lora in model.children:
        (source,) = lora.children
        (settings,) = source.children
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
    (reapony_lora,) = reapony.children              # the single "(no LoRA)" level
    assert len(reapony_lora.children) == 1          # the two seeds collapse
    assert {r["prompt_id"] for r in reapony_lora.children[0].rows} == {"i1", "i2"}
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
    assert [m.key for m in models] == [reapony.key, dream.key]  # order unchanged
    assert models[1].label == "Dreamy"     # custom name applied in place
    assert models[1].starred is True
    assert models[0].starred is False


def test_settings_labels_drop_the_model_pinned_by_the_folder_above():
    # Two checkpoints, identical prompt/settings otherwise: the split is at the
    # model level, so neither settings leaf needs the checkpoint in its name.
    rows = [
        _img_model("i1", "a cat", "reapony_v80.safetensors", 50, 1),
        _img_model("i2", "a cat", "dreamshaper.safetensors", 50, 1),
    ]
    workflow = build_gallery_tree(rows)[0].workflow_groups[0]
    for model in workflow.model_groups:
        (lora,) = model.children
        (settings,) = lora.children
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
    (lora,) = model.children                # the single "(no LoRA)" level
    settings = lora.children
    assert len(settings) == 2
    assert {r["prompt_id"] for r in settings[0].rows} == {"i1", "i2"}
    assert {r["prompt_id"] for r in settings[1].rows} == {"i3"}

    video = media["video"]
    assert [w.workflow_name for w in video.workflow_groups] == ["wan22_i2v"]
    (video_model,) = video.workflow_groups[0].model_groups
    (video_lora,) = video_model.children    # wan22_i2v grows a LoRA level ("(no LoRA)" here)
    (video_source,) = video_lora.children   # then a source-image level ("(no input image)")
    assert len(video_source.children) == 1


def test_build_gallery_tree_assigns_stable_folder_keys():
    tree = build_gallery_tree([_img("i1", "a cat", 50, 1)])
    media = tree[0]
    assert media.key == "image"
    workflow = media.workflow_groups[0]
    assert workflow.key == "image/sdxl_t2i"
    model = workflow.model_groups[0]
    assert model.key.startswith("image/sdxl_t2i/")
    settings = model.children[0].children[0]     # model -> "(no LoRA)" -> settings
    assert settings.key.startswith("image/sdxl_t2i/")

    # The model and settings keys are derived from signatures, so they are
    # stable across rebuilds (what lets a rename/star stick to the same folder).
    again_model = build_gallery_tree([_img("i9", "a cat", 50, 7)])[0] \
        .workflow_groups[0].model_groups[0]
    assert again_model.key == model.key
    assert again_model.children[0].children[0].key == settings.key


def test_build_gallery_tree_applies_custom_names_and_stars_in_place():
    rows = [_img("i1", "a cat", 50, 1), _img("i2", "a dog", 50, 1)]
    plain_lora = build_gallery_tree(rows)[0] \
        .workflow_groups[0].model_groups[0].children[0]  # the "(no LoRA)" level
    cat, dog = plain_lora.children  # newest-first: cat, dog

    meta = {dog.key: {"custom_name": "Doggos", "starred": True}}
    settings = build_gallery_tree(rows, meta)[0] \
        .workflow_groups[0].model_groups[0].children[0].children

    assert [s.key for s in settings] == [cat.key, dog.key]  # order unchanged — no reshuffle
    assert settings[1].label == "Doggos"      # custom name applied in place
    assert settings[1].starred is True
    assert settings[0].starred is False


def test_starred_folders_collects_starred_across_every_level():
    # Star a whole workflow folder and one deep settings leaf; the collector
    # returns both, top-down in tree order, regardless of how deep each sits.
    rows = [_img("i1", "a cat", 50, 1), _img("i2", "a dog", 50, 1)]
    workflow = build_gallery_tree(rows)[0].workflow_groups[0]
    cat_leaf = workflow.model_groups[0].children[0].children[0]  # model -> "(no LoRA)" -> settings

    meta = {
        workflow.key: {"custom_name": None, "starred": True},
        cat_leaf.key: {"custom_name": None, "starred": True},
    }
    starred = starred_folders(build_gallery_tree(rows, meta))
    assert [g.key for g in starred] == [workflow.key, cat_leaf.key]


def test_starred_folders_is_empty_when_nothing_is_starred():
    tree = build_gallery_tree([_img("i1", "a cat", 50, 1)])
    assert starred_folders(tree) == []


def test_recent_generations_keeps_the_callers_newest_first_order():
    # Rows arrive newest-first (the DB lists by descending id); the shelf keeps
    # that order and doesn't re-sort.
    rows = [_img("i3", "c", 50, 3), _img("i2", "b", 50, 2), _img("i1", "a", 50, 1)]
    assert [r["prompt_id"] for r in recent_generations(rows, 10)] == ["i3", "i2", "i1"]


def test_recent_generations_excludes_imported_files():
    # "Recently generated" means this app made it — an imported file discovered on
    # disk is not a generation and never joins the shelf.
    generated = _img("gen", "a cat", 50, 1)
    imported = _row(prompt_id="imp", source="imported",
                    output_files=json.dumps([{"filename": "imp.png"}]))
    assert [r["prompt_id"] for r in recent_generations([imported, generated], 10)] == ["gen"]


def test_recent_generations_excludes_rows_that_produced_no_output():
    # Mirrors the tree: a failed or in-flight row wrote no file, so it has nothing
    # to show and stays off the shelf.
    done = _img("done", "a cat", 50, 1)
    pending = _row(prompt_id="wip", output_files=None)
    assert [r["prompt_id"] for r in recent_generations([done, pending], 10)] == ["done"]


def test_recent_generations_caps_at_the_limit():
    rows = [_img(f"i{n}", "a cat", 50, n) for n in range(5)]
    assert [r["prompt_id"] for r in recent_generations(rows, 3)] == ["i0", "i1", "i2"]


def test_child_groups_and_rows_under_walk_the_tree():
    rows = [_img("i1", "a cat", 50, 1), _img("i2", "a cat", 50, 2),
            _img("i3", "a dog", 50, 1)]
    media = build_gallery_tree(rows)[0]

    workflows = child_groups(media)
    assert [w.workflow_name for w in workflows] == ["sdxl_t2i"]
    (model,) = child_groups(workflows[0])  # no checkpoint recorded -> one model
    (lora,) = child_groups(model)          # the single "(no LoRA)" level
    settings = child_groups(lora)
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
              tree[0].workflow_groups[0].model_groups[0].children[0].children]
    assert len(labels) == 2
    assert labels[0] != labels[1]
    assert all("a cat" in label for label in labels)
    # the distinguishing param is surfaced so the folders are tellable apart
    assert any("steps" in label for label in labels)


def test_settings_group_label_omits_params_when_only_one_group():
    # A lone settings folder needs no disambiguating suffix.
    tree = build_gallery_tree([_img("i1", "a cat", 50, 1),
                               _img("i2", "a cat", 50, 2)])
    (lora,) = tree[0].workflow_groups[0].model_groups[0].children
    (only,) = lora.children
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
