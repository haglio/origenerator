import json

from origenerator.generation_metadata import build_sections


def _row(**overrides):
    """A completed video — the shape whose file this block still carries.

    An image's files are each a version of it, listed with the level that made
    them; a video has no versions, so its file has nowhere else to be.
    """
    row = {
        "status": "completed",
        "source": "generated",
        "created_at": "2026-01-01",
        "workflow_name": "wan22_i2v",
        "positive_prompt": "a cat",
        "negative_prompt": "blurry",
        "params_json": json.dumps({"positive_prompt": "a cat", "seed": 7}),
        "output_files": json.dumps([{"filename": "clip.mp4", "subfolder": "video"}]),
    }
    row.update(overrides)
    return row


def _image_row(**overrides):
    return _row(**{
        "workflow_name": "sdxl_t2i",
        "output_files": json.dumps([{"filename": "out.png", "subfolder": ""}]),
        **overrides,
    })


def _section(sections, title):
    return next(s for s in sections if s.title == title)


# --- section layout --------------------------------------------------------

def test_basic_leads_with_the_output_file_and_the_date():
    items = _section(build_sections(_row(created_at="2026-07-01")), "Basic").items
    assert items[0].label == "File"
    assert items[0].value == "video/clip.mp4"
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
        {"filename": "a.mp4", "subfolder": ""}, {"filename": "b.mp4", "subfolder": ""},
    ]))
    files = [i.value for i in _section(build_sections(row), "Basic").items
             if i.label == "File"]
    assert files == ["a.mp4", "b.mp4"]


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


# --- an image's files belong to its versions, not to this block -------------

def test_an_image_has_no_block_at_all():
    # Its one file is its Original — listed down in the version list, beside the
    # enhancement (none, yet) that made it. Repeating it here under a second
    # label is exactly what moving it was for.
    assert build_sections(_image_row()) == []


def test_a_batch_still_lists_the_siblings_no_version_claims():
    # Several files out of one run are separate results, not versions of each
    # other, so only the first is listed as the image's Original. The rest have
    # nowhere else to appear and stay here.
    row = _image_row(output_files=json.dumps([
        {"filename": "a.png", "subfolder": ""},
        {"filename": "b.png", "subfolder": ""},
        {"filename": "c.png", "subfolder": ""},
    ]))
    files = [i.value for i in _section(build_sections(row), "Basic").items
             if i.label == "File"]
    assert files == ["b.png", "c.png"]
