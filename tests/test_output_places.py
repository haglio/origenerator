import _winapi
from pathlib import Path

from origenerator import config
from origenerator.output_places import OutputPlaces


def test_a_record_kept_in_one_folder_names_its_file_under_that_folder(tmp_path):
    places = OutputPlaces.in_one_folder(tmp_path)

    assert places.folder("video") == tmp_path / "video"
    assert places.folder("image/kept") == tmp_path / "image" / "kept"
    assert places.folder("") == tmp_path


def _library(tmp_path: Path) -> dict:
    library = tmp_path / "library"
    return {
        "comfyui_output_dir": str(tmp_path / "comfyui saves"),
        "origenerator_images_dir": str(library / "images"),
        "origenerator_videos_dir": str(library / "videos"),
        "origenerator_scripts_dir": str(library / "scripts"),
        "origenerator_audio_dir": str(library / "sounds"),
    }


def test_the_settings_send_each_kind_of_output_to_its_own_library_folder(tmp_path):
    places = OutputPlaces.from_settings(_library(tmp_path), comfyui_dir=tmp_path / "ComfyUI")

    library = tmp_path / "library"
    assert places.folder("image") == library / "images"
    assert places.folder("video/kept") == library / "videos" / "video" / "kept"
    assert places.folder("funscript/video") == library / "scripts" / "video"
    assert places.folder("audio") == library / "sounds"
    assert places.folder("") == tmp_path / "comfyui saves"


def test_scripts_and_sounds_with_no_folder_of_their_own_stay_with_the_videos(tmp_path):
    settings = _library(tmp_path)
    del settings["origenerator_scripts_dir"], settings["origenerator_audio_dir"]

    places = OutputPlaces.from_settings(settings, comfyui_dir=tmp_path / "ComfyUI")

    videos = tmp_path / "library" / "videos"
    assert places.folder("funscript/video") == videos / "funscript" / "video"
    assert places.folder("audio") == videos / "audio"


def test_the_apps_places_name_the_trash_its_deletes_go_to():
    assert config.OUTPUT_PLACES.trash == config.TRASH_DIR


def test_with_no_library_folders_every_output_stays_in_comfyuis_own_folder(tmp_path):
    places = OutputPlaces.from_settings({}, comfyui_dir=tmp_path / "ComfyUI")

    assert places == OutputPlaces.in_one_folder(tmp_path / "ComfyUI" / "output")


def test_a_folder_in_the_library_reads_back_as_the_subfolder_a_record_names(tmp_path):
    places = OutputPlaces.from_settings(_library(tmp_path), comfyui_dir=tmp_path / "ComfyUI")

    for subfolder in ("image", "image/kept", "video", "video/kept", "funscript/video", "audio", ""):
        assert places.subfolder_of(places.folder(subfolder)) == subfolder
    assert places.subfolder_of(places.videos) is None
    assert places.subfolder_of(tmp_path / "elsewhere") is None


def test_a_folder_kept_in_one_folder_reads_back_the_same_way(tmp_path):
    places = OutputPlaces.in_one_folder(tmp_path)

    for subfolder in ("image", "video", "video/kept", "funscript/video", ""):
        assert places.subfolder_of(places.folder(subfolder)) == subfolder


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


def test_every_file_in_the_library_is_found_with_the_subfolder_its_record_names(tmp_path):
    places = OutputPlaces.from_settings(_library(tmp_path), comfyui_dir=tmp_path / "ComfyUI")
    kept = {
        _touch(places.folder("image") / "a.png"): "image",
        _touch(places.folder("video/kept") / "b.mp4"): "video/kept",
        _touch(places.folder("funscript/video") / "b.mp4.funscript"): "funscript/video",
        _touch(places.folder("audio") / "c.wav"): "audio",
        _touch(places.comfyui / "loose.png"): "",
    }
    _touch(places.videos / "not filed in a folder.mp4")
    _touch(places.comfyui / "waiting" / "d.png")

    assert dict(places.files()) == kept


def test_files_kept_in_one_folder_leave_out_the_runs_waiting_there_and_every_link(tmp_path):
    places = OutputPlaces.in_one_folder(tmp_path / "saves")
    kept = {
        _touch(places.folder("image") / "a.png"): "image",
        _touch(places.folder("video") / "b.mp4"): "video",
        _touch(places.comfyui / "loose.png"): "",
    }
    _touch(places.working / "run" / "image" / "c.png")
    elsewhere = tmp_path / "elsewhere"
    _touch(elsewhere / "d.png")
    _winapi.CreateJunction(str(elsewhere), str(places.folder("linked")))

    assert dict(places.files()) == kept


def test_a_file_named_with_its_folder_is_found_in_the_place_that_folder_names(tmp_path):
    places = OutputPlaces.from_settings(_library(tmp_path), comfyui_dir=tmp_path / "ComfyUI")

    assert places.file("image/a.png") == places.folder("image") / "a.png"
    assert places.file("video/kept/b.mp4") == places.folder("video/kept") / "b.mp4"
    assert places.file("loose.png") == places.comfyui / "loose.png"
    assert places.file(".hidden/c.png") == places.folder(".hidden") / "c.png"


def test_videos_are_kept_in_the_folders_of_the_videos_place_alone(tmp_path):
    places = OutputPlaces.in_one_folder(tmp_path)
    for subfolder in ("image", "funscript", "audio", "video", "another"):
        places.folder(subfolder).mkdir(parents=True)
    places.working.mkdir()

    assert places.video_folders() == [places.folder("another"), places.folder("video")]


def test_outputs_count_as_kept_in_comfyuis_folder_only_when_a_place_lies_inside_it(tmp_path):
    assert OutputPlaces.in_one_folder(tmp_path).keeps_outputs_in_comfyuis_folder()
    assert not OutputPlaces.from_settings(
        _library(tmp_path), comfyui_dir=tmp_path / "ComfyUI").keeps_outputs_in_comfyuis_folder()
