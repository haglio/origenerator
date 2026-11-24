from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from origenerator import fixes_kept
from origenerator.db import Database, NewGeneration
from origenerator.fixes_being_chosen import FixesBeingChosen
from origenerator.output_places import OutputPlaces

UNDER_THE_FIX, FIXED, UNDER_THE_EYES, EYES_FIXED = (10, 10, 10), (200, 0, 0), (0, 0, 90), (0, 200, 0)
FIX_BOX, EYES_BOX = [10, 10, 40, 40], [60, 60, 80, 80]
IN_THE_FIX, IN_THE_EYES = (20, 20), (70, 70)


class OffTheWindowsThread:
    def __init__(self, *, at_once: bool = True):
        self._at_once = at_once
        self.waiting: list = []

    def __call__(self, work, done) -> None:
        if self._at_once:
            done(work())
        else:
            self.waiting.append((work, done))

    def finish_one(self) -> None:
        work, done = self.waiting.pop(0)
        done(work())


class Enhanced:
    def __init__(self, tmp_path, *, at_once: bool = True):
        self.db = Database(tmp_path / "test.db")
        self.output = tmp_path / "output"
        self.thumbnails = tmp_path / "thumbnails"
        self.image = self.output / "image" / "enhanced.png"
        self.kept = tmp_path / "kept from fixes" / "run-1"
        self.off_thread = OffTheWindowsThread(at_once=at_once)
        self.told_written: list[Path] = []
        self.chosen = FixesBeingChosen(
            self.db, OutputPlaces.in_one_folder(self.output), self.thumbnails,
            off_thread=self.off_thread, written=self.told_written.append)
        self._an_item_enhanced_with_two_fixes()

    def _an_item_enhanced_with_two_fixes(self) -> None:
        self.db.insert_generation(NewGeneration(
            prompt_id="p1", workflow_name="sdxl_t2i", workflow_version="v002",
            params_json="{}", workflow_json="{}"))
        self.image.parent.mkdir(parents=True)
        enhanced = Image.new("RGB", (100, 100), UNDER_THE_FIX)
        enhanced.paste(FIXED, tuple(FIX_BOX))
        enhanced.paste(EYES_FIXED, tuple(EYES_BOX))
        enhanced.save(self.image)
        (self.output / "image" / "base.png").write_bytes(b"data")
        self.kept.mkdir(parents=True)
        for at, (under, fixed, box) in enumerate(((UNDER_THE_FIX, FIXED, FIX_BOX),
                                                  (UNDER_THE_EYES, EYES_FIXED, EYES_BOX))):
            size = (box[2] - box[0], box[3] - box[1])
            Image.new("RGB", size, under).save(self.kept / f"{at}_before.png")
            Image.new("RGB", size, fixed).save(self.kept / f"{at}_after.png")
            Image.new("L", size, 255).save(self.kept / f"{at}_changed.png")
        self.db.update_generation(
            "p1", status="completed",
            output_files=json.dumps([
                {"filename": "enhanced.png", "subfolder": "image", "fixes_kept": "run-1",
                 "fixes": [{"part": "faces", "box": FIX_BOX, "over": []},
                           {"part": "eyes", "box": EYES_BOX, "over": []}]},
                {"filename": "base.png", "subfolder": "image"}]),
            original_files=json.dumps([{"filename": "base.png", "subfolder": "image"}]))

    def change(self, part: str, what: str, to: bool):
        return self.chosen.change(self.db.get_generation("p1"), "enhanced.png", part, what, to)

    def on_disk(self, point=IN_THE_FIX):
        with Image.open(self.image) as image:
            return image.getpixel(point)

    def recorded(self) -> dict:
        return json.loads(self.db.get_generation("p1")["output_files"])[0]


@pytest.fixture
def enhanced(tmp_path) -> Enhanced:
    return Enhanced(tmp_path)


@pytest.fixture
def written_later(tmp_path) -> Enhanced:
    return Enhanced(tmp_path, at_once=False)


def test_a_fix_switched_off_shows_at_once_before_a_byte_of_the_file_is_written(written_later):
    shown = written_later.change("faces", "on", False)

    assert shown.image.getpixel(IN_THE_FIX) == UNDER_THE_FIX
    assert shown.file["fixes_off"] == ["faces"]
    assert shown.path == written_later.image
    assert written_later.on_disk() == FIXED, (
        "the screen waited on the file, and a click took seconds to show")


def test_the_file_follows_off_the_windows_thread_and_whoever_shows_it_is_told(written_later):
    written_later.change("faces", "on", False)

    written_later.off_thread.finish_one()

    assert written_later.on_disk() == UNDER_THE_FIX
    assert written_later.told_written == [written_later.image]


def test_clicks_made_while_the_file_is_being_written_are_all_shown_and_written_once_more(
        written_later):
    written_later.change("faces", "on", False)
    back_on = written_later.change("faces", "on", True)
    eyes_off = written_later.change("eyes", "on", False)

    assert back_on.image.getpixel(IN_THE_FIX) == FIXED
    assert (eyes_off.image.getpixel(IN_THE_FIX), eyes_off.image.getpixel(IN_THE_EYES)) == (
        FIXED, UNDER_THE_EYES), "each click is drawn onto what the screen shows, never onto the file"
    assert len(written_later.off_thread.waiting) == 1, "one writer at a time, whatever is clicked"
    written_later.off_thread.finish_one()
    written_later.off_thread.finish_one()

    assert written_later.off_thread.waiting == []
    assert (written_later.on_disk(), written_later.on_disk(IN_THE_EYES)) == (FIXED, UNDER_THE_EYES)


def test_the_record_waits_until_it_is_asked_for_and_then_says_what_the_file_shows(enhanced):
    enhanced.change("faces", "on", False)
    before_the_choosing_rests = enhanced.recorded()

    assert enhanced.chosen.record() == ["p1"]

    assert "fixes_off" not in before_the_choosing_rests, (
        "every change to the record has the whole gallery read again, which is what a click "
        "waited on")
    assert enhanced.recorded()["fixes_off"] == ["faces"]
    assert enhanced.chosen.record() == []


def test_nothing_is_recorded_while_the_file_is_still_behind_the_screen(written_later):
    written_later.change("faces", "on", False)

    assert written_later.chosen.any_being_written()
    assert written_later.chosen.record() == []
    written_later.off_thread.finish_one()
    assert not written_later.chosen.any_being_written()
    assert written_later.chosen.record() == ["p1"]


def test_a_fix_switched_back_on_is_drawn_again_and_recorded_as_on(enhanced):
    enhanced.change("faces", "on", False)

    shown = enhanced.change("faces", "on", True)
    enhanced.chosen.record()

    assert (shown.image.getpixel(IN_THE_FIX), enhanced.on_disk()) == (FIXED, FIXED)
    assert "fixes_off" not in enhanced.recorded()


def test_a_change_made_after_the_record_was_written_starts_from_the_record(enhanced):
    enhanced.change("faces", "on", False)
    enhanced.chosen.record()

    shown = enhanced.change("eyes", "on", False)

    assert shown.file["fixes_off"] == ["faces", "eyes"]
    assert (shown.image.getpixel(IN_THE_FIX), shown.image.getpixel(IN_THE_EYES)) == (
        UNDER_THE_FIX, UNDER_THE_EYES)


def test_the_first_change_after_a_record_draws_on_the_image_last_written_without_reading_it(
        enhanced, monkeypatch):
    enhanced.change("faces", "on", False)
    enhanced.chosen.record()
    monkeypatch.setattr(fixes_kept, "opened", lambda path: pytest.fail(
        "decoding the whole file again is most of what the first click after a rest waited on"))

    shown = enhanced.change("faces", "on", True)

    assert shown.image.getpixel(IN_THE_FIX) == FIXED


def test_an_image_written_by_something_else_since_the_record_is_read_again(enhanced):
    enhanced.change("faces", "on", False)
    enhanced.chosen.record()
    Image.new("RGB", (100, 100), UNDER_THE_EYES).save(enhanced.image)

    shown = enhanced.change("eyes", "on", False)

    assert shown.image.getpixel(IN_THE_FIX) == UNDER_THE_EYES, (
        "the image kept from the last record is no longer what the file holds")


def test_marking_a_fix_as_bad_changes_no_image_and_is_recorded_with_the_rest(enhanced):
    written = enhanced.image.read_bytes()

    shown = enhanced.change("faces", "bad", True)
    enhanced.chosen.record()

    assert (shown.image, shown.file["fixes_left_out"]) == (None, ["faces"])
    assert enhanced.image.read_bytes() == written
    assert enhanced.told_written == []
    assert enhanced.recorded()["fixes_left_out"] == ["faces"]


def test_the_thumbnail_follows_a_switch_of_the_enhancement_the_item_shows(enhanced):
    enhanced.change("faces", "on", False)

    enhanced.chosen.record()

    with Image.open(enhanced.db.get_generation("p1")["thumbnail_path"]) as thumbnail:
        red, green, blue = thumbnail.getpixel(IN_THE_FIX)
    assert max(abs(red - green), abs(red - blue)) < 12, "the fix was red, and what was under it gray"


def test_a_switch_asks_nothing_to_let_go_of_the_image_and_redraws_it_while_it_is_held_open(
        enhanced):
    with open(enhanced.image, "rb"):
        assert enhanced.change("faces", "on", False) is not None

    assert enhanced.on_disk() == UNDER_THE_FIX, (
        "letting go made a slideshow drop the image it was showing, and a slideshow of that one "
        "image closed")


def test_a_fix_whose_kept_places_are_gone_stays_as_it_is(enhanced):
    (enhanced.kept / "0_before.png").unlink()
    recorded = enhanced.recorded()

    assert enhanced.change("faces", "on", False) is None

    assert enhanced.chosen.record() == []
    assert (enhanced.recorded(), enhanced.on_disk()) == (recorded, FIXED)


def test_a_change_that_changes_nothing_or_names_no_such_enhancement_is_refused(enhanced):
    row = enhanced.db.get_generation("p1")

    assert enhanced.change("faces", "on", True) is None
    assert enhanced.chosen.change(row, "gone.png", "faces", "on", False) is None
    assert enhanced.chosen.change(row, "base.png", "faces", "on", False) is None


def test_settling_writes_what_the_screen_shows_and_records_it_without_waiting_for_the_writer(
        written_later):
    written_later.change("faces", "on", False)
    written_later.change("eyes", "on", False)

    assert written_later.chosen.settle() == ["p1"]

    assert (written_later.on_disk(), written_later.on_disk(IN_THE_EYES)) == (
        UNDER_THE_FIX, UNDER_THE_EYES)
    assert written_later.recorded()["fixes_off"] == ["faces", "eyes"]
    assert written_later.told_written == [written_later.image]
    written_later.off_thread.finish_one()
    assert written_later.off_thread.waiting == [], "the writer that comes back late writes nothing"


def test_a_file_written_and_not_yet_recorded_can_be_finished_after_a_crash_until_it_is_recorded(
        enhanced):
    enhanced.change("faces", "on", False)

    cut_short_here = fixes_kept.finish_what_was_written(enhanced.kept, enhanced.image)
    enhanced.chosen.record()

    assert cut_short_here == ["faces"]
    assert fixes_kept.finish_what_was_written(enhanced.kept, enhanced.image) is None


def test_an_enhancement_deleted_while_its_fixes_were_being_chosen_is_recorded_nowhere(enhanced):
    enhanced.change("faces", "on", False)
    enhanced.db.update_generation("p1", output_files=json.dumps(
        [{"filename": "base.png", "subfolder": "image"}]))

    assert enhanced.chosen.record() == []
    assert [entry["filename"] for entry in json.loads(
        enhanced.db.get_generation("p1")["output_files"])] == ["base.png"]
