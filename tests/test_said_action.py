from __future__ import annotations

import json

from origenerator import said_action
from origenerator.generation_state import GenerationSource
from origenerator.gui.action_presses import striking
from origenerator.outside_journal import actions_in, said_in
from origenerator.outside_videos import Places
from origenerator.slideshow import Slide


class _Gallery:
    def __init__(self, *rows):
        self.rows = {row["prompt_id"]: row for row in rows}
        self.said = []
        self.reread = 0

    def get_generation(self, prompt_id):
        return self.rows.get(prompt_id)

    def set_action(self, prompt_id, action):
        self.said.append(("action", prompt_id, action))

    def set_image_state(self, prompt_id, state):
        self.said.append(("image state", prompt_id, state))

    def refresh(self):
        self.reread += 1


def _places(tmp_path) -> Places:
    library = tmp_path / "videos"
    return Places(upscaled_dir=library / "videos" / "outbox", records_folder=library / "metadata",
                  frames_dir=tmp_path / "frames", thumb_dir=tmp_path / "thumbs",
                  skip_sources=frozenset(), library_root=library,
                  journal=tmp_path / "journals" / "origenerator.jsonl")


def _nowhere():
    return None


def _an_image(**fields) -> dict:
    return {"prompt_id": "g1", "workflow_name": "sdxl_t2i",
            "output_files": json.dumps([{"filename": "g1.png"}]), **fields}


def _a_video(prompt_id="v1", **fields) -> dict:
    return {"prompt_id": prompt_id, "workflow_name": "wan22_i2v",
            "output_files": json.dumps([{"filename": f"{prompt_id}.mp4"}]), **fields}


def _a_recorded_video(places: Places, filed_under: str, **fields) -> tuple[dict, Slide, object]:
    video = places.upscaled_dir / "portrait" / filed_under / "scene one_topaz.mp4"
    record = (places.records_folder / "outbox" / "portrait" / filed_under
              / "scene one_topaz.json")
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({"video": {"action": "alpha", "prompt": "a made-up prompt"}}),
                      encoding="utf-8")
    row = {"prompt_id": "o1", "workflow_name": "wan22_i2v", **fields,
           "output_files": json.dumps([{"filename": video.name, "library_path": str(video)}])}
    return row, Slide(video, "video", "o1"), record


def _recorded(record) -> dict:
    return json.loads(record.read_text(encoding="utf-8"))["video"]


class TestSayingAnAction:
    def test_an_image_is_told_what_it_was_sorted_as(self):
        db = _Gallery()

        said_action.say(db, "g1", _an_image(), "beta", places_here=_nowhere)

        assert db.said == [("image state", "g1", "beta")]

    def test_a_video_made_here_is_told_its_action_and_no_action_is_told_as_none(self):
        db = _Gallery()

        said_action.say(db, "v1", _a_video(), "alpha", places_here=_nowhere)
        said_action.say(db, "v1", _a_video(), "", places_here=_nowhere)

        assert db.said == [("action", "v1", "alpha"), ("action", "v1", None)]

    def test_another_sites_video_has_its_action_written_down_for_the_gallerys_next_entries(
            self, tmp_path):
        places = _places(tmp_path)
        row, _slide, _record = _a_recorded_video(places, "example_site",
                                                 source=GenerationSource.OUTSIDE)
        db = _Gallery()

        said_action.say(db, "o1", row, "beta", places_here=lambda: places)

        assert [action for _when, action in actions_in(said_in(places.journal)).values()] == [
            "beta"]
        assert db.said == [("action", "o1", "beta")]


class TestStrikingTheActionOnScreen:
    def test_an_images_action_is_what_it_was_sorted_as(self):
        db = _Gallery(_an_image(image_state="beta"))

        assert said_action.strike(db, Slide("g1.png", "image", "g1"), _nowhere) == "beta"
        assert db.said == [("image state", "g1", None)]

    def test_a_videos_action_comes_off_the_video(self):
        db = _Gallery(_a_video(action="alpha"))

        assert said_action.strike(db, Slide("v1.mp4", "video", "v1"), _nowhere) == "alpha"
        assert db.said == [("action", "v1", None)]

    def test_an_item_with_no_action_anywhere_has_none_to_strike(self):
        db = _Gallery(_an_image())

        assert said_action.strike(db, Slide("g1.png", "image", "g1"), _nowhere) == ""
        assert said_action.strike(db, Slide("gone.png", "image", "gone"), _nowhere) == ""
        assert db.said == []

    def test_another_sites_video_loses_it_in_its_record_and_in_the_gallerys_next_entries(
            self, tmp_path):
        places = _places(tmp_path)
        row, slide, record = _a_recorded_video(places, "example_site", action="alpha",
                                               source=GenerationSource.OUTSIDE)
        db = _Gallery(row)

        assert said_action.strike(db, slide, lambda: places) == "alpha"

        assert _recorded(record) == {"wrong_action": "alpha", "prompt": "a made-up prompt"}
        assert [action for _when, action in actions_in(said_in(places.journal)).values()] == [""]

    def test_a_video_made_here_loses_it_in_the_record_of_the_upscale_being_played(self, tmp_path):
        places = _places(tmp_path)
        row, slide, record = _a_recorded_video(places, "origenerator", action="alpha")
        db = _Gallery(row)

        assert said_action.strike(db, slide, lambda: places) == "alpha"

        assert _recorded(record)["wrong_action"] == "alpha"
        assert db.said == [("action", "o1", None)]
        assert not places.journal.exists()

    def test_an_action_only_the_record_holds_is_struck_there_and_said(self, tmp_path):
        places = _places(tmp_path)
        row, slide, record = _a_recorded_video(places, "origenerator")
        db = _Gallery(row)

        assert said_action.strike(db, slide, lambda: places) == "alpha"

        assert "action" not in _recorded(record)
        assert db.said == []


def test_the_slideshows_press_strikes_the_action_and_has_the_gallery_reread(tmp_path):
    places = _places(tmp_path)
    row, slide, record = _a_recorded_video(places, "example_site", action="alpha",
                                           source=GenerationSource.OUTSIDE)
    gallery = _Gallery(row)

    assert striking(gallery, gallery, places_here=lambda: places)(slide) == "alpha"

    assert _recorded(record)["wrong_action"] == "alpha"
    assert gallery.reread == 1


def test_the_slideshows_press_on_a_slide_with_no_action_leaves_the_gallery_as_it_is():
    gallery = _Gallery(_an_image())

    assert striking(gallery, gallery, places_here=_nowhere)(Slide("g1.png", "image", "g1")) == ""

    assert gallery.reread == 0
