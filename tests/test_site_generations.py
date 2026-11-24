from __future__ import annotations

import json

import pytest
from app_support import haglio_settings

from origenerator import sites
from origenerator.db import Database
from origenerator.generation_state import GenerationStatus
from origenerator.gui.site_generations import (
    NOT_DOWNLOADED,
    SiteGenerations,
    why_in_words,
)
from origenerator.media import MediaType
from origenerator.output_places import OutputFolders, OutputPlaces
from origenerator.site_generation import NEVER_ANSWERED, Made, SiteRefused
from origenerator.workflows import workflow_named
from origenerator.workflows.outside import outside_workflow
from tests.test_site_items import _webp

KEY = "made-up folder"
ASKED = {"positive_prompt": "a red apple", "quality": "Base"}


class FakeSite:
    def __init__(self, *answers):
        self._answers = list(answers)
        self.asked: list[str] = []
        self.closed = 0

    def make(self, address: str) -> Made:
        self.asked.append(address)
        answer = self._answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def close(self) -> None:
        self.closed += 1


class Later:
    def __init__(self):
        self.waiting: list = []

    def __call__(self, work, done, *, owner) -> None:
        self.waiting.append((work, done))

    def run_one(self) -> None:
        work, done = self.waiting.pop(0)
        done(work())


@pytest.fixture
def making(qapp, monkeypatch, tmp_path):
    written = tmp_path / "haglio_settings.json"
    written.write_text(json.dumps({**haglio_settings.example_inside(tmp_path), sites.SETTING: {
        "madeup": {"image": "https://example.com/create"}}}), encoding="utf-8")
    monkeypatch.setenv(haglio_settings.SETTINGS_ENV, str(written))

    def build(site, download=lambda address: _webp()):
        db = Database(tmp_path / "test.db")
        folders = OutputFolders(OutputPlaces.in_one_folder(tmp_path / "out"), tmp_path / "thumbs")
        later = Later()
        generations = SiteGenerations(db, folders, site=lambda: site, download=download,
                                      run_off=later)
        heard = {"finished": [], "failed": []}
        generations.finished.connect(lambda *said: heard["finished"].append(said))
        generations.failed.connect(lambda *said: heard["failed"].append(said))
        return generations, db, later, heard

    return build


def _its_images():
    return workflow_named(outside_workflow("madeup", MediaType.IMAGE))


def test_an_image_asked_of_a_site_is_made_off_the_windows_thread_and_filed(making):
    site = FakeSite(Made("https://example.com/a.webp", seed="5"))
    generations, db, later, heard = making(site)

    (prompt_id,) = generations.start_batch(KEY, _its_images(), [ASKED])

    assert db.get_generation(prompt_id)["status"] == GenerationStatus.RUNNING
    assert generations.making() == {prompt_id}
    later.run_one()
    assert db.get_generation(prompt_id)["status"] == GenerationStatus.COMPLETED
    assert heard == {"finished": [(KEY, prompt_id, prompt_id)], "failed": []}
    assert site.asked[0].startswith("https://example.com/create#ft=")
    assert generations.making() == set()


def test_several_images_are_made_one_after_another_and_the_chrome_closed_after_the_last(making):
    site = FakeSite(Made("https://example.com/a.webp"), Made("https://example.com/b.webp"))
    generations, _db, later, heard = making(site)

    first, second = generations.start_batch(KEY, _its_images(), [ASKED, ASKED])

    assert len(later.waiting) == 1
    later.run_one()
    assert site.closed == 0
    assert generations.making() == {second}
    later.run_one()
    assert site.closed == 1
    assert [said[1] for said in heard["finished"]] == [first, second]


def test_an_image_a_site_refuses_fails_with_the_reason_in_words(making):
    generations, db, later, heard = making(FakeSite(SiteRefused(NEVER_ANSWERED)))

    (prompt_id,) = generations.start_batch(KEY, _its_images(), [ASKED])
    later.run_one()

    assert db.get_generation(prompt_id)["status"] == GenerationStatus.ERROR
    assert heard["failed"] == [(KEY, "madeup did not make the image: the site never answered.")]


def test_an_image_that_cannot_be_downloaded_fails(making):
    def refuse(address):
        raise OSError("refused")

    generations, _db, later, heard = making(FakeSite(Made("https://example.com/a.webp")), refuse)

    generations.start_batch(KEY, _its_images(), [ASKED])
    later.run_one()

    assert heard["failed"] == [(KEY, why_in_words("madeup", NOT_DOWNLOADED))]


def test_an_image_deleted_while_the_site_made_it_ends_without_a_word(making):
    generations, db, later, heard = making(FakeSite(Made("https://example.com/a.webp")))
    (prompt_id,) = generations.start_batch(KEY, _its_images(), [ASKED])
    db.delete_generation(prompt_id)

    later.run_one()

    assert heard == {"finished": [], "failed": []}


def test_closing_drops_what_waits_and_closes_the_chrome(making):
    site = FakeSite(Made("https://example.com/a.webp"))
    generations, _db, later, _heard = making(site)
    generations.start_batch(KEY, _its_images(), [ASKED, ASKED])

    generations.close()
    later.run_one()

    assert site.closed == 2
    assert later.waiting == []


def test_a_reason_the_site_gives_in_its_own_words_is_passed_on():
    assert why_in_words("madeup", "made-up reason") == (
        "madeup did not make the image: made-up reason.")
