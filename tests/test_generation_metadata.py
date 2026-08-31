import json

from origenerator.generation_metadata import basic_section, created_item, file_item


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


# --- section layout --------------------------------------------------------

def test_basic_leads_with_the_output_file_and_the_date():
    items = basic_section(_row(created_at="2026-07-01")).items
    assert items[0].label == "File"
    assert items[0].value == "video/clip.mp4"
    assert items[1].label == "Created"
    assert items[1].value == "2026-07-01"


def test_file_shows_the_subfolder_path_but_copies_just_the_filename():
    row = _row(output_files=json.dumps(
        [{"filename": "clip_00001.mp4", "subfolder": "video"}]
    ))
    file_item = basic_section(row).items[0]
    assert file_item.value == "video/clip_00001.mp4"
    assert file_item.copy == "clip_00001.mp4"


def test_every_output_file_gets_its_own_row():
    row = _row(output_files=json.dumps([
        {"filename": "a.mp4", "subfolder": ""}, {"filename": "b.mp4", "subfolder": ""},
    ]))
    files = [i.value for i in basic_section(row).items
             if i.label == "File"]
    assert files == ["a.mp4", "b.mp4"]


def test_file_item_reveals_the_absolute_output_path():
    # The File row carries the on-disk path (output folder + subfolder + name) so
    # a Show-in-Explorer button can reveal it, while its value stays the short
    # displayed path.
    from origenerator.config import COMFYUI_OUTPUT_DIR

    row = _row(output_files=json.dumps([{"filename": "clip.mp4", "subfolder": "video"}]))
    file_item = basic_section(row).items[0]
    assert file_item.reveal == str(COMFYUI_OUTPUT_DIR / "video" / "clip.mp4")


def test_file_item_reveals_a_deleted_items_file_where_it_now_sits():
    # The bin re-points a deleted row's files at the trash; Show in Explorer has
    # to follow them there, or it points at a folder the file left.
    row = _row(output_files=json.dumps([{"filename": "clip.mp4", "subfolder": "video",
                                         "path": r"C:\state\trash\abc\0_clip.mp4"}]))
    file_item = basic_section(row).items[0]
    assert file_item.reveal == r"C:\state\trash\abc\0_clip.mp4"


# --- a deleted item's file line says how long it has been in the trash -------

def test_a_deleted_items_file_line_leads_with_its_days_in_the_trash():
    file_item = basic_section(_row(days_in_trash=3)).items[0]
    assert file_item.value == "(3 days in trash) video/clip.mp4"
    assert file_item.copy == "clip.mp4"  # the copy button still hands over the name


def test_one_day_in_the_trash_reads_as_one_day():
    file_item = basic_section(_row(days_in_trash=1)).items[0]
    assert file_item.value.startswith("(1 day in trash)")


def test_an_item_binned_today_says_so_rather_than_counting_zero():
    file_item = basic_section(_row(days_in_trash=0)).items[0]
    assert file_item.value == "(deleted today) video/clip.mp4"


def test_a_live_items_file_line_says_nothing_about_the_trash():
    file_item = basic_section(_row()).items[0]
    assert file_item.value == "video/clip.mp4"


def test_created_row_carries_no_reveal_path():
    # Only the output file is a real thing on disk; the date has nothing to reveal.
    created = basic_section(_row()).items[1]
    assert created.label == "Created"
    assert created.reveal is None


def test_a_passthrough_param_does_not_grow_a_second_block():
    # Params — editable or read-only passthrough — now live in the form itself, so
    # this block stays the output file and its date whatever a row carries.
    row = _row(params_json=json.dumps({"vae": "x.safetensors"}))
    section = basic_section(row)
    assert section.title == "Basic"
    assert [item.label for item in section.items] == ["File", "Created"]


# --- an image's files belong to its versions, not to this block -------------

def test_an_image_has_no_block_at_all():
    # Its one file is its Original — listed down in the version list, beside the
    # enhancement (none, yet) that made it. Repeating it here under a second
    # label is exactly what moving it was for.
    assert basic_section(_image_row()) is None


def test_a_batch_still_lists_the_siblings_no_version_claims():
    # Several files out of one run are separate results, not versions of each
    # other, so only the first is listed as the image's Original. The rest have
    # nowhere else to appear and stay here.
    row = _image_row(output_files=json.dumps([
        {"filename": "a.png", "subfolder": ""},
        {"filename": "b.png", "subfolder": ""},
        {"filename": "c.png", "subfolder": ""},
    ]))
    files = [i.value for i in basic_section(row).items
             if i.label == "File"]
    assert files == ["b.png", "c.png"]


def test_a_files_row_can_be_pointed_at_a_different_output_folder(tmp_path):
    """It resolved every path against the global `COMFYUI_OUTPUT_DIR` from
    inside the function, so nothing in the signature said it touched the
    filesystem at all, and it could not be pointed at another library without
    monkeypatching a module. Its neighbours -- importer, completion, reconcile,
    base_backfill, recovery -- all take the folder as an argument."""
    item = file_item({"filename": "alpha_00001_.png", "subfolder": "image"},
                     output_dir=tmp_path / "elsewhere")

    assert item.reveal == str(tmp_path / "elsewhere" / "image" / "alpha_00001_.png")


def test_created_reads_the_file_in_the_folder_it_is_given(tmp_path):
    written = tmp_path / "elsewhere" / "image"
    written.mkdir(parents=True)
    (written / "alpha_00001_.png").write_bytes(b"a picture")

    item = created_item({"filename": "alpha_00001_.png", "subfolder": "image"},
                        "never", output_dir=tmp_path / "elsewhere")

    assert item.value != "never"


def test_the_output_folder_still_defaults_to_the_configured_one(tmp_path, monkeypatch):
    """Resolved when it is called, not bound when the module was imported."""
    from origenerator import config

    monkeypatch.setattr(config, "COMFYUI_OUTPUT_DIR", tmp_path / "configured")

    item = file_item({"filename": "alpha_00001_.png", "subfolder": "image"})

    assert item.reveal == str(tmp_path / "configured" / "image" / "alpha_00001_.png")
