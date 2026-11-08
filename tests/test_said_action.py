from __future__ import annotations

import json
import os

from origenerator import said_action
from origenerator.db import Database, NewGeneration
from origenerator.generation_state import GenerationSource
from origenerator.gui.action_presses import striking
from origenerator.item_actions import ItemActions, actions_of
from origenerator.media import MediaType
from origenerator.outside_journal import actions_in, said_in
from origenerator.outside_videos import Places
from origenerator.sent_back import SentBack
from origenerator.slideshow import Slide


class _Gallery:
    def __init__(self):
        self.reread = 0

    def refresh(self):
        self.reread += 1


def _places(tmp_path) -> Places:
    library = tmp_path / "videos"
    return Places(kino=library / "videos" / "kino", records_folder=library / "metadata",
                  frames_dir=tmp_path / "frames", thumb_dir=tmp_path / "thumbs",
                  skip_sources=frozenset(), library_root=library,
                  journal=tmp_path / "journals" / "origenerator.jsonl")


def _nowhere():
    return None


def _a_finished(db, prompt_id: str, workflow: str, output: dict, *,
                source=GenerationSource.GENERATED, **params) -> None:
    db.insert_generation(NewGeneration(prompt_id=prompt_id, workflow_name=workflow,
                         workflow_version="v1", seed=1, workflow_json="{}", source=source,
                         params_json=json.dumps({"positive_prompt": "a red kite", "seed": 1,
                                                 **params})))
    db.update_generation(prompt_id, status="completed", output_files=json.dumps([output]))


def _a_db(tmp_path) -> Database:
    return Database(tmp_path / "origenerator.db")


def _an_image(db, item_actions=None) -> Slide:
    _a_finished(db, "g1", "sdxl_t2i", {"filename": "g1.png", "subfolder": ""})
    if item_actions:
        db.set_actions("g1", MediaType.IMAGE, item_actions)
    return Slide("g1.png", "image", "g1")


def _a_video(db, *, image=None, video=None, **params) -> Slide:
    _a_finished(db, "v1", "wan22_i2v", {"filename": "v1.mp4", "subfolder": ""}, **params)
    for side, item_actions in ((MediaType.IMAGE, image), (MediaType.VIDEO, video)):
        if item_actions:
            db.set_actions("v1", side, item_actions)
    return Slide("v1.mp4", "video", "v1")


def _a_recorded_video(db, places: Places, filed_under: str, *, video=None,
                      source=GenerationSource.GENERATED) -> tuple[Slide, object]:
    played = places.upscaled_dir / "portrait" / filed_under / "scene one_topaz.mp4"
    record = (places.records_folder / "kino" / "2D" / "AI" / "portrait" / filed_under
              / "scene one_topaz.json")
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({"video": {"action": "alpha", "prompt": "a made-up prompt"}}),
                      encoding="utf-8")
    _a_finished(db, "o1", "wan22_i2v", {"filename": played.name, "library_path": str(played)},
                source=source)
    if video:
        db.set_actions("o1", MediaType.VIDEO, video)
    return Slide(played, "video", "o1"), record


def _a_sites_video_set_as_alpha(db, places: Places) -> tuple[Slide, object]:
    return _a_recorded_video(db, places, "example_site", video=ItemActions(("alpha",)),
                             source=GenerationSource.OUTSIDE)


def _picked_before(places: Places, slide: Slide, action: str, at: float) -> None:
    places.journal.parent.mkdir(parents=True, exist_ok=True)
    line = {"t": round(at * 1000), "event": "action", "action": action,
            "path": slide.path.relative_to(places.library_root).as_posix()}
    with places.journal.open("a", encoding="utf-8", newline="\n") as journal:
        journal.write(json.dumps(line) + "\n")


def _picked(places: Places) -> list[str]:
    return [action for _when, action in actions_in(said_in(places.journal)).values()]


def _recorded(record) -> dict:
    return json.loads(record.read_text(encoding="utf-8"))["video"]


def _item_actions(db, prompt_id, side) -> ItemActions:
    return actions_of(db.get_generation(prompt_id), side)


def _sent_back(tmp_path) -> SentBack:
    return SentBack(tmp_path / "sent_back.json")


class TestStrikingTheActionOnScreen:
    def test_an_images_actions_are_asked_for_again(self, tmp_path):
        db = _a_db(tmp_path)
        slide = _an_image(db, ItemActions(("beta", "gamma")))
        kept = _sent_back(tmp_path)

        assert said_action.strike(db, slide, _nowhere, kept) == "beta, gamma"
        assert (_item_actions(db, "g1", MediaType.IMAGE), kept.ids()) == (ItemActions(), ("g1",))

    def test_a_videos_actions_come_off_the_video(self, tmp_path):
        db = _a_db(tmp_path)
        slide = _a_video(db, video=ItemActions(("alpha",)))

        assert said_action.strike(db, slide, _nowhere, _sent_back(tmp_path)) == "alpha"
        assert _item_actions(db, "v1", MediaType.VIDEO) == ItemActions()

    def test_a_video_made_from_no_image_loses_the_image_actions_it_holds_as_its_own_too(
            self, tmp_path):
        db = _a_db(tmp_path)
        slide = _a_video(db, image=ItemActions(("beta",)), video=ItemActions(("alpha",)))

        assert said_action.strike(db, slide, _nowhere, _sent_back(tmp_path)) == "beta, alpha"
        assert [_item_actions(db, "v1", side) for side in (MediaType.IMAGE, MediaType.VIDEO)] == [
            ItemActions(), ItemActions()]

    def test_a_video_made_from_an_image_sends_that_image_back_too(self, tmp_path):
        db = _a_db(tmp_path)
        _an_image(db, ItemActions(("beta",)))
        slide = _a_video(db, video=ItemActions(("alpha",)), input_image="g1.png")
        kept = _sent_back(tmp_path)

        assert said_action.strike(db, slide, _nowhere, kept) == "beta, alpha"
        assert (_item_actions(db, "g1", MediaType.IMAGE), kept.ids()) == (ItemActions(), ("v1", "g1"))

    def test_an_item_with_no_action_anywhere_has_none_to_strike(self, tmp_path):
        db = _a_db(tmp_path)
        slide = _an_image(db)
        kept = _sent_back(tmp_path)

        assert said_action.strike(db, slide, _nowhere, kept) == ""
        assert said_action.strike(db, Slide("gone.png", "image", "gone"), _nowhere, kept) == ""
        assert kept.ids() == ()

    def test_the_record_kino_keeps_of_a_sites_video_is_left_as_it_is(self, tmp_path):
        places = _places(tmp_path)
        db = _a_db(tmp_path)
        slide, record = _a_sites_video_set_as_alpha(db, places)

        assert said_action.strike(db, slide, lambda: places, _sent_back(tmp_path)) == "alpha"

        assert _recorded(record) == {"action": "alpha", "prompt": "a made-up prompt"}
        assert _item_actions(db, "o1", MediaType.VIDEO) == ItemActions()
        assert not places.journal.exists()

    def test_a_pick_of_his_evolver_has_yet_to_write_down_is_cancelled_or_it_would_come_back(
            self, tmp_path):
        places = _places(tmp_path)
        db = _a_db(tmp_path)
        slide, record = _a_sites_video_set_as_alpha(db, places)
        os.utime(record, (1_000_000, 1_000_000))
        _picked_before(places, slide, "alpha", 2_000_000)

        assert said_action.strike(db, slide, lambda: places, _sent_back(tmp_path)) == "alpha"

        assert _picked(places) == [""]

    def test_a_pick_evolver_wrote_into_the_record_long_ago_is_not_journaled_again(
            self, tmp_path):
        places = _places(tmp_path)
        db = _a_db(tmp_path)
        slide, _record = _a_sites_video_set_as_alpha(db, places)
        places.journal.parent.mkdir(parents=True)
        places.journal.write_text(json.dumps({
            "t": 1000, "event": "action", "action": "alpha",
            "path": slide.path.relative_to(places.library_root).as_posix()}) + "\n",
            encoding="utf-8")

        assert said_action.strike(db, slide, lambda: places, _sent_back(tmp_path)) == "alpha"

        assert _picked(places) == ["alpha"]

    def test_an_action_only_kinos_record_holds_is_none_of_this_apps_to_strike(self, tmp_path):
        places = _places(tmp_path)
        db = _a_db(tmp_path)
        slide, record = _a_recorded_video(db, places, "origenerator")

        assert said_action.strike(db, slide, lambda: places, _sent_back(tmp_path)) == ""

        assert _recorded(record)["action"] == "alpha"


def test_the_slideshows_press_sends_the_item_back_and_has_the_gallery_reread(tmp_path):
    places = _places(tmp_path)
    db = _a_db(tmp_path)
    slide, _record = _a_sites_video_set_as_alpha(db, places)
    gallery = _Gallery()
    kept = _sent_back(tmp_path)

    assert striking(db, gallery, places_here=lambda: places, sent_back=lambda: kept)(slide) == (
        "alpha")

    assert (kept.ids(), gallery.reread) == (("o1",), 1)


def test_the_slideshows_press_on_a_slide_with_no_action_leaves_the_gallery_as_it_is(tmp_path):
    db = _a_db(tmp_path)
    gallery = _Gallery()

    struck = striking(db, gallery, places_here=_nowhere,
                      sent_back=lambda: _sent_back(tmp_path))(_an_image(db))

    assert (struck, gallery.reread) == ("", 0)
