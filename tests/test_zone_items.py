"""What a drop zone holds, as the gallery reads it. Fixture values are fabricated."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from origenerator.db import Database
from origenerator.gui.zone_items import FilesOnly, ZoneItems
from origenerator.item_names import ItemNames
from origenerator.library_views import LibraryViews
from origenerator.media import MediaType
from origenerator.output_places import OutputPlaces
from tests.media_files import write_mp4
from tests.pictured_rows import square


@pytest.fixture
def library(tmp_path):
    output_dir = tmp_path / "output"
    (output_dir / "image").mkdir(parents=True)
    (output_dir / "video").mkdir(parents=True)
    square(output_dir / "image", "red")
    Path(output_dir / "image" / "made-red.png").rename(output_dir / "image" / "pic_00001_.png")
    write_mp4(output_dir / "video" / "run_00002_.mp4")
    thumb = square(tmp_path, "blue")
    db = Database(tmp_path / "t.db")
    _row(db, "gen-pic", "sdxl_t2i", "image/pic_00001_.png", thumb)
    _row(db, "gen-run", "wan22_i2v", "video/run_00002_.mp4", thumb)
    names = ItemNames.from_library(db)
    items = ZoneItems(
        db, names, LibraryViews(db),
        places=OutputPlaces.in_one_folder(output_dir), input_dir=tmp_path / "input",
        thumb_dir=tmp_path / "thumbs", moving_preview=lambda row: None)
    return items, names, output_dir, thumb


def _row(db, prompt_id, workflow, file, thumb):
    db.insert_generation(prompt_id=prompt_id, workflow_name=workflow, workflow_version="v1",
                         params_json="{}", workflow_json="{}")
    subfolder, name = file.split("/")
    db.update_generation(prompt_id, status="completed", thumbnail_path=thumb,
                         output_files=json.dumps([{"filename": name, "subfolder": subfolder,
                                                   "type": "output"}]))


def test_a_dragged_picture_lends_a_picture_zone_its_file_reference(library):
    items, _names, _output_dir, _thumb = library

    assert items.lends("gen-pic", MediaType.IMAGE) == "image/pic_00001_.png [output]"
    assert items.lends("gen-pic", MediaType.VIDEO) is None


def test_a_dragged_video_lends_a_video_zone_its_own_path(library):
    items, _names, output_dir, _thumb = library

    assert items.lends("gen-run", MediaType.VIDEO) == str(output_dir / "video" / "run_00002_.mp4")
    assert items.lends("gen-run", MediaType.IMAGE) is None


def test_a_held_item_is_known_by_its_file_and_shows_its_own_pictures(library):
    items, names, output_dir, thumb = library

    assert items.item_of("image/pic_00001_.png [output]") == "gen-pic"
    assert items.name_of("image/pic_00001_.png [output]") == names.of("gen-pic")
    assert items.preview("image/pic_00001_.png [output]") == (thumb, None)
    assert items.item_of(str(output_dir / "video" / "run_00002_.mp4")) == "gen-run"


def test_a_file_from_outside_is_named_by_its_file_and_shown_as_itself(library, tmp_path):
    items, _names, _output_dir, _thumb = library
    picture = square(tmp_path, "green")

    assert items.item_of(picture) is None
    assert items.name_of(picture) == "made-green.png"
    assert items.preview(picture) == (picture, None)


def test_a_video_from_outside_shows_a_still_made_from_it(library, tmp_path):
    items, _names, _output_dir, _thumb = library
    video = str(write_mp4(tmp_path / "scene one.mp4"))

    still, movie = items.preview(video)

    assert movie is None
    assert Path(still).parent == tmp_path / "thumbs" and Path(still).is_file()
    assert items.name_of(video) == "scene one.mp4"


def test_a_pasted_name_means_the_item_wearing_it(library):
    items, names, _output_dir, _thumb = library

    assert items.named(names.of("gen-run")) == "gen-run"
    assert items.named("no such name") is None


def test_with_no_gallery_a_zone_holds_files_alone(tmp_path):
    items = FilesOnly(places=OutputPlaces.in_one_folder(tmp_path / "output"),
                      input_dir=tmp_path / "input")
    picture = square(tmp_path, "red")

    assert items.lends("gen-pic", MediaType.IMAGE) is None
    assert items.named("anything") is None
    assert items.preview(picture) == (picture, None)
    assert items.name_of(picture) == "made-red.png"
    assert items.preview("nowhere.png") == (None, None)
