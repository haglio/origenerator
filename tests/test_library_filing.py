import _winapi
from pathlib import Path

from origenerator.library_filing import (
    file_into_library,
    file_what_comfyui_left,
    handed_to_comfyui,
)
from origenerator.output_places import OutputPlaces


def _places(tmp_path: Path) -> OutputPlaces:
    library = tmp_path / "library"
    return OutputPlaces(comfyui=tmp_path / "comfyui saves", pictures=library / "pictures",
                        videos=library / "videos", scripts=library / "scripts",
                        audio=library / "sounds")


def test_a_run_saves_into_a_folder_of_its_own_in_comfyuis_folder(tmp_path):
    payload = {"9": {"class_type": "SaveImage",
                     "inputs": {"images": ["8", 0], "filename_prefix": "image/alpha_t2i"}}}

    handed = handed_to_comfyui(payload, _places(tmp_path), "run-one").payload

    assert handed["9"]["inputs"]["filename_prefix"] == "origenerator/run-one/image/alpha_t2i"
    assert payload["9"]["inputs"]["filename_prefix"] == "image/alpha_t2i"


def _saved_by_comfyui(places: OutputPlaces, prompt_id: str, subfolder: str, name: str,
                      data: bytes = b"new") -> Path:
    path = places.run(prompt_id) / subfolder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _listed(prompt_id: str, subfolder: str, name: str, **extra) -> dict:
    return {"filename": name, "subfolder": f"origenerator/{prompt_id}/{subfolder}",
            "type": "output", **extra}


def test_a_finished_picture_is_filed_in_the_pictures_folder_after_the_highest_number_there(
        tmp_path):
    places = _places(tmp_path)
    places.pictures.mkdir(parents=True)
    (places.pictures / "alpha_t2i_00041_.png").write_bytes(b"old")
    _saved_by_comfyui(places, "run-one", "image", "alpha_t2i_00001_.png")

    filed = file_into_library([_listed("run-one", "image", "alpha_t2i_00001_.png")],
                              places, "run-one")

    assert filed == [{"filename": "alpha_t2i_00042_.png", "subfolder": "image", "type": "output"}]
    assert (places.pictures / "alpha_t2i_00042_.png").read_bytes() == b"new"
    assert (places.pictures / "alpha_t2i_00041_.png").read_bytes() == b"old"


def test_a_finished_videos_files_are_filed_together_under_one_number(tmp_path):
    places = _places(tmp_path)
    places.folder("video").mkdir(parents=True)
    (places.folder("video") / "beta_i2v_00761-audio.mp4").write_bytes(b"old")
    for name in ("beta_i2v_00001-audio.mp4", "beta_i2v_00001.mp4", "beta_i2v_00001.png"):
        _saved_by_comfyui(places, "run-two", "video", name)

    filed = file_into_library([_listed("run-two", "video", "beta_i2v_00001-audio.mp4"),
                               _listed("run-two", "video", "beta_i2v_00001.mp4", role="silent")],
                              places, "run-two")

    assert [(f["subfolder"], f["filename"]) for f in filed] == [
        ("video", "beta_i2v_00762-audio.mp4"), ("video", "beta_i2v_00762.mp4")]
    assert filed[1]["role"] == "silent"
    assert sorted(p.name for p in places.folder("video").iterdir()) == [
        "beta_i2v_00761-audio.mp4", "beta_i2v_00762-audio.mp4", "beta_i2v_00762.mp4",
        "beta_i2v_00762.png"]


def test_a_file_comfyui_reports_outside_the_runs_own_folder_is_left_where_it_is(tmp_path):
    places = _places(tmp_path)
    already = places.folder("image") / "alpha_t2i_00007_.png"
    already.parent.mkdir(parents=True)
    already.write_bytes(b"kept")
    record = {"filename": "alpha_t2i_00007_.png", "subfolder": "image", "type": "output"}

    assert file_into_library([record], places, "run-three") == [record]
    assert already.read_bytes() == b"kept"


def test_the_runs_folder_goes_once_everything_in_it_is_filed(tmp_path):
    places = _places(tmp_path)
    _saved_by_comfyui(places, "run-four", "image", "alpha_t2i_00001_.png")

    file_into_library([_listed("run-four", "image", "alpha_t2i_00001_.png")], places, "run-four")

    assert not places.run("run-four").exists()


def test_a_past_output_a_run_reads_is_handed_to_comfyui_as_a_copy_in_the_runs_folder(tmp_path):
    places = _places(tmp_path)
    picture = places.folder("image") / "alpha_t2i_00042_.png"
    picture.parent.mkdir(parents=True)
    picture.write_bytes(b"the picture")
    payload = {"3": {"class_type": "LoadImage",
                     "inputs": {"image": "image/alpha_t2i_00042_.png [output]"}}}

    handed = handed_to_comfyui(payload, places, "run-five")
    handed.copy_reads()

    reference = handed.payload["3"]["inputs"]["image"]
    assert reference == "origenerator/run-five/reads/image/alpha_t2i_00042_.png [output]"
    assert (places.comfyui / reference.removesuffix(" [output]")).read_bytes() == b"the picture"
    assert picture.read_bytes() == b"the picture"


def test_a_picture_picked_from_anywhere_on_disk_is_handed_over_as_a_copy_too(tmp_path):
    places = _places(tmp_path)
    picked = tmp_path / "poses" / "standing.png"
    picked.parent.mkdir()
    picked.write_bytes(b"a pose")
    payload = {"5": {"class_type": "LoadImage", "inputs": {"image": str(picked)}}}

    handed = handed_to_comfyui(payload, places, "run-six")
    handed.copy_reads()

    reference = handed.payload["5"]["inputs"]["image"]
    assert reference.endswith(" [output]")
    assert (places.comfyui / reference.removesuffix(" [output]")).read_bytes() == b"a pose"


def test_a_reference_to_a_file_that_is_gone_is_left_for_comfyui_to_refuse(tmp_path):
    payload = {"3": {"class_type": "LoadImage", "inputs": {"image": "image/gone_00001_.png [output]"}}}

    handed = handed_to_comfyui(payload, _places(tmp_path), "run-seven")

    assert handed.payload["3"]["inputs"]["image"] == "image/gone_00001_.png [output]"
    assert handed.reads == ()


def test_the_copies_a_run_read_go_once_its_outputs_are_filed(tmp_path):
    places = _places(tmp_path)
    picture = places.folder("image") / "alpha_t2i_00042_.png"
    picture.parent.mkdir(parents=True)
    picture.write_bytes(b"the picture")
    handed_to_comfyui({"3": {"class_type": "LoadImage",
                             "inputs": {"image": "image/alpha_t2i_00042_.png [output]"}}},
                      places, "run-eight").copy_reads()
    _saved_by_comfyui(places, "run-eight", "image", "alpha_enhance_00001_.png")

    file_into_library([_listed("run-eight", "image", "alpha_enhance_00001_.png")],
                      places, "run-eight")

    assert not places.run("run-eight").exists()
    assert picture.read_bytes() == b"the picture"


def test_what_another_program_saved_in_a_folder_of_comfyuis_is_filed_where_that_folder_names(
        tmp_path):
    places = _places(tmp_path)
    left = places.comfyui / "video" / "gamma_anim_00001.mp4"
    left.parent.mkdir(parents=True)
    left.write_bytes(b"theirs")

    assert file_what_comfyui_left(places, in_flight=set()) == 1

    assert (places.folder("video") / "gamma_anim_00001.mp4").read_bytes() == b"theirs"
    assert not (places.comfyui / "video").exists()


def test_a_run_still_in_flight_is_left_waiting_in_comfyuis_folder(tmp_path):
    places = _places(tmp_path)
    waiting = _saved_by_comfyui(places, "run-nine", "image", "alpha_t2i_00001_.png")

    assert file_what_comfyui_left(places, in_flight={"run-nine"}) == 0

    assert waiting.is_file()


def test_a_run_nobody_finished_has_its_outputs_filed_and_its_copies_cleared(tmp_path):
    places = _places(tmp_path)
    _saved_by_comfyui(places, "run-ten", "image", "alpha_t2i_00001_.png")
    _saved_by_comfyui(places, "run-ten", "reads/image", "alpha_t2i_00009_.png", data=b"copy")

    assert file_what_comfyui_left(places, in_flight=set()) == 1

    assert (places.pictures / "alpha_t2i_00001_.png").read_bytes() == b"new"
    assert not (places.pictures / "alpha_t2i_00009_.png").exists()
    assert not places.run("run-ten").exists()


def test_the_old_links_and_an_add_ons_scratch_folder_are_left_alone(tmp_path):
    places = _places(tmp_path)
    kept = places.pictures / "alpha_t2i_00003_.png"
    kept.parent.mkdir(parents=True)
    kept.write_bytes(b"kept")
    places.comfyui.mkdir()
    _winapi.CreateJunction(str(places.pictures), str(places.comfyui / "image"))
    scratch = places.comfyui / "VRGDG_TEMP" / "TextFiles" / "note_00001_.txt"
    scratch.parent.mkdir(parents=True)
    scratch.write_bytes(b"scratch")

    assert file_what_comfyui_left(places, in_flight=set()) == 0

    assert kept.read_bytes() == b"kept"
    assert scratch.read_bytes() == b"scratch"


def test_nothing_moves_when_comfyuis_folder_is_where_every_output_is_kept(tmp_path):
    places = OutputPlaces.in_one_folder(tmp_path / "saves")
    kept = places.folder("video") / "beta_i2v_00001.mp4"
    kept.parent.mkdir(parents=True)
    kept.write_bytes(b"kept")

    assert file_what_comfyui_left(places, in_flight=set()) == 0

    assert kept.read_bytes() == b"kept"


def test_a_comfyui_folder_that_holds_the_library_itself_has_only_its_runs_filed(tmp_path):
    library = tmp_path / "library"
    places = OutputPlaces(comfyui=library, pictures=library / "pictures",
                          videos=library / "videos", scripts=library / "scripts",
                          audio=library / "sounds")
    his = library / "projects" / "notes_00001_.txt"
    his.parent.mkdir(parents=True)
    his.write_bytes(b"his")
    _saved_by_comfyui(places, "run-eleven", "image", "alpha_t2i_00001_.png")

    assert file_what_comfyui_left(places, in_flight=set()) == 1

    assert his.read_bytes() == b"his"
    assert (places.pictures / "alpha_t2i_00001_.png").is_file()


def test_a_number_some_other_file_already_wears_is_passed_over(tmp_path):
    places = _places(tmp_path)
    places.folder("video").mkdir(parents=True)
    (places.folder("video") / "beta_i2v_00004-audio.mp4").write_bytes(b"old")
    (places.folder("video") / "beta_i2v_00005.png").write_bytes(b"a stray sidecar")
    _saved_by_comfyui(places, "run-twelve", "video", "beta_i2v_00001-audio.mp4")
    _saved_by_comfyui(places, "run-twelve", "video", "beta_i2v_00001.png")

    filed = file_into_library([_listed("run-twelve", "video", "beta_i2v_00001-audio.mp4")],
                              places, "run-twelve")

    assert filed[0]["filename"] == "beta_i2v_00006-audio.mp4"
    assert (places.folder("video") / "beta_i2v_00006.png").read_bytes() == b"new"


def test_a_run_comfyui_reports_with_windows_separators_is_filed_all_the_same(tmp_path):
    places = _places(tmp_path)
    _saved_by_comfyui(places, "run-thirteen", "image", "alpha_t2i_00001_.png")
    reported = {"filename": "alpha_t2i_00001_.png",
                "subfolder": r"origenerator\run-thirteen\image", "type": "output"}

    filed = file_into_library([reported], places, "run-thirteen")

    assert (filed[0]["subfolder"], filed[0]["filename"]) == ("image", "alpha_t2i_00001_.png")
    assert (places.pictures / "alpha_t2i_00001_.png").is_file()
