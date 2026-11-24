from __future__ import annotations

import json
from functools import partial

import pytest
from app_support import haglio_settings

from origenerator import sites
from origenerator.db import Database
from origenerator.generation_state import GenerationSource, GenerationStatus
from origenerator.gui import gallery_view
from origenerator.gui.gallery_view import GalleryView
from origenerator.gui.site_generations import SiteGenerations
from origenerator.media import MediaType
from origenerator.site_generation import Made
from origenerator.workflows.outside import outside_workflow
from tests.gallery_view_support import _reroll_client
from tests.test_site_generations import FakeSite, Later
from tests.test_site_items import _webp

ITS_IMAGES = outside_workflow("madeup", MediaType.IMAGE)
ASKED = {"positive_prompt": "a red apple", "model": "Made Up", "seed": 5}


@pytest.fixture
def gallery(qtbot, monkeypatch, tmp_path):
    written = tmp_path / "haglio_settings.json"
    written.write_text(json.dumps({**haglio_settings.example_inside(tmp_path), sites.SETTING: {
        "madeup": {"image": "https://example.com/create"}}}), encoding="utf-8")
    monkeypatch.setenv(haglio_settings.SETTINGS_ENV, str(written))
    site, later = FakeSite(Made("https://example.com/a.webp", seed="5"),
                           Made("https://example.com/b.webp", seed="6")), Later()
    monkeypatch.setattr(gallery_view, "SiteGenerations", partial(
        SiteGenerations, site=lambda: site, download=lambda address: _webp(), run_off=later))
    db = Database(tmp_path / "test.db")
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    return view, db, site, later


def _its_rows(db) -> list[dict]:
    return [row for row in db.list_generations() if row["workflow_name"] == ITS_IMAGES]


def test_generate_on_a_sites_image_asks_the_site_and_never_comfyui(gallery):
    view, db, site, later = gallery

    view._on_generate_requested(ITS_IMAGES, [ASKED])

    (row,) = _its_rows(db)
    assert (row["source"], row["status"]) == (GenerationSource.OUTSIDE, GenerationStatus.RUNNING)
    assert view._jobs.all_jobs == []
    view._client.submit_job.assert_not_called()
    later.run_one()
    assert len(site.asked) == 1
    assert _its_rows(db)[0]["status"] == GenerationStatus.COMPLETED


def test_an_image_a_site_is_making_shows_among_the_items_and_not_in_the_job_queue(gallery):
    view, db, _site, _later = gallery

    view._on_generate_requested(ITS_IMAGES, [ASKED])

    (row,) = _its_rows(db)
    assert [item.key for item in view._gallery_pane.inflight_items()] == [row["prompt_id"]]
    assert view._in_flight_items() == []


def test_a_second_image_can_be_asked_of_the_site_while_the_first_is_being_made(gallery):
    view, db, _site, later = gallery

    view._on_generate_requested(ITS_IMAGES, [ASKED])
    view._on_generate_requested(ITS_IMAGES, [{**ASKED, "seed": 6}])

    assert len(_its_rows(db)) == 2
    later.run_one()
    later.run_one()
    assert {row["status"] for row in _its_rows(db)} == {GenerationStatus.COMPLETED}

