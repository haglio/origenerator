from __future__ import annotations

import json

from origenerator.db import Database, NewGeneration
from origenerator.generation_state import GenerationSource
from origenerator.gui.action_presses import striking
from origenerator.item_actions import ItemActions, actions_of
from origenerator.media import MediaType
from origenerator.sent_back import SentBack, send_back
from origenerator.slideshow import Slide


class _Gallery:
    def __init__(self):
        self.reread = 0

    def refresh(self):
        self.reread += 1


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


def _a_sites_video(tmp_path, db, *, video=None) -> Slide:
    played = tmp_path / "kino" / "portrait" / "example_site" / "scene one_topaz.mp4"
    _a_finished(db, "o1", "wan22_i2v", {"filename": played.name, "library_path": str(played)},
                source=GenerationSource.OUTSIDE)
    db.set_action("o1", "alpha")
    if video:
        db.set_actions("o1", MediaType.VIDEO, video)
    return Slide(played, "video", "o1")


def _item_actions(db, prompt_id, side) -> ItemActions:
    return actions_of(db.get_generation(prompt_id), side)


def _sent_back(tmp_path) -> SentBack:
    return SentBack(tmp_path / "sent_back.json")


class TestSendingBackTheActionOnScreen:
    def test_an_images_actions_are_asked_for_again(self, tmp_path):
        db = _a_db(tmp_path)
        slide = _an_image(db, ItemActions(("beta", "gamma")))
        kept = _sent_back(tmp_path)

        assert send_back(db, slide.prompt_id, kept) == "beta, gamma"
        assert (_item_actions(db, "g1", MediaType.IMAGE), kept.ids()) == (ItemActions(), ("g1",))

    def test_a_videos_actions_come_off_the_video(self, tmp_path):
        db = _a_db(tmp_path)
        slide = _a_video(db, video=ItemActions(("alpha",)))

        assert send_back(db, slide.prompt_id, _sent_back(tmp_path)) == "alpha"
        assert _item_actions(db, "v1", MediaType.VIDEO) == ItemActions()

    def test_a_video_made_from_no_image_loses_the_image_actions_it_holds_as_its_own_too(
            self, tmp_path):
        db = _a_db(tmp_path)
        slide = _a_video(db, image=ItemActions(("beta",)), video=ItemActions(("alpha",)))

        assert send_back(db, slide.prompt_id, _sent_back(tmp_path)) == "beta, alpha"
        assert [_item_actions(db, "v1", side) for side in (MediaType.IMAGE, MediaType.VIDEO)] == [
            ItemActions(), ItemActions()]

    def test_a_video_made_from_an_image_sends_that_image_back_too(self, tmp_path):
        db = _a_db(tmp_path)
        _an_image(db, ItemActions(("beta",)))
        slide = _a_video(db, video=ItemActions(("alpha",)), input_image="g1.png")
        kept = _sent_back(tmp_path)

        assert send_back(db, slide.prompt_id, kept) == "beta, alpha"
        assert (_item_actions(db, "g1", MediaType.IMAGE), kept.ids()) == (ItemActions(), ("v1", "g1"))

    def test_a_sites_video_loses_the_actions_set_here_and_keeps_the_one_its_site_gave(
            self, tmp_path):
        db = _a_db(tmp_path)
        slide = _a_sites_video(tmp_path, db, video=ItemActions(("beta",)))

        assert send_back(db, slide.prompt_id, _sent_back(tmp_path)) == "beta"

        row = db.get_generation("o1")
        assert (actions_of(row, MediaType.VIDEO), row["action"]) == (ItemActions(), "alpha")
        assert not (tmp_path / "kino").exists()

    def test_an_action_only_its_site_gave_is_none_of_this_apps_to_strike(self, tmp_path):
        db = _a_db(tmp_path)
        slide = _a_sites_video(tmp_path, db)

        assert send_back(db, slide.prompt_id, _sent_back(tmp_path)) == ""

        assert db.get_generation("o1")["action"] == "alpha"

    def test_an_item_with_no_action_anywhere_has_none_to_strike(self, tmp_path):
        db = _a_db(tmp_path)
        slide = _an_image(db)
        kept = _sent_back(tmp_path)

        assert send_back(db, slide.prompt_id, kept) == ""
        assert send_back(db, Slide("gone.png", "image", "gone").prompt_id, kept) == ""
        assert kept.ids() == ()

def test_the_slideshows_press_sends_the_item_back_and_has_the_gallery_reread(tmp_path):
    db = _a_db(tmp_path)
    slide = _a_sites_video(tmp_path, db, video=ItemActions(("alpha",)))
    gallery = _Gallery()
    kept = _sent_back(tmp_path)

    assert striking(db, gallery, sent_back=lambda: kept)(slide) == "alpha"

    assert (kept.ids(), gallery.reread) == (("o1",), 1)


def test_the_slideshows_press_on_a_slide_with_no_action_leaves_the_gallery_as_it_is(tmp_path):
    db = _a_db(tmp_path)
    gallery = _Gallery()

    struck = striking(db, gallery, sent_back=lambda: _sent_back(tmp_path))(_an_image(db))

    assert (struck, gallery.reread) == ("", 0)
