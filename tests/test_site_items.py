from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from urllib.parse import unquote

import pytest
from app_support import haglio_settings
from PIL import Image

from origenerator import site_items, sites
from origenerator.db import Database
from origenerator.gallery.output import is_in_progress, output_file_path, parse_file_list
from origenerator.generation_state import GenerationSource, GenerationStatus
from origenerator.media import MediaType
from origenerator.output_places import OutputFolders, OutputPlaces
from origenerator.site_generation import Made
from origenerator.workflows.outside import outside_workflow

A_SITES_IMAGES = outside_workflow("madeup", MediaType.IMAGE)
ASKED = {"positive_prompt": "a red apple", "negative_prompt": "blurry", "model": "Made Up",
         "quality": "Base"}
WHEN_ASKED = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
WHEN_MADE = datetime(2026, 3, 1, 12, 1, tzinfo=UTC)


def _webp() -> bytes:
    held = io.BytesIO()
    Image.new("RGB", (90, 120), (200, 30, 30)).save(held, "WEBP")
    return held.getvalue()


@pytest.fixture
def library(tmp_path):
    folders = OutputFolders(OutputPlaces.in_one_folder(tmp_path / "out"), tmp_path / "thumbs")
    return Database(tmp_path / "test.db"), folders


def test_an_image_asked_of_a_site_is_in_flight_as_that_sites_image(library):
    db, _folders = library

    prompt_id = site_items.begin(db, A_SITES_IMAGES, ASKED, now=WHEN_ASKED)

    row = db.get_generation(prompt_id)
    assert is_in_progress(row)
    assert row["status"] == GenerationStatus.RUNNING
    assert (row["source"], row["workflow_name"]) == (GenerationSource.OUTSIDE, A_SITES_IMAGES)
    assert json.loads(row["params_json"]) == ASKED
    assert row["created_at"] == "2026-03-01 12:00:00"
    assert row["completed_at"] is None


def test_what_the_site_made_is_filed_with_the_images_under_the_seed_the_site_used(library):
    db, folders = library
    prompt_id = site_items.begin(db, A_SITES_IMAGES, ASKED, now=WHEN_ASKED)

    took = site_items.take_in(db, prompt_id, Made("https://example.com/made/a.webp", seed="4242"),
                              _webp(), folders, now=WHEN_MADE)

    row = db.get_generation(prompt_id)
    assert took
    assert row["status"] == GenerationStatus.COMPLETED
    assert (row["seed"], json.loads(row["params_json"])["seed"]) == (4242, "4242")
    assert row["created_at"] == "2026-03-01 12:00:00"
    (filed,) = parse_file_list(row["output_files"])
    kept = output_file_path(filed, folders.places)
    assert kept.parent == folders.places.images
    assert kept.name == "madeup_image_00001_.webp"
    assert kept.read_bytes() == _webp()
    assert Image.open(row["thumbnail_path"]).size[0] > 0
    assert not folders.places.run(prompt_id).exists()


def test_a_second_image_from_the_site_takes_the_next_number(library):
    db, folders = library
    names = []
    for _each in range(2):
        prompt_id = site_items.begin(db, A_SITES_IMAGES, ASKED)
        site_items.take_in(db, prompt_id, Made("https://example.com/a.webp"), _webp(), folders)
        names.append(parse_file_list(db.get_generation(prompt_id)["output_files"])[0]["filename"])

    assert names == ["madeup_image_00001_.webp", "madeup_image_00002_.webp"]


def test_an_address_that_names_no_kind_of_image_is_kept_as_the_kind_the_site_sends(library):
    db, folders = library
    prompt_id = site_items.begin(db, A_SITES_IMAGES, ASKED)

    site_items.take_in(db, prompt_id, Made("https://example.com/made/a"), _webp(), folders)

    assert parse_file_list(db.get_generation(prompt_id)["output_files"])[0]["filename"].endswith(
        ".webp")


def test_an_image_whose_item_was_deleted_meanwhile_is_not_filed(library):
    db, folders = library
    prompt_id = site_items.begin(db, A_SITES_IMAGES, ASKED)
    db.delete_generation(prompt_id)

    assert not site_items.take_in(db, prompt_id, Made("https://example.com/a.webp"), _webp(),
                                  folders)
    assert not folders.places.images.exists()


def test_an_image_the_site_refused_is_marked_failed_with_the_reason(library):
    db, _folders = library
    prompt_id = site_items.begin(db, A_SITES_IMAGES, ASKED)

    site_items.give_up(db, prompt_id, "made-up reason")

    row = db.get_generation(prompt_id)
    assert (row["status"], row["error_message"]) == (GenerationStatus.ERROR, "made-up reason")


def test_giving_up_on_an_item_already_deleted_does_nothing(library):
    db, _folders = library

    site_items.give_up(db, "no-such-item", "made-up reason")

    assert db.get_generation("no-such-item") is None


def _settings_naming(monkeypatch, tmp_path, pages: dict):
    written = tmp_path / "haglio_settings.json"
    written.write_text(json.dumps({**haglio_settings.example_inside(tmp_path),
                                   sites.SETTING: pages}), encoding="utf-8")
    monkeypatch.setenv(haglio_settings.SETTINGS_ENV, str(written))


def test_a_site_makes_images_when_the_shared_settings_name_its_image_page(monkeypatch, tmp_path):
    _settings_naming(monkeypatch, tmp_path, {"madeup": {"image": "https://example.com/create"},
                                             "videos-only": {"video": "https://example.com/v"}})

    assert sites.makes_images("madeup")
    assert not sites.makes_images("videos-only")
    assert not sites.makes_images("another")


def test_no_site_makes_images_where_the_shared_settings_name_no_pages():
    assert not sites.makes_images("madeup")


def test_the_address_asks_the_sites_image_page_for_the_forms_settings_and_to_submit(
        monkeypatch, tmp_path):
    _settings_naming(monkeypatch, tmp_path, {"madeup": {"image": "https://example.com/create"}})

    address = sites.address_asking_for_an_image("madeup", {**ASKED, "seed": 77})

    page, packed = address.split("#ft=", 1)
    asked = json.loads(unquote(packed))
    assert page == "https://example.com/create"
    assert (asked["kind"], asked["positive"], asked["negative"]) == ("image", "a red apple",
                                                                     "blurry")
    assert ["Seed", "77"] in asked["settings"]
    assert ["Quality", "Base"] in asked["settings"]
    assert asked["submit"] is True
