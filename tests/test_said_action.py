from __future__ import annotations

import json
import os

from origenerator import said_action
from origenerator.action_labels import Labels
from origenerator.generation_state import GenerationSource
from origenerator.gui.action_presses import striking
from origenerator.media import MediaType
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

    def set_labels(self, prompt_id, side, labels):
        self.said.append((side, prompt_id, labels))

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


def _labeled(*, image=(), video=()) -> dict:
    return {**({"image_actions": json.dumps(list(image))} if image else {}),
            **({"video_actions": json.dumps(list(video))} if video else {})}


def _a_sites_video_set_as_alpha(places: Places) -> tuple[dict, Slide, object]:
    return _a_recorded_video(places, "example_site", **_labeled(video=["alpha"]),
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


class TestStrikingTheActionOnScreen:
    def test_an_images_actions_are_the_ones_set_for_it(self):
        db = _Gallery(_an_image(**_labeled(image=["beta", "gamma"])))

        assert said_action.strike(db, Slide("g1.png", "image", "g1"), _nowhere) == "beta, gamma"
        assert db.said == [(MediaType.IMAGE, "g1", Labels())]

    def test_a_videos_actions_come_off_the_video(self):
        db = _Gallery(_a_video(**_labeled(video=["alpha"])))

        assert said_action.strike(db, Slide("v1.mp4", "video", "v1"), _nowhere) == "alpha"
        assert db.said == [(MediaType.VIDEO, "v1", Labels())]

    def test_a_video_made_from_no_image_loses_the_image_actions_it_holds_as_its_own_too(self):
        db = _Gallery(_a_video(**_labeled(image=["beta"], video=["alpha"])))

        assert said_action.strike(db, Slide("v1.mp4", "video", "v1"), _nowhere) == "beta, alpha"
        assert db.said == [(MediaType.IMAGE, "v1", Labels()), (MediaType.VIDEO, "v1", Labels())]

    def test_an_item_with_no_action_anywhere_has_none_to_strike(self):
        db = _Gallery(_an_image())

        assert said_action.strike(db, Slide("g1.png", "image", "g1"), _nowhere) == ""
        assert said_action.strike(db, Slide("gone.png", "image", "gone"), _nowhere) == ""
        assert db.said == []

    def test_another_sites_video_keeps_the_rejection_in_its_record_as_kinos_does(
            self, tmp_path):
        places = _places(tmp_path)
        row, slide, record = _a_sites_video_set_as_alpha(places)
        db = _Gallery(row)

        assert said_action.strike(db, slide, lambda: places) == "alpha"

        assert _recorded(record) == {"wrong_action": "alpha", "prompt": "a made-up prompt"}
        assert db.said == [(MediaType.VIDEO, "o1", Labels())]
        assert not places.journal.exists()

    def test_a_pick_of_his_evolver_has_yet_to_write_down_is_cancelled_or_it_would_come_back(
            self, tmp_path):
        places = _places(tmp_path)
        row, slide, record = _a_sites_video_set_as_alpha(places)
        os.utime(record, (1_000_000, 1_000_000))
        db = _Gallery(row)
        _picked_before(places, slide, "alpha", 2_000_000)

        assert said_action.strike(db, slide, lambda: places) == "alpha"

        assert _picked(places) == [""]

    def test_a_pick_evolver_wrote_into_the_record_long_ago_is_not_journaled_again(
            self, tmp_path):
        places = _places(tmp_path)
        row, slide, record = _a_sites_video_set_as_alpha(places)
        places.journal.parent.mkdir(parents=True)
        places.journal.write_text(json.dumps({
            "t": 1000, "event": "action", "action": "alpha",
            "path": slide.path.relative_to(places.library_root).as_posix()}) + "\n",
            encoding="utf-8")

        assert said_action.strike(_Gallery(row), slide, lambda: places) == "alpha"

        assert _picked(places) == ["alpha"]
        assert _recorded(record)["wrong_action"] == "alpha"

    def test_a_video_made_here_loses_it_in_the_record_of_the_upscale_being_played(self, tmp_path):
        places = _places(tmp_path)
        row, slide, record = _a_recorded_video(places, "origenerator", **_labeled(video=["alpha"]))
        db = _Gallery(row)

        assert said_action.strike(db, slide, lambda: places) == "alpha"

        assert _recorded(record)["wrong_action"] == "alpha"
        assert db.said == [(MediaType.VIDEO, "o1", Labels())]
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
    row, slide, record = _a_sites_video_set_as_alpha(places)
    gallery = _Gallery(row)

    assert striking(gallery, gallery, places_here=lambda: places)(slide) == "alpha"

    assert _recorded(record)["wrong_action"] == "alpha"
    assert gallery.reread == 1


def test_the_slideshows_press_on_a_slide_with_no_action_leaves_the_gallery_as_it_is():
    gallery = _Gallery(_an_image())

    assert striking(gallery, gallery, places_here=_nowhere)(Slide("g1.png", "image", "g1")) == ""

    assert gallery.reread == 0
