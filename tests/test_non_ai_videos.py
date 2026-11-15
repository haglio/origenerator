from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from app_support.gallery_rows import made_here

from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gallery import (
    SettingsGroup,
    build_gallery_tree,
    child_groups,
    resolve_preview,
)
from origenerator.gallery.tree import ALL_KEY, folder_chain
from origenerator.generation_state import GenerationSource
from origenerator.gui.generate_tab import GenerateTab
from origenerator.media import MediaType
from origenerator.non_ai_videos import NonAiPlaces, scan
from origenerator.output_places import OutputPlaces
from origenerator.thumbnail import animated_thumbnail_path
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
    return NonAiPlaces(videos=tmp_path / "library" / "non_AI", thumb_dir=tmp_path / "thumbs")


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


def test_a_non_ai_videos_tab_shows_its_folder_and_cannot_generate(qtbot, tmp_path):
    db, places = Database(tmp_path / "test.db"), _library(tmp_path)
    write_mp4(places.videos / "sample" / "full" / "video one.mp4")
    scan(db, places)
    tab = GenerateTab(ComfyUIClient(folders=SUITE_FOLDERS), db)
    qtbot.addWidget(tab)
    tab._viewport.show_media = MagicMock()

    tab.show_saved_generation(_videos(db)[0], [])

    assert tab._workflow_dropdown.currentText() == "sample full"
    assert tab._param_form.get_values() == {"folder": "sample/full"}
    assert not tab._generate_pair.isEnabled()
    assert tab._generate_btn.toolTip() == NonAiWorkflow.why_it_cannot_be_made_again
