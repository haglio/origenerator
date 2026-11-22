from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from app_support import favorites
from app_support.gallery_rows import made_here
from app_support.mirrored_tree import filed_record
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from shared_ui.spacing import MARGIN_STANDARD

from origenerator import config, display_names
from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gallery import (
    SettingsGroup,
    build_gallery_tree,
    child_groups,
    resolve_preview,
)
from origenerator.gallery.non_ai import alternate_versions, recorded_title
from origenerator.gallery.tree import ALL_KEY, folder_chain
from origenerator.gallery_edits import GalleryEdits, GalleryEnvironment
from origenerator.generation_state import GenerationSource
from origenerator.gui.generate_tab import GenerateTab
from origenerator.item_actions import ItemActions, actions_of
from origenerator.item_names import ItemNames
from origenerator.media import MediaType
from origenerator.non_ai_videos import (
    Kept,
    NonAiPlaces,
    more_places_here,
    scan,
    take_up_what_the_records_say,
)
from origenerator.output_places import OutputPlaces
from origenerator.thumbnail import animated_thumbnail_path
from origenerator.trash import Trash
from origenerator.workflows import workflow_named
from origenerator.workflows.non_ai import NonAiWorkflow, non_ai_folder, non_ai_workflow
from tests.comfyui_folders import SUITE_FOLDERS
from tests.media_files import write_mp4


def test_a_non_ai_folder_is_a_workflow_named_for_it_that_nothing_generates():
    workflow = workflow_named(non_ai_workflow("Sample Folder"))

    assert (workflow.display_name, workflow.generates_here, workflow.selectable,
            [pd.label for pd in workflow.param_definitions()]) == (
        "Sample Folder", False, False, ["Folder"])
    assert non_ai_folder(workflow.name) == "Sample Folder"
    assert non_ai_folder("wan22_i2v") is None


def test_a_non_ai_folder_shows_its_first_folder_capitalized_and_other_as_other_or_unknown():
    assert [workflow_named(non_ai_workflow(folder)).display_name
            for folder in ("sample full", "other clips", "other", "otherwise full")] == [
        "Sample full", "(other/unknown) clips", "(other/unknown)", "Otherwise full"]


def test_the_overlay_can_give_a_non_ai_folder_another_name_to_show(monkeypatch):
    monkeypatch.setattr(display_names, "load_content", lambda: {"display_names": {
        non_ai_workflow("sample full"): "Sample films"}})

    assert [workflow_named(non_ai_workflow(folder)).display_name
            for folder in ("sample full", "sample clips")] == ["Sample films", "Sample clips"]


def _library(tmp_path) -> NonAiPlaces:
    library = tmp_path / "library"
    return NonAiPlaces(videos=library / "videos" / "non_AI", thumb_dir=tmp_path / "thumbs",
                       records=library / "metadata")


def _record(places: NonAiPlaces, video: Path, record: dict) -> None:
    filed = places.records / video.relative_to(places.videos.parent).with_suffix(".json")
    filed.parent.mkdir(parents=True, exist_ok=True)
    filed.write_text(json.dumps(record), encoding="utf-8")


def _videos(db) -> list[dict]:
    return [row for row in db.list_generations() if row["source"] == GenerationSource.NON_AI]


def test_a_scan_brings_each_non_ai_video_in_once_from_where_it_is_kept(tmp_path):
    db, places = Database(tmp_path / "test.db"), _library(tmp_path)
    kept = write_mp4(places.videos / "sample" / "full" / "video one.mp4")
    write_mp4(places.videos / "sample" / "full" / "video two.partial.mp4")
    write_mp4(places.videos / "sample" / "full" / "video one [conflicted 2].mp4")

    assert (scan(db, places), scan(db, places)) == (1, 0)
    [row] = _videos(db)
    assert json.loads(row["output_files"]) == [{"filename": "video one.mp4",
                                                "library_path": str(kept)}]
    assert workflow_named(row["workflow_name"]).display_name == "Sample full"
    assert resolve_preview(row, OutputPlaces.in_one_folder(tmp_path / "out")) == (
        kept, MediaType.VIDEO)
    assert Path(row["thumbnail_path"]).exists()
    assert animated_thumbnail_path(places.thumb_dir, row["prompt_id"]).exists()


def test_a_video_replaced_by_its_enhanced_copy_keeps_its_item_which_then_names_that_copy(
        tmp_path):
    db, places = Database(tmp_path / "test.db"), _library(tmp_path)
    kept = write_mp4(places.videos / "sample" / "full" / "video one.mp4")
    scan(db, places)
    [before] = _videos(db)
    db.set_generation_favorite(before["prompt_id"], True)
    enhanced = kept.rename(kept.with_name("video one_topaz.mp4"))

    assert scan(db, places) == 0, "the enhanced copy is the same video, never one more item"
    [row] = _videos(db)
    assert (row["prompt_id"], json.loads(row["output_files"])) == (
        before["prompt_id"], [{"filename": enhanced.name, "library_path": str(enhanced)}])


def test_the_records_take_up_at_every_start_follows_an_enhanced_copy_too(tmp_path):
    db, places = Database(tmp_path / "test.db"), _library(tmp_path)
    kept = write_mp4(places.videos / "sample" / "full" / "video one.mp4")
    scan(db, places)
    enhanced = kept.rename(kept.with_name("video one_topaz.mp4"))

    take_up_what_the_records_say(db, places)

    [row] = _videos(db)
    assert json.loads(row["output_files"])[0]["library_path"] == str(enhanced)


def _move_with_its_record(places: NonAiPlaces, video: Path, to: Path) -> Path:
    record = places.records / video.relative_to(places.videos.parent).with_suffix(".json")
    moved_record = places.records / to.relative_to(places.videos.parent).with_suffix(".json")
    to.parent.mkdir(parents=True, exist_ok=True)
    moved_record.parent.mkdir(parents=True, exist_ok=True)
    record.replace(moved_record)
    return video.replace(to)


def test_a_video_moved_to_another_folder_keeps_its_item_which_then_names_it_there(
        db, tmp_path):
    places = _library(tmp_path)
    video = write_mp4(places.videos / "sample" / "full" / "set" / "video one.mp4")
    _record(places, video, {"id": "video-one-id"})
    scan(db, places)
    [before] = _videos(db)
    moved = _move_with_its_record(places, video, places.videos / "sample" / "clips" / "video one.mp4")

    assert scan(db, places) == 0, "the moved video is the same video, never one more item"
    [row] = _videos(db)
    assert (row["prompt_id"], json.loads(row["output_files"])) == (
        before["prompt_id"], [{"filename": moved.name, "library_path": str(moved)}])


def _record_path(places: NonAiPlaces, video: Path) -> Path:
    return places.records / video.relative_to(places.videos.parent).with_suffix(".json")


def test_a_video_scanned_before_its_record_followed_it_is_folded_into_its_item(db, tmp_path):
    places = _library(tmp_path)
    video = write_mp4(places.videos / "sample" / "full" / "set" / "video one.mp4")
    _record(places, video, {"id": "video-one-id"})
    scan(db, places)
    [before] = _videos(db)
    moved = places.videos / "sample" / "clips" / "video one.mp4"
    moved.parent.mkdir(parents=True)
    video.replace(moved)
    scan(db, places)
    _record_path(places, moved).parent.mkdir(parents=True)
    _record_path(places, video).replace(_record_path(places, moved))

    scan(db, places)

    [row] = _videos(db)
    assert (row["prompt_id"], json.loads(row["output_files"])) == (
        before["prompt_id"], [{"filename": moved.name, "library_path": str(moved)}])


def test_actions_set_on_the_new_item_of_a_moved_video_stay_on_its_item(db, tmp_path):
    places = _library(tmp_path)
    video = write_mp4(places.videos / "sample" / "full" / "set" / "video one.mp4")
    _record(places, video, {"id": "video-one-id"})
    scan(db, places)
    moved = places.videos / "sample" / "clips" / "video one.mp4"
    moved.parent.mkdir(parents=True)
    video.replace(moved)
    scan(db, places)
    [new] = [row for row in _videos(db) if "clips" in row["output_files"]]
    db.set_actions(new["prompt_id"], MediaType.VIDEO, ItemActions(("alpha",)))
    _record_path(places, moved).parent.mkdir(parents=True)
    _record_path(places, video).replace(_record_path(places, moved))

    scan(db, places)

    [row] = _videos(db)
    assert (actions_of(row, MediaType.VIDEO), json.loads(row["combined_labels"])) == (
        ItemActions(("alpha",)), ["alpha"])


def test_a_moved_video_shows_under_the_folder_it_was_moved_to(db, tmp_path):
    places = _library(tmp_path)
    video = write_mp4(places.videos / "sample" / "full" / "set" / "video one.mp4")
    _record(places, video, {"id": "video-one-id"})
    scan(db, places)
    _move_with_its_record(places, video, places.videos / "sample" / "clips" / "video one.mp4")

    scan(db, places)

    [row] = _videos(db)
    assert (workflow_named(row["workflow_name"]).display_name,
            json.loads(row["params_json"])["folder"]) == ("Sample clips", "sample/clips")


def test_a_moved_full_video_keeps_its_star_and_the_clips_cut_from_it(db, tmp_path):
    places = _library(tmp_path)
    full = write_mp4(places.videos / "sample" / "full" / "set" / "video one.mp4")
    clip = write_mp4(places.videos / "sample" / "clips" / "first.mp4")
    _record(places, full, {"id": "video-one-id", "favorite": True})
    _record(places, clip, {"clip": {"full_video_id": "video-one-id"}})
    scan(db, places)
    _move_with_its_record(places, full, places.videos / "sample" / "full" / "kept" / "video one.mp4")

    scan(db, places)

    rows = {json.loads(row["output_files"])[0]["filename"]: row for row in _videos(db)}
    assert (rows["video one.mp4"]["starred"], rows["first.mp4"]["trimmed_from"]) == (
        1, rows["video one.mp4"]["prompt_id"])


def test_a_non_ai_video_is_named_as_fun_time_names_it(db, tmp_path):
    places = _library(tmp_path)
    named = write_mp4(places.videos / "sample" / "full" / "set" / "video one.mp4")
    unnamed = write_mp4(places.videos / "sample" / "full" / "set" / "video two.mp4")
    _record(places, named, {"title": "Jane Doe - Alpha Study"})
    scan(db, places)
    names = ItemNames(db)

    names.take(db.list_generations(), [], {})

    assert {json.loads(row["output_files"])[0]["filename"]: names.of(row["prompt_id"])
            for row in _videos(db)} == {"video one.mp4": "Jane Doe - Alpha Study",
                                        "video two.mp4": "video two"}
    assert unnamed.exists()


def test_a_scan_takes_up_the_name_a_held_video_has_been_given_since(db, tmp_path):
    places = _library(tmp_path)
    video = write_mp4(places.videos / "sample" / "full" / "set" / "video one.mp4")
    scan(db, places)
    _record(places, video, {"title": "Jane Doe - Alpha Study"})

    assert scan(db, places) == 0

    [row] = _videos(db)
    assert recorded_title(row) == "Jane Doe - Alpha Study"
    assert json.loads(row["params_json"])["folder"] == "sample/full/set"


def test_a_non_ai_videos_star_is_the_favorite_fun_time_keeps_in_its_record(db, tmp_path):
    places = _library(tmp_path)
    video = write_mp4(places.videos / "sample" / "full" / "set" / "video one.mp4")
    _record(places, video, {"favorite": True})
    scan(db, places)
    starred_when_brought_in = _videos(db)[0]["starred"]

    _record(places, video, {})
    scan(db, places)

    assert (starred_when_brought_in, _videos(db)[0]["starred"]) == (1, 0)


def test_starring_a_non_ai_video_here_changes_the_favorite_fun_time_keeps(db, tmp_path):
    places = _library(tmp_path)
    video = write_mp4(places.videos / "sample" / "full" / "set" / "video one.mp4")
    scan(db, places)
    edits = GalleryEdits(db, OutputPlaces.in_one_folder(tmp_path / "out"), Trash(tmp_path / "trash"),
                         environment=GalleryEnvironment(video_records=places.records))
    [prompt_id] = [row["prompt_id"] for row in _videos(db)]

    def kept() -> bool:
        return favorites.is_favorite(filed_record(video, places.records))

    edits.tell_fun_time_of_favorites([prompt_id], True)
    starred = kept()
    edits.tell_fun_time_of_favorites([prompt_id], False)

    assert (starred, kept()) == (True, False)


def test_a_clip_is_linked_to_the_full_video_its_record_says_it_was_cut_from(db, tmp_path):
    places = _library(tmp_path)
    full = write_mp4(places.videos / "sample" / "full" / "set" / "video one.mp4")
    clip = write_mp4(places.videos / "sample" / "clips" / "video one" / "first.mp4")
    _record(places, full, {"id": "the-full-videos-id"})
    _record(places, clip, {"clip": {"full_video_id": "the-full-videos-id"}})

    scan(db, places)

    rows = {json.loads(row["output_files"])[0]["filename"]: row for row in _videos(db)}
    assert (rows["first.mp4"]["trimmed_from"], rows["video one.mp4"]["trimmed_from"]) == (
        rows["video one.mp4"]["prompt_id"], None)


def test_the_videos_one_folders_records_group_together_are_alternate_versions(db, tmp_path):
    places = _library(tmp_path)
    for name, record in (("video one.mp4", {"version": {"group": "video one"}}),
                         ("video one remaster.mp4", {"version": {"group": "video one"}}),
                         ("video two.mp4", {"version": {"group": "video two"}}),
                         ("video three.mp4", {})):
        _record(places, write_mp4(places.videos / "sample" / "full" / "set" / name), record)
    _record(places, write_mp4(places.videos / "sample" / "clips" / "video one.mp4"),
            {"version": {"group": "video one"}})

    scan(db, places)

    rows = _videos(db)
    named = {json.loads(row["output_files"])[0]["library_path"]: row for row in rows}
    full = {Path(path).name: row for path, row in named.items() if "full" in Path(path).parts}
    assert {name: [json.loads(other["output_files"])[0]["filename"]
                   for other in alternate_versions(row, rows)]
            for name, row in full.items()} == {
        "video one.mp4": ["video one remaster.mp4"],
        "video one remaster.mp4": ["video one.mp4"],
        "video two.mp4": [], "video three.mp4": []}


def _leaves(db) -> list[list[str]]:
    rows = db.list_generations()

    def walk(group):
        if not child_groups(group):
            return [sorted(json.loads(row["output_files"])[0]["filename"] for row in group.rows)]
        return [leaf for child in child_groups(group) for leaf in walk(child)]

    return sorted(leaf for media in build_gallery_tree(rows) for leaf in walk(media))


def test_the_videos_of_one_folder_on_disk_share_a_folder_in_the_toc(tmp_path):
    db, places = Database(tmp_path / "test.db"), _library(tmp_path)
    for name in ("sample/clips/video one/first.mp4", "sample/clips/video one/second.mp4",
                 "sample/clips/video two/first.mp4", "sample/full/video one.mp4"):
        write_mp4(places.videos / name)

    scan(db, places)

    assert _leaves(db) == [["first.mp4"], ["first.mp4", "second.mp4"], ["video one.mp4"]]
    assert all(not made_here(row) for row in _videos(db))


def test_a_non_ai_leaf_folder_is_named_for_its_folder_on_disk(db, tmp_path):
    places = _library(tmp_path)
    for name in ("sample/full/set one/first.mp4", "sample/full/set two/extra/first.mp4",
                 "sample/clips/first.mp4"):
        write_mp4(places.videos / name)
    scan(db, places)

    [videos] = build_gallery_tree(db.list_generations())

    assert {folder.label: sorted(leaf.label for leaf in child_groups(folder))
            for folder in child_groups(videos)} == {
        "Sample clips": ["clips"], "Sample full": ["set one", "set two/extra"]}


def test_a_non_ai_folder_holds_its_leaf_folders_with_no_model_or_lora_between(tmp_path):
    db, places = Database(tmp_path / "test.db"), _library(tmp_path)
    write_mp4(places.videos / "sample" / "full" / "video one.mp4")
    scan(db, places)
    [row] = _videos(db)

    [videos] = build_gallery_tree(db.list_generations())
    [folder] = child_groups(videos)
    [leaf] = child_groups(folder)

    assert (folder.label, type(leaf)) == ("Sample full", SettingsGroup)
    assert folder_chain(row) == (ALL_KEY, videos.key, folder.key, leaf.key)


def test_a_non_ai_videos_tab_says_it_has_no_settings_and_cannot_generate(qtbot, tmp_path):
    db, places = Database(tmp_path / "test.db"), _library(tmp_path)
    write_mp4(places.videos / "sample" / "full" / "video one.mp4")
    scan(db, places)
    tab = GenerateTab(ComfyUIClient(folders=SUITE_FOLDERS), db)
    qtbot.addWidget(tab)
    tab._viewport.show_media = MagicMock()

    tab.show_saved_generation(_videos(db)[0], [])

    assert (tab._form_host.isHidden(), tab._no_settings_note.isHidden(),
            tab._no_settings_note.text()) == (
        True, False, "This video wasn't generated, so it has no generation settings.")
    assert not tab._generate_pair.isEnabled()
    assert tab._generate_btn.toolTip() == NonAiWorkflow.why_it_cannot_be_made_again


def test_the_line_saying_there_are_no_settings_sits_in_the_middle_of_the_empty_top_section(
        qtbot, tmp_path):
    db, places = Database(tmp_path / "test.db"), _library(tmp_path)
    write_mp4(places.videos / "sample" / "full" / "video one.mp4")
    scan(db, places)
    tab = GenerateTab(ComfyUIClient(folders=SUITE_FOLDERS), db)
    qtbot.addWidget(tab)
    tab._viewport.show_media = MagicMock()
    tab.resize(700, 1000)
    tab.show()

    tab.show_saved_generation(_videos(db)[0], [])
    QApplication.processEvents()

    section, note = tab._settings_scroll.viewport(), tab._no_settings_note
    middle = note.mapTo(section, note.rect().center()) - section.rect().center()
    assert note.alignment() == Qt.AlignmentFlag.AlignCenter
    assert section.height() > 4 * note.fontMetrics().height()
    assert max(abs(middle.x()), abs(middle.y())) <= MARGIN_STANDARD


def _library_with_more(tmp_path) -> tuple[NonAiPlaces, Path, Path]:
    places = _library(tmp_path)
    library = places.videos.parent
    other_drive = tmp_path / "another drive" / "videos"
    return (NonAiPlaces(
        videos=places.videos, thumb_dir=places.thumb_dir, records=places.records,
        more=(Kept(other_drive / "VR" / "finished", named_from=other_drive),
              Kept(library / "sample app" / "flicks" / "2D" / "non_AI", named_from=library),
              Kept(library / "sample app" / "flicks" / "VR", named_from=library))),
        library, other_drive)


def test_a_scan_brings_in_the_videos_of_every_place_each_under_its_own_folders(db, tmp_path):
    places, library, other_drive = _library_with_more(tmp_path)
    for video in (places.videos / "sample" / "full" / "video one.mp4",
                  other_drive / "VR" / "finished" / "video two.mp4",
                  library / "sample app" / "flicks" / "2D" / "non_AI" / "video three.mp4",
                  library / "sample app" / "flicks" / "VR" / "video four.mp4"):
        write_mp4(video)

    assert (scan(db, places), scan(db, places)) == (4, 0)

    [videos] = build_gallery_tree(db.list_generations())
    assert {folder.label: sorted(leaf.label for leaf in child_groups(folder))
            for folder in child_groups(videos)} == {
        "Sample full": ["full"], "VR finished": ["finished"],
        "Sample app flicks": ["2D/non_AI", "VR"]}


def test_a_video_kept_on_another_drive_takes_its_name_and_star_from_its_record(db, tmp_path):
    places, _library_folder, other_drive = _library_with_more(tmp_path)
    video = write_mp4(other_drive / "VR" / "finished" / "video two.mp4")
    record = places.records / "VR" / "finished" / "video two.json"
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({"title": "Jane Doe - Beta Study", "favorite": True}),
                      encoding="utf-8")

    scan(db, places)

    [row] = _videos(db)
    assert (recorded_title(row), row["starred"], json.loads(row["output_files"])) == (
        "Jane Doe - Beta Study", 1, [{"filename": "video two.mp4", "library_path": str(video)}])


def test_a_place_that_is_not_there_brings_nothing_in_and_stops_no_other(db, tmp_path):
    places, _library_folder, _other_drive = _library_with_more(tmp_path)
    write_mp4(places.videos / "sample" / "full" / "video one.mp4")

    assert scan(db, places) == 1


def test_the_places_beyond_the_non_ai_folder_are_the_vr_folder_and_genaus_flicks_no_model_made(
        tmp_path, monkeypatch):
    drive, genau = tmp_path / "another drive" / "videos", tmp_path / "videos" / "sample app"
    flicks = (genau / "flicks" / "2D" / "non_AI", genau / "flicks" / "VR")
    monkeypatch.setattr(config, "GENAU_DIR", genau)
    monkeypatch.setattr(config, "GENAU_FLICKS_NO_MODEL_MADE", flicks)
    monkeypatch.setattr(config, "VR_DIR", drive / "VR" / "finished")
    with_vr = more_places_here()
    monkeypatch.setattr(config, "VR_DIR", None)

    assert (with_vr, more_places_here()) == (
        (Kept(drive / "VR" / "finished", named_from=drive),
         *(Kept(folder, named_from=tmp_path / "videos") for folder in flicks)),
        tuple(Kept(folder, named_from=tmp_path / "videos") for folder in flicks))
