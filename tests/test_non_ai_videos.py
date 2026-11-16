from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from app_support import favorites
from app_support.gallery_rows import made_here
from app_support.mirrored_tree import filed_record

from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gallery import (
    SettingsGroup,
    build_gallery_tree,
    child_groups,
    resolve_preview,
)
from origenerator.gallery.non_ai import recorded_title
from origenerator.gallery.tree import ALL_KEY, folder_chain
from origenerator.gallery_edits import GalleryEdits, GalleryEnvironment
from origenerator.generation_state import GenerationSource
from origenerator.gui.generate_tab import GenerateTab
from origenerator.item_names import ItemNames
from origenerator.media import MediaType
from origenerator.non_ai_videos import NonAiPlaces, scan
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

    assert (scan(db, places), scan(db, places)) == (1, 0)
    [row] = _videos(db)
    assert json.loads(row["output_files"]) == [{"filename": "video one.mp4",
                                                "library_path": str(kept)}]
    assert workflow_named(row["workflow_name"]).display_name == "sample full"
    assert resolve_preview(row, OutputPlaces.in_one_folder(tmp_path / "out")) == (
        kept, MediaType.VIDEO)
    assert Path(row["thumbnail_path"]).exists()
    assert animated_thumbnail_path(places.thumb_dir, row["prompt_id"]).exists()


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
        "sample clips": ["clips"], "sample full": ["set one", "set two/extra"]}


def test_a_non_ai_folder_holds_its_leaf_folders_with_no_model_or_lora_between(tmp_path):
    db, places = Database(tmp_path / "test.db"), _library(tmp_path)
    write_mp4(places.videos / "sample" / "full" / "video one.mp4")
    scan(db, places)
    [row] = _videos(db)

    [videos] = build_gallery_tree(db.list_generations())
    [folder] = child_groups(videos)
    [leaf] = child_groups(folder)

    assert (folder.label, type(leaf)) == ("sample full", SettingsGroup)
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
