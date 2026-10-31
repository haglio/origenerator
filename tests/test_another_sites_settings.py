"""A video another site made, and the image it was made from, show their own
settings on a Generate tab the way anything made here does.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from PIL import Image

from origenerator import outside_videos
from origenerator.act_settings import CATEGORIES
from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gui.generate_pane import parse_tabs_state
from origenerator.gui.generate_tab import GenerateTab
from origenerator.gui.param_sections import OTHER_TITLE, section_title
from origenerator.media import MediaType
from origenerator.outside_videos import Made, OutsideVideo, Record, rows_bringing_in
from origenerator.workflows import WORKFLOW_REGISTRY, workflow_named
from origenerator.workflows.outside import VideoKind, outside_workflow
from tests.comfyui_folders import SUITE_FOLDERS

_VIDEO = {"positive_prompt": "a slow walk on the shore", "seed": "11", "model": "Video Model",
          "style": "Video Style", "resolution": "720p", "aspect_ratio": "9:16",
          "quality": "High", "creativity": "Low"}
_IMAGE = {"positive_prompt": "a quiet shore", "negative_prompt": "rain", "seed": "22",
            "model": "Image Model", "style": "Image Style", "resolution": "1024",
            "aspect_ratio": "9:16", "quality": "Medium", "creativity": "High"}


def _brought_in(db, tmp_path, name: str, record: Record,
                kind: VideoKind | None = None) -> list[dict]:
    file = tmp_path / "outbox" / "portrait" / "a-site" / name
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(b"not really a video")
    made = rows_bringing_in(OutsideVideo(file, "a-site"), record,
                            frames_dir=tmp_path / "frames", thumb_dir=tmp_path / "thumbs",
                            grab=lambda _path: Image.new("RGB", (64, 96)), kind=kind)
    db.insert_rows(made)
    return [db.get_generation(row["prompt_id"]) for row in made]


@pytest.fixture
def library(qtbot, tmp_path):
    db = Database(tmp_path / "t.db")
    image, video = _brought_in(db, tmp_path, "c1_topaz.mp4", Record(
        video=Made(_VIDEO), image=Made(_IMAGE), act="Wave"))
    tab =GenerateTab(ComfyUIClient(folders=SUITE_FOLDERS), db)
    qtbot.addWidget(tab)
    tab._preview.show_media = MagicMock()
    return tab, db, video, image


def _shown(tab, keys) -> dict:
    values = tab._param_form.get_values()
    return {key: values[key] for key in keys}


def test_an_ai_video_shows_its_own_settings_under_its_site(library):
    tab, _db, video, image = library

    tab.show_saved_generation(video, [image])

    assert tab._workflow_dropdown.currentText() == "a-site"
    assert _shown(tab, ("positive_prompt", "model", "style", "resolution", "aspect_ratio",
                          "quality", "creativity")) == {key: value for key, value in _VIDEO.items()
                                                        if key != "seed"}
    assert tab._param_form.get_values()["seed"] == 11


def test_an_ai_video_from_a_site_of_both_kinds_shows_its_settings_under_its_site_and_kind(
        qtbot, tmp_path):
    db = Database(tmp_path / "t.db")
    image, video = _brought_in(db, tmp_path, "c1_topaz.mp4", Record(
        video=Made(_VIDEO), image=Made(_IMAGE), act="Wave"),
        kind=VideoKind.IMAGE_TO_VIDEO)
    tab = GenerateTab(ComfyUIClient(folders=SUITE_FOLDERS), db)
    qtbot.addWidget(tab)
    tab._preview.show_media = MagicMock()

    tab.show_saved_generation(video, [image])

    assert tab._workflow_dropdown.currentText() == "a-site I2V"


def test_the_image_an_ai_video_was_made_from_shows_its_own_settings(library):
    tab, _db, _video, image = library

    tab.show_saved_generation(image, [image])

    assert tab._workflow_dropdown.currentText() == "a-site"
    assert _shown(tab, ("positive_prompt", "negative_prompt", "model", "style")) == {
        "positive_prompt": "a quiet shore", "negative_prompt": "rain",
        "model": "Image Model", "style": "Image Style"}
    assert tab._param_form.get_values()["seed"] == 22


def test_an_ai_video_shows_its_sites_video_fields_and_its_image_its_image_fields(library):
    tab, _db, video, image = library

    tab.show_saved_generation(video, [image])
    video_fields = set(tab._param_form._widgets)
    tab.show_saved_generation(image, [image])
    image_fields = set(tab._param_form._widgets)

    assert (video_fields, image_fields - video_fields) == (
        {"positive_prompt", "seed", "model", "style", "creativity", "resolution",
         "aspect_ratio", "quality"}, {"negative_prompt"})


def test_a_setting_an_ai_videos_record_lacks_shows_empty_rather_than_the_last_items(
        library, tmp_path):
    tab, db, video, image = library
    _frame, bare = _brought_in(db, tmp_path, "c2_topaz.mp4", Record(video=Made({"seed": "33"})))
    tab.show_saved_generation(video, [image])

    tab.show_saved_generation(bare, [])

    unrecorded = ("positive_prompt", "model", "style", "resolution", "aspect_ratio", "quality",
                  "creativity")
    assert _shown(tab, unrecorded) == dict.fromkeys(unrecorded, "")


def test_a_seed_the_site_did_not_record_reads_as_a_dash_and_one_it_recorded_as_0_as_0(
        library, tmp_path):
    tab, db, _video, _image = library
    _frame, unseeded = _brought_in(db, tmp_path, "c2_topaz.mp4",
                                   Record(video=Made({"positive_prompt": "a slow turn"})))
    _frame, zero = _brought_in(db, tmp_path, "c3_topaz.mp4", Record(video=Made({"seed": "0"})))

    tab.show_saved_generation(unseeded, [])
    unrecorded = tab._param_form._widgets["seed"].currentText()
    tab.show_saved_generation(zero, [])

    assert (unrecorded, tab._param_form._widgets["seed"].currentText()) == ("—", "0")


def test_an_ai_video_after_an_image_made_here_shows_none_of_that_images_prompts(
        library, tmp_path):
    tab, db, _video, _image = library
    _frame, bare = _brought_in(db, tmp_path, "c2_topaz.mp4", Record(video=Made({"seed": "33"})))
    params = dict(WORKFLOW_REGISTRY["sdxl_t2i"].default_params(),
                  positive_prompt="a red door", negative_prompt="fog", seed=1)
    db.insert_generation(prompt_id="made-here", workflow_name="sdxl_t2i", workflow_version="v002",
                         positive_prompt="a red door", seed=1, params_json=json.dumps(params),
                         workflow_json="{}")
    db.update_generation("made-here", status="completed",
                         output_files=json.dumps([{"filename": "door.png", "subfolder": "image"}]))
    made_here = db.get_generation("made-here")
    tab.show_saved_generation(made_here, [made_here])

    tab.show_saved_generation(bare, [])

    assert _shown(tab, ("positive_prompt",)) == {"positive_prompt": ""}
    assert "negative_prompt" not in tab._param_form.get_values()


def test_an_ai_videos_settings_can_be_edited_and_an_edit_counts_as_one(library, qtbot):
    tab, _db, video, image = library
    tab.show_saved_generation(video, [image])
    edits = []
    tab.user_edited.connect(lambda: edits.append(True))

    tab._param_form.set_values({"positive_prompt": "a fast walk on the shore"})

    assert tab._param_form.get_values()["positive_prompt"] == "a fast walk on the shore"
    assert edits


@pytest.mark.parametrize("shown", ["video", "image"])
def test_generate_is_grayed_on_an_ai_item_and_says_why(library, qtbot, shown):
    tab, _db, video, image = library

    tab.show_saved_generation({"video": video, "image": image}[shown], [image])
    qtbot.waitUntil(lambda: not tab._caption_timer.isActive())

    assert not tab._generate_pair.isEnabled()
    assert tab._generate_btn.toolTip() == "Another site made this — Origenerator can't remake it"


def test_picking_an_act_on_an_ai_videos_tab_goes_where_its_star_goes(library, monkeypatch):
    tab, _db, video, image = library
    places, picks = object(), []
    monkeypatch.setattr(outside_videos, "places_here", lambda: places)
    monkeypatch.setattr(outside_videos, "pick_act",
                        lambda db, where, row, act: picks.append((where, row["prompt_id"], act)))
    tab.show_saved_generation(video, [image])

    tab._action.pick(CATEGORIES[1])

    assert picks == [(places, video["prompt_id"], CATEGORIES[1])]


@pytest.mark.parametrize("made", [MediaType.VIDEO, MediaType.IMAGE])
def test_every_setting_another_site_records_sits_in_a_section_of_the_form(made):
    workflow = workflow_named(outside_workflow("a-site", made))

    assert [pd.key for pd in workflow.param_definitions()
            if section_title(pd.key) == OTHER_TITLE] == []


def test_a_tab_left_on_an_ai_video_comes_back_after_a_restart(library):
    tab, _db, video, image = library
    tab.show_saved_generation(video, [image])
    state = {"tabs": [{"config": json.loads(json.dumps(tab.current_config().to_dict()))}],
             "current": 0}

    [tab], _current = parse_tabs_state(state)

    assert tab.config.workflow_name == outside_workflow("a-site")
