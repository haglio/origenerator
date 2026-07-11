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


def test_file_item_reveals_the_absolute_output_path():
    # The File row carries the on-disk path (output folder + subfolder + name) so
    # a Show-in-Explorer button can reveal it, while its value stays the short
    # displayed path.
    from origenerator.config import COMFYUI_OUTPUT_DIR

    row = _row(output_files=json.dumps([{"filename": "clip.mp4", "subfolder": "video"}]))
    file_item = _section(build_sections(row), "Basic").items[0]
    assert file_item.reveal == str(COMFYUI_OUTPUT_DIR / "video" / "clip.mp4")


def test_created_row_carries_no_reveal_path():
    # Only the output file is a real thing on disk; the date has nothing to reveal.
    created = _section(build_sections(_row()), "Basic").items[1]
    assert created.label == "Created"
    assert created.reveal is None


def test_basic_is_the_only_section():
    # Params — editable or read-only passthrough — now live in the form itself, so
    # this block is just the output file and its date; there's no Parameters section.
    row = _row(params_json=json.dumps({"vae": "x.safetensors"}))
    assert [s.title for s in build_sections(row)] == ["Basic"]
