from __future__ import annotations

import json

from origenerator.db import Database
from origenerator.generation_state import GenerationSource, GenerationStatus
from origenerator.take_in_ai_records import main, take_in

KINO_AI = ("kino", "2D", "AI", "portrait", "Example Site")


def _filed(library, video_name: str, record: dict, *, under=KINO_AI):
    video = library.joinpath("videos", "videos", *under, video_name)
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"")
    sidecar = library.joinpath("videos", "metadata", *under, video_name).with_suffix(".json")
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps(record), encoding="utf-8")
    return video


def _outside_row(db, prompt_id: str, video, **fields):
    db.insert_rows([{"prompt_id": prompt_id, "source": GenerationSource.OUTSIDE,
                     "workflow_name": "outside:Example Site", "workflow_version": "outside",
                     "status": GenerationStatus.COMPLETED, "params_json": "{}",
                     "workflow_json": "{}",
                     "output_files": json.dumps([{"filename": video.name,
                                                  "library_path": str(video)}]),
                     **fields}])


def test_a_favorite_in_a_sidecar_stars_the_outside_row_of_its_video(tmp_path):
    library, db = tmp_path / "library", Database(tmp_path / "gallery.db")
    video = _filed(library, "scene one.mp4", {"favorite": True})
    _outside_row(db, "out-1", video)

    counts = take_in(db, library)

    assert db.get_generation("out-1")["starred"] == 1
    assert counts["stars added"] == 1


def test_a_sidecar_never_takes_a_star_away_and_a_star_already_there_is_not_added_again(tmp_path):
    library, db = tmp_path / "library", Database(tmp_path / "gallery.db")
    _outside_row(db, "out-1", _filed(library, "scene one.mp4", {"favorite": False}), starred=1)
    _outside_row(db, "out-2", _filed(library, "scene two.mp4", {"favorite": True}), starred=1)

    counts = take_in(db, library)

    assert [db.get_generation(one)["starred"] for one in ("out-1", "out-2")] == [1, 1]
    assert counts["stars added"] == 0


def test_a_sidecar_whose_video_is_gone_or_has_no_row_writes_nothing_and_is_counted(tmp_path):
    library, db = tmp_path / "library", Database(tmp_path / "gallery.db")
    gone = _filed(library, "scene one.mp4", {"favorite": True})
    gone.unlink()
    _filed(library, "scene two.mp4", {"favorite": True})

    counts = take_in(db, library)

    assert (counts["records read"], counts["no video"], counts["no row"], counts["matched"]) == (
        2, 1, 1, 0)


def test_a_sidecars_watch_counts_and_what_the_library_knows_of_the_video_land_on_its_row(tmp_path):
    library, db = tmp_path / "library", Database(tmp_path / "gallery.db")
    upscale = {"tool": "Example Upscaler", "settings": "made-up"}
    video = _filed(library, "scene one.mp4", {
        "id": "made-up-id", "web_url": "https://example.com/watch/101",
        "watch": {"completions": 3, "skips": 1, "locks": 2, "weight": 2.0},
        "provenance": {"upscale": upscale}})
    _outside_row(db, "out-1", video)

    counts = take_in(db, library)

    row = db.get_generation("out-1")
    assert (row["watch_completions"], row["watch_skips"], row["watch_locks"]) == (3, 1, 2)
    assert (row["web_url"], row["library_id"], json.loads(row["upscale_provenance"])) == (
        "https://example.com/watch/101", "made-up-id", upscale)
    assert (counts["counts written"], counts["library records written"]) == (1, 1)


def test_a_sidecars_action_lands_only_on_a_row_that_has_none(tmp_path):
    library, db = tmp_path / "library", Database(tmp_path / "gallery.db")
    _outside_row(db, "out-1", _filed(library, "scene one.mp4", {"video": {"action": "alpha"}}))
    _outside_row(db, "out-2", _filed(library, "scene two.mp4", {"video": {"action": "alpha"}}),
                 recipe_category="beta")

    counts = take_in(db, library)

    assert [db.get_generation(one)["action"] for one in ("out-1", "out-2")] == ["alpha", "beta"]
    assert counts["actions added"] == 1


def test_an_outside_row_takes_the_sidecars_settings_only_where_it_has_none(tmp_path):
    library, db = tmp_path / "library", Database(tmp_path / "gallery.db")
    video = _filed(library, "scene one.mp4", {"video": {
        "prompt": "a lighthouse at dusk", "model": "Motion A", "seed": "101", "quality": "high"}})
    _outside_row(db, "out-1", video,
                 params_json=json.dumps({"model": "Motion B", "input_image": "frame.jpg"}))

    counts = take_in(db, library)

    row = db.get_generation("out-1")
    assert json.loads(row["params_json"]) == {
        "model": "Motion B", "input_image": "frame.jpg", "positive_prompt": "a lighthouse at dusk",
        "seed": "101", "quality": "high"}
    assert (row["positive_prompt"], row["seed"]) == ("a lighthouse at dusk", 101)
    assert counts["settings filled in"] == 1


def _made_here(db, prompt_id: str, filename: str, **fields):
    db.insert_rows([{"prompt_id": prompt_id, "workflow_name": "wan22_i2v", "workflow_version": "v1",
                     "status": GenerationStatus.COMPLETED, "params_json": "{}",
                     "workflow_json": "{}",
                     "output_files": json.dumps([{"filename": filename, "subfolder": "video"}]),
                     **fields}])


def test_a_video_this_app_made_is_found_by_its_upscale_or_else_by_the_name_it_was_made_with(tmp_path):
    library, db = tmp_path / "library", Database(tmp_path / "gallery.db")
    _filed(library, "alpha_00007_topaz.mp4", {"favorite": True})
    upscaled = _filed(library, "renamed by hand.mp4", {"favorite": True})
    _made_here(db, "gen-1", "alpha_00007.mp4")
    _made_here(db, "gen-2", "beta_00003.mp4", evolver_upscale=str(upscaled))

    counts = take_in(db, library)

    assert [db.get_generation(one)["starred"] for one in ("gen-1", "gen-2")] == [1, 1]
    assert counts["matched"] == 2


def test_kinos_ai_folder_origenerators_and_genaus_records_are_read_and_no_non_ai_record_is(tmp_path):
    library, db = tmp_path / "library", Database(tmp_path / "gallery.db")
    places = {"origenerator": ("origenerator", "video", "portrait"),
              "genau": ("genau", "loops", "2D", "AI", "portrait"),
              "kino non-AI": ("kino", "2D", "non_AI", "portrait"),
              "kino outside its AI folder": ("kino", "VR", "portrait"),
              "genau non-AI": ("genau", "loops", "2D", "non_AI", "portrait"),
              "genau VR": ("genau", "loops", "VR"),
              "elsewhere": ("evolver", "inbox")}
    for number, (name, under) in enumerate(places.items()):
        _outside_row(db, name, _filed(library, f"scene {number}.mp4", {"favorite": True},
                                      under=under))

    counts = take_in(db, library)

    assert [name for name in places if db.get_generation(name)["starred"]] == [
        "origenerator", "genau"]
    assert counts["records read"] == 2


def test_a_dry_run_counts_what_it_would_write_and_writes_nothing(tmp_path):
    library, db = tmp_path / "library", Database(tmp_path / "gallery.db")
    _outside_row(db, "out-1", _filed(library, "scene one.mp4", {
        "favorite": True, "watch": {"completions": 3}, "web_url": "https://example.com/watch/101",
        "video": {"action": "alpha", "prompt": "a lighthouse at dusk"}}))
    before = db.get_generation("out-1")

    counts = take_in(db, library, dry_run=True)

    assert db.get_generation("out-1") == before
    assert counts == take_in(db, library)


def test_a_sidecar_that_is_not_a_record_is_counted_and_passed_over(tmp_path):
    library, db = tmp_path / "library", Database(tmp_path / "gallery.db")
    _outside_row(db, "out-1", _filed(library, "scene one.mp4", {"favorite": True}))
    broken = library.joinpath("videos", "metadata", *KINO_AI, "scene two.json")
    broken.write_text("{not json", encoding="utf-8")
    listed = library.joinpath("videos", "metadata", *KINO_AI, "scene three.json")
    listed.write_text("[]", encoding="utf-8")

    counts = take_in(db, library)

    assert (counts["unreadable"], counts["stars added"]) == (2, 1)


def test_run_from_the_command_line_it_prints_only_counts(tmp_path, capsys):
    library, db = tmp_path / "library", Database(tmp_path / "gallery.db")
    _outside_row(db, "out-1", _filed(library, "scene one.mp4", {
        "favorite": True, "web_url": "https://example.com/watch/101"}))
    _filed(library, "scene two.mp4", {"favorite": True})

    _filed(library, "scene three.mp4", {"favorite": True}, under=("genau", "loops", "2D", "AI", "portrait"))

    assert main(["--db", str(db.path), "--library", str(library), "--dry-run"],
                phone_records=_never_written) == 0

    by_folder = "(kino {}, origenerator {}, genau {})".format
    assert capsys.readouterr().out.splitlines() == [
        f"records read: 3 {by_folder(2, 0, 1)}", f"unreadable: 0 {by_folder(0, 0, 0)}",
        f"no video: 0 {by_folder(0, 0, 0)}", f"no row: 2 {by_folder(1, 0, 1)}",
        f"left out of the gallery: 0 {by_folder(0, 0, 0)}", f"matched: 1 {by_folder(1, 0, 0)}",
        f"stars added: 1 {by_folder(1, 0, 0)}", f"counts written: 0 {by_folder(0, 0, 0)}",
        f"library records written: 1 {by_folder(1, 0, 0)}",
        f"actions added: 0 {by_folder(0, 0, 0)}", f"flips added: 0 {by_folder(0, 0, 0)}",
        f"sizes added: 0 {by_folder(0, 0, 0)}",
        f"settings filled in: 0 {by_folder(0, 0, 0)}"]
    assert db.get_generation("out-1")["starred"] == 0


def _never_written(db):
    raise AssertionError("a dry run writes nothing, the phone's file included")


def test_a_take_in_that_wrote_to_the_gallery_rewrites_the_phones_file_from_it(tmp_path, capsys):
    library, db = tmp_path / "library", Database(tmp_path / "gallery.db")
    _outside_row(db, "out-1", _filed(library, "scene one.mp4", {"favorite": True}))
    written = []

    class _Phone:
        def __init__(self, gallery):
            self.gallery = gallery

        def write(self):
            written.append(self.gallery.get_generation("out-1")["starred"])

    assert main(["--db", str(db.path), "--library", str(library)], phone_records=_Phone) == 0

    assert written == [1]


def test_the_command_line_refuses_a_gallery_that_is_not_there(tmp_path):
    assert main(["--db", str(tmp_path / "none.db"), "--library", str(tmp_path)]) == 2
    assert not (tmp_path / "none.db").exists()


def test_a_video_whose_row_is_left_out_of_the_gallery_is_counted_apart_and_left_alone(tmp_path):
    library, db = tmp_path / "library", Database(tmp_path / "gallery.db")
    _outside_row(db, "out-1", _filed(library, "scene one.mp4", {"favorite": True}),
                 source=GenerationSource.LEFT_OUT)

    counts = take_in(db, library)

    assert (counts["left out of the gallery"], counts["no row"], counts["matched"]) == (1, 0, 0)
    assert db.rows_left_out()[0]["starred"] == 0


def test_a_row_naming_its_video_by_file_name_alone_is_found_by_that_name(tmp_path):
    library, db = tmp_path / "library", Database(tmp_path / "gallery.db")
    _filed(library, "alpha_00009_-audio_topaz (2).mp4", {"favorite": True})
    db.insert_rows([{"prompt_id": "gen-1", "workflow_name": "wan22_i2v", "workflow_version": "v1",
                     "status": GenerationStatus.COMPLETED, "params_json": "{}",
                     "workflow_json": "{}",
                     "output_files": json.dumps([{"filename": "alpha_00009_.mp4"}])}])

    assert (take_in(db, library)["matched"], db.get_generation("gen-1")["starred"]) == (1, 1)


def test_a_genau_copy_of_a_video_made_here_is_found_under_any_name_the_lanes_gave_it(tmp_path):
    library, db = tmp_path / "library", Database(tmp_path / "gallery.db")
    for name in ("beta_00003__topaz.mp4", "beta_00003_-audio_topaz.mp4", "beta_00003_ (2).mp4"):
        _filed(library, name, {"favorite": True}, under=("genau", "loops", "2D", "AI", "portrait"))
    _made_here(db, "gen-2", "beta_00003_.mp4")

    assert take_in(db, library)["matched"] == 3


def test_a_flick_turned_over_in_genau_stays_turned_over_on_its_row(tmp_path):
    library, db = tmp_path / "library", Database(tmp_path / "gallery.db")
    under = ("genau", "loops", "2D", "AI", "portrait")
    _outside_row(db, "out-1", _filed(library, "scene one.mp4", {"genau": {"flipped": True}},
                                     under=under))
    _outside_row(db, "out-2", _filed(library, "scene two.mp4", {"genau": {}}, under=under))

    counts = take_in(db, library)

    assert [db.get_generation(one)["genau_flipped"] for one in ("out-1", "out-2")] == [1, 0]
    assert counts["flips added"] == 1


def test_the_size_a_sidecar_gave_a_video_made_here_lands_on_its_row_where_it_has_none(tmp_path):
    library, db = tmp_path / "library", Database(tmp_path / "gallery.db")
    _filed(library, "alpha_00007_topaz.mp4",
           {"video": {"resolution": "832x480", "aspect_ratio": "16:9"}})
    _filed(library, "beta_00003_topaz.mp4",
           {"video": {"resolution": "832x480", "aspect_ratio": "16:9"}})
    _made_here(db, "gen-1", "alpha_00007.mp4")
    _made_here(db, "gen-2", "beta_00003.mp4", video_resolution="480x832", video_aspect_ratio="9:16")

    counts = take_in(db, library)

    assert [(db.get_generation(one)["video_resolution"], db.get_generation(one)["video_aspect_ratio"])
            for one in ("gen-1", "gen-2")] == [("832x480", "16:9"), ("480x832", "9:16")]
    assert counts["sizes added"] == 1
