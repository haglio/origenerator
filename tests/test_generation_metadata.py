import json

from origenerator.generation_metadata import build_sections


def _row(**overrides):
    row = {
        "status": "completed",
        "source": "generated",
        "seed": 7,
        "created_at": "2026-01-01",
        "positive_prompt": "a cat",
        "negative_prompt": "blurry",
        "params_json": json.dumps({"steps": 20, "positive_prompt": "a cat"}),
        "output_files": json.dumps([{"filename": "out.png", "subfolder": ""}]),
    }
    row.update(overrides)
    return row


def _section(sections, title):
    return next(s for s in sections if s.title == title)


def _items(sections, title):
    return {i.label: i.value for i in _section(sections, title).items}


def _item(sections, title, label):
    return next(i for i in _section(sections, title).items if i.label == label)


def _labels(sections, title):
    """The section's item labels, in display order."""
    return [i.label for i in _section(sections, title).items]


# --- section layout --------------------------------------------------------

def test_sections_run_basic_first_and_details_last():
    titles = [s.title for s in build_sections(_row())]
    assert titles == ["Basic", "Positive Prompt", "Negative Prompt",
                      "Parameters", "Details"]


def test_basic_leads_with_the_output_file_and_the_date():
    items = _section(build_sections(_row(created_at="2026-07-01")), "Basic").items
    assert items[0].label == "File"       # the output file leads, and carries a key
    assert items[0].value == "out.png"
    assert items[1].label == "Created"
    assert items[1].value == "2026-07-01"


def test_details_holds_only_status_and_source():
    assert _items(build_sections(_row()), "Details") == {
        "Status": "completed", "Source": "generated",
    }


# --- duration is gone (confusing, and shown elsewhere) ---------------------

def test_duration_is_not_shown_in_any_section():
    sections = build_sections(_row(duration_seconds=905.0))
    labels = [i.label for s in sections for i in s.items]
    assert "Duration" not in labels


# --- seed: shown once, in Parameters, and copyable -------------------------

def test_seed_shows_only_in_parameters_not_duplicated_elsewhere():
    sections = build_sections(_row(params_json=json.dumps({"steps": 20, "seed": 42})))
    assert _items(sections, "Parameters")["seed"] == "42"
    for title in ("Basic", "Details"):
        assert "seed" not in _items(sections, title)
        assert "Seed" not in _items(sections, title)


def test_seed_and_noise_seed_parameters_are_copyable():
    sections = build_sections(_row(params_json=json.dumps({"noise_seed": 5, "seed": 42})))
    assert _item(sections, "Parameters", "seed").copy == "42"
    assert _item(sections, "Parameters", "noise_seed").copy == "5"


def test_non_seed_parameters_are_not_copyable():
    sections = build_sections(_row(params_json=json.dumps({"steps": 20, "seed": 1})))
    assert _item(sections, "Parameters", "steps").copy is None


def test_parameters_section_lists_params_except_the_prompts():
    params = {"steps": 20, "cfg": 7, "positive_prompt": "a cat", "negative_prompt": "x"}
    assert _items(build_sections(_row(params_json=json.dumps(params))), "Parameters") == {
        "steps": "20", "cfg": "7",
    }


def test_parameters_follow_the_workflows_form_order_not_the_saved_order():
    # The info pane orders parameters by the workflow's param_definitions() — the
    # same source the Generate form lays out — not by however the row's JSON was
    # serialized. So a generation saved before the model/LoRA regroup still reads
    # grouped: all the models, then all the LoRAs.
    pre_regroup = {  # the old noise-major serialization: high block, then low block
        "unet_high": "mh", "lora_high": "lh", "lora_strength_high": 1.0,
        "unet_low": "ml", "lora_low": "ll", "lora_strength_low": 1.0,
    }
    row = _row(workflow_name="wan22_i2v", params_json=json.dumps(pre_regroup))
    assert _labels(build_sections(row), "Parameters") == [
        "unet_high", "unet_low",
        "lora_high", "lora_strength_high", "lora_low", "lora_strength_low",
    ]


def test_parameters_keep_keys_the_form_doesnt_lay_out_after_the_known_ones():
    # Hidden passthrough params (vae, clip…) aren't in the form's
    # param_definitions, but a row still recorded them — they show after the
    # ordered known params, in their stored order, never dropped.
    params = {"steps": 20, "vae_name": "v.safetensors", "cfg": 7}
    labels = _labels(build_sections(_row(workflow_name="wan22_i2v",
                                         params_json=json.dumps(params))), "Parameters")
    assert set(labels) == {"steps", "cfg", "vae_name"}    # nothing lost
    assert labels.index("steps") < labels.index("cfg")     # known ones in form order
    assert labels[-1] == "vae_name"                        # the unlaid-out key trails


def test_parameters_section_omitted_when_only_prompts_remain():
    params = {"positive_prompt": "a cat", "negative_prompt": "x"}
    sections = build_sections(_row(params_json=json.dumps(params)))
    assert all(s.title != "Parameters" for s in sections)


def test_input_image_param_links_to_its_source_image_when_one_is_given():
    params = {"steps": 20, "input_image": "sdxl_00007_.png [output]"}
    sections = build_sections(_row(params_json=json.dumps(params)), source_image_id="img1")
    item = _item(sections, "Parameters", "input_image")
    assert item.value == "sdxl_00007_.png [output]"  # the value the user already sees
    assert item.link == "img1"                        # now navigable to its source


def test_params_carry_no_link_without_a_source_image():
    params = {"steps": 20, "input_image": "hand_placed.png"}
    sections = build_sections(_row(params_json=json.dumps(params)))
    assert _item(sections, "Parameters", "input_image").link is None
    assert _item(sections, "Parameters", "steps").link is None


# --- prompts ---------------------------------------------------------------

def test_prompt_sections_carry_the_prompt_as_a_bare_value():
    sections = build_sections(_row(positive_prompt="a cat", negative_prompt="blurry"))
    [positive] = _section(sections, "Positive Prompt").items
    [negative] = _section(sections, "Negative Prompt").items
    assert (positive.label, positive.value) == ("", "a cat")
    assert (negative.label, negative.value) == ("", "blurry")


def test_prompt_items_are_copyable_with_their_text():
    sections = build_sections(_row(positive_prompt="a cat", negative_prompt="blurry"))
    assert _section(sections, "Positive Prompt").items[0].copy == "a cat"
    assert _section(sections, "Negative Prompt").items[0].copy == "blurry"


def test_empty_prompt_shows_no_text_and_a_disabled_copy():
    sections = build_sections(_row(positive_prompt="", negative_prompt=None))
    for title in ("Positive Prompt", "Negative Prompt"):
        [item] = _section(sections, title).items
        assert item.value == ""   # no "(empty)" masquerading as the prompt
        assert item.copy == ""    # a copy button, but disabled (nothing to copy)


# --- output file copy ------------------------------------------------------

def test_output_file_copies_only_the_filename_not_the_subfolder():
    files = [{"filename": "wan_00001_.mp4", "subfolder": "video"}]
    file_item = _item(build_sections(_row(output_files=json.dumps(files))), "Basic", "File")
    assert file_item.value == "video/wan_00001_.mp4"  # shown with its subfolder
    assert file_item.copy == "wan_00001_.mp4"          # copied without it


def test_basic_has_no_file_rows_when_there_are_no_outputs():
    labels = {i.label for i in _section(build_sections(_row(output_files=None)), "Basic").items}
    assert "File" not in labels   # no file row
    assert "Created" in labels     # but the date still shows
