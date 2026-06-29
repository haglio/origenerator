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


def test_details_section_lists_status_source_seed_and_created():
    sections = build_sections(_row())
    details = _items(sections, "Details")
    assert details["Status"] == "completed"
    assert details["Source"] == "generated"
    assert details["Seed"] == "7"
    assert details["Created"] == "2026-01-01"


def test_details_includes_formatted_duration_when_present():
    sections = build_sections(_row(duration_seconds=905.0))
    assert _items(sections, "Details")["Duration"] == "15 min 5 sec"


def test_details_omits_duration_when_absent():
    sections = build_sections(_row())
    assert "Duration" not in _items(sections, "Details")


def test_prompt_sections_carry_the_prompt_as_a_bare_value():
    sections = build_sections(_row(positive_prompt="a cat", negative_prompt="blurry"))
    [positive] = _section(sections, "Positive Prompt").items
    [negative] = _section(sections, "Negative Prompt").items
    assert (positive.label, positive.value) == ("", "a cat")
    assert (negative.label, negative.value) == ("", "blurry")


def test_empty_prompt_falls_back_to_a_placeholder():
    sections = build_sections(_row(positive_prompt="", negative_prompt=None))
    assert _section(sections, "Positive Prompt").items[0].value == "(empty)"
    assert _section(sections, "Negative Prompt").items[0].value == "(empty)"


def test_parameters_section_lists_params_except_the_prompts():
    params = {"steps": 20, "cfg": 7, "positive_prompt": "a cat", "negative_prompt": "x"}
    sections = build_sections(_row(params_json=json.dumps(params)))
    items = _items(sections, "Parameters")
    assert items == {"steps": "20", "cfg": "7"}


def test_parameters_section_omitted_when_only_prompts_remain():
    params = {"positive_prompt": "a cat", "negative_prompt": "x"}
    sections = build_sections(_row(params_json=json.dumps(params)))
    assert all(s.title != "Parameters" for s in sections)


def test_output_files_section_lists_each_file_by_path():
    files = [
        {"filename": "a.png", "subfolder": ""},
        {"filename": "b.mp4", "subfolder": "videos"},
    ]
    sections = build_sections(_row(output_files=json.dumps(files)))
    values = [i.value for i in _section(sections, "Output Files").items]
    assert values == ["a.png", "videos/b.mp4"]


def test_output_files_section_omitted_when_there_are_none():
    sections = build_sections(_row(output_files=None))
    assert all(s.title != "Output Files" for s in sections)
