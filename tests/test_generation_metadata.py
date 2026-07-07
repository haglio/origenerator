import json

from origenerator.generation_metadata import build_sections


def _row(**overrides):
    row = {
        "status": "completed",
        "source": "generated",
        "created_at": "2026-01-01",
        "workflow_name": "sdxl_t2i",
        "positive_prompt": "a cat",
        "negative_prompt": "blurry",
        "params_json": json.dumps({"positive_prompt": "a cat", "seed": 7}),
        "output_files": json.dumps([{"filename": "out.png", "subfolder": ""}]),
    }
    row.update(overrides)
    return row


def _section(sections, title):
    return next(s for s in sections if s.title == title)


def _items(sections, title):
    return {i.label: i.value for i in _section(sections, title).items}


# --- section layout --------------------------------------------------------

def test_basic_leads_with_the_output_file_and_the_date():
    items = _section(build_sections(_row(created_at="2026-07-01")), "Basic").items
    assert items[0].label == "File"
    assert items[0].value == "out.png"
    assert items[1].label == "Created"
    assert items[1].value == "2026-07-01"


def test_file_shows_the_subfolder_path_but_copies_just_the_filename():
    row = _row(output_files=json.dumps(
        [{"filename": "clip_00001.mp4", "subfolder": "video"}]
    ))
    file_item = _section(build_sections(row), "Basic").items[0]
    assert file_item.value == "video/clip_00001.mp4"
    assert file_item.copy == "clip_00001.mp4"


def test_every_output_file_gets_its_own_row():
    row = _row(output_files=json.dumps([
        {"filename": "a.png", "subfolder": ""}, {"filename": "b.png", "subfolder": ""},
    ]))
    files = [i.value for i in _section(build_sections(row), "Basic").items
             if i.label == "File"]
    assert files == ["a.png", "b.png"]


def test_details_holds_only_status_and_source():
    assert _items(build_sections(_row()), "Details") == {
        "Status": "completed", "Source": "generated",
    }


def test_source_defaults_to_generated_when_absent():
    row = _row()
    del row["source"]
    assert _items(build_sections(row), "Details")["Source"] == "generated"


# --- Parameters: only what the form has no field for -----------------------

def test_parameters_shows_only_params_the_form_has_no_field_for():
    # seed and positive_prompt are sdxl_t2i form fields (shown in the editable
    # form); vae is hidden passthrough with no field, so only it lands here.
    row = _row(params_json=json.dumps(
        {"seed": 7, "positive_prompt": "a cat", "vae": "sdxl.vae.safetensors"}
    ))
    assert _items(build_sections(row), "Parameters") == {"vae": "sdxl.vae.safetensors"}


def test_parameters_section_absent_when_every_param_is_in_the_form():
    row = _row(params_json=json.dumps({"seed": 7, "positive_prompt": "a cat"}))
    assert "Parameters" not in [s.title for s in build_sections(row)]


def test_sections_run_basic_then_parameters_then_details():
    row = _row(params_json=json.dumps({"vae": "x.safetensors"}))
    assert [s.title for s in build_sections(row)] == ["Basic", "Parameters", "Details"]


def test_an_unknown_workflow_shows_all_its_params_here():
    # An import with no registered template has no form to render its params, so
    # this read-only block becomes their only home — none are dropped.
    row = _row(workflow_name="imported_thing",
               params_json=json.dumps({"steps": 20, "cfg": 7.5}))
    assert _items(build_sections(row), "Parameters") == {"steps": "20", "cfg": "7.5"}


def test_a_seed_keyed_extra_param_is_copyable():
    # Only reachable for an unknown workflow (a known one puts seed in its form),
    # but when a seed does surface here it earns a copy button like it used to.
    row = _row(workflow_name="imported_thing", params_json=json.dumps({"seed": 42}))
    item = next(i for i in _section(build_sections(row), "Parameters").items
                if i.label == "seed")
    assert item.copy == "42"
