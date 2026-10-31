"""What a run hands ComfyUI for each file it loads, so that ComfyUI can open it.

Every file here is fabricated and lives under the test's own folders (see CLAUDE.md).
"""
from __future__ import annotations

import _winapi
from pathlib import Path

from origenerator import config
from origenerator.comfyui_inputs import HANDED_OVER, ComfyFolders, within_reach
from origenerator.db import Database
from origenerator.output_places import OutputPlaces


def _folders(tmp_path: Path) -> ComfyFolders:
    folders = ComfyFolders(input=tmp_path / "input", places=OutputPlaces.in_one_folder(tmp_path / "output"),
                           temp=tmp_path / "temp")
    for folder in (folders.input, folders.places.comfyui, folders.temp):
        folder.mkdir()
    return folders


def _image(path: Path, content: bytes = b"fabricated image bytes") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _load_image(ref: str) -> dict:
    return {"1": {"class_type": "LoadImage", "inputs": {"image": ref}}}


def _handed_over(folders: ComfyFolders) -> list[Path]:
    return sorted((folders.temp / HANDED_OVER).rglob("*.*"))


def test_an_image_named_by_its_whole_path_goes_to_comfyui_as_a_copy_in_its_temp_folder(tmp_path):
    folders = _folders(tmp_path)
    image = _image(tmp_path / "elsewhere" / "jane_doe.png")
    payload = _load_image(str(image))

    posted = within_reach(payload, folders)

    ref = posted["1"]["inputs"]["image"]
    assert ref.startswith(f"{HANDED_OVER}/")
    assert ref.endswith("/jane_doe.png [temp]")
    copies = _handed_over(folders)
    assert len(copies) == 1
    assert copies[0].read_bytes() == image.read_bytes()
    assert ref == f"{copies[0].relative_to(folders.temp).as_posix()} [temp]"
    assert payload["1"]["inputs"]["image"] == str(image), "the run keeps the name it was given"


def test_a_file_comfyui_can_already_open_is_left_as_it_was_named(tmp_path):
    folders = _folders(tmp_path)
    _image(folders.input / "in_reach.png")
    _image(folders.places.images / "made_here.png")
    _image(folders.temp / "scratch" / "preview.png")
    payload = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "in_reach.png"}},
        "2": {"class_type": "LoadImage", "inputs": {"image": "image/made_here.png [output]"}},
        "3": {"class_type": "LoadImage", "inputs": {"image": "scratch/preview.png [temp]"}},
    }

    assert within_reach(payload, folders) == payload
    assert _handed_over(folders) == []


def test_an_output_reference_reached_through_a_link_into_another_place_is_copied_too(tmp_path):
    folders = _folders(tmp_path)
    library = tmp_path / "library"
    image = _image(library / "jane_doe.png")
    _winapi.CreateJunction(str(library), str(folders.places.images))

    posted = within_reach(_load_image("image/jane_doe.png [output]"), folders)

    assert posted["1"]["inputs"]["image"].endswith("/jane_doe.png [temp]")
    assert [copy.read_bytes() for copy in _handed_over(folders)] == [image.read_bytes()]


def test_an_output_kept_in_the_library_goes_to_comfyui_as_a_copy_in_its_temp_folder(tmp_path):
    library = tmp_path / "library"
    places = OutputPlaces(comfyui=tmp_path / "output", images=library / "images",
                          videos=library / "videos", scripts=library / "scripts",
                          audio=library / "sounds")
    folders = ComfyFolders(input=tmp_path / "input", places=places, temp=tmp_path / "temp")
    image = _image(places.images / "alpha_t2i_00007_.png")

    posted = within_reach(_load_image("image/alpha_t2i_00007_.png [output]"), folders)

    assert posted["1"]["inputs"]["image"].endswith("/alpha_t2i_00007_.png [temp]")
    assert [copy.read_bytes() for copy in _handed_over(folders)] == [image.read_bytes()]


def test_a_reference_video_and_a_reference_sound_are_handed_over_like_an_image(tmp_path):
    folders = _folders(tmp_path)
    video = _image(tmp_path / "elsewhere" / "jane_doe.mp4", b"fabricated video bytes")
    sound = _image(tmp_path / "elsewhere" / "jane_doe.wav", b"fabricated sound bytes")
    payload = {
        "1": {"class_type": "LoadVideo", "inputs": {"file": str(video)}},
        "2": {"class_type": "LoadAudio", "inputs": {"audio": str(sound)}},
    }

    posted = within_reach(payload, folders)

    assert posted["1"]["inputs"]["file"].endswith("/jane_doe.mp4 [temp]")
    assert posted["2"]["inputs"]["audio"].endswith("/jane_doe.wav [temp]")
    assert sorted(copy.name for copy in _handed_over(folders)) == ["jane_doe.mp4", "jane_doe.wav"]


def test_the_same_image_handed_over_twice_is_copied_once(tmp_path):
    folders = _folders(tmp_path)
    image = _image(tmp_path / "elsewhere" / "jane_doe.png")

    first = within_reach(_load_image(str(image)), folders)
    second = within_reach(_load_image(str(image)), folders)

    assert first == second
    assert len(_handed_over(folders)) == 1


def test_an_image_in_the_trash_goes_to_comfyui_as_a_copy_in_its_temp_folder(tmp_path):
    folders = _folders(tmp_path)
    trashed = _image(tmp_path / "trash" / "batch" / "1_alpha_t2i_00007_.png")
    folders = folders._replace(trashed={folders.places.file("image/alpha_t2i_00007_.png"): trashed}.get)

    posted = within_reach(_load_image("image/alpha_t2i_00007_.png [output]"), folders)

    assert posted["1"]["inputs"]["image"].endswith("/1_alpha_t2i_00007_.png [temp]")
    assert [copy.read_bytes() for copy in _handed_over(folders)] == [trashed.read_bytes()]


def test_a_reference_to_a_file_that_is_not_there_is_left_for_comfyui_to_refuse(tmp_path):
    folders = _folders(tmp_path)
    payload = _load_image(str(tmp_path / "elsewhere" / "gone.png"))

    assert within_reach(payload, folders) == payload
    assert _handed_over(folders) == []


def test_only_the_loading_nodes_file_inputs_are_touched(tmp_path):
    folders = _folders(tmp_path)
    image = _image(tmp_path / "elsewhere" / "jane_doe.png")
    payload = {
        "1": {"class_type": "LoadImage", "inputs": {"image": str(image)}},
        "2": {"class_type": "Fabricated", "inputs": {"image": str(image), "images": ["1", 0]}},
        "3": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": "image/sample"}},
    }

    posted = within_reach(payload, folders)

    assert posted["1"] != payload["1"]
    assert posted["2"] == payload["2"]
    assert posted["3"] == payload["3"]


def test_the_apps_folders_are_comfyuis_input_and_temp_and_the_places_outputs_are_kept():
    assert config.COMFYUI_FOLDERS[:3] == (config.COMFYUI_INPUT_DIR, config.OUTPUT_PLACES, config.COMFYUI_TEMP_DIR)


def test_the_app_finds_an_image_gone_from_its_place_in_the_librarys_trash(tmp_path):
    db = Database(config.DB_PATH)
    original = config.OUTPUT_PLACES.file("image/alpha_t2i_00007_.png")
    held = _image(tmp_path / "1_alpha_t2i_00007_.png")
    db.record_deletion("held-for-this-test", {"prompt_id": "held-for-this-test"},
                       {"moves": [[str(original), str(held)]], "subdir": str(tmp_path)})
    try:
        assert config.COMFYUI_FOLDERS.trashed(original) == held
    finally:
        db.forget_deletion("held-for-this-test")
