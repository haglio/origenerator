from __future__ import annotations

import json

from origenerator import config, warm_gun_records
from origenerator.db import Database
from origenerator.generation_state import GenerationSource
from origenerator.warm_gun_records import FILE_NAME, PhoneRecords, PlayedFrom, records_for_the_phone
from tests.media_files import write_mp4


def _played_from(tmp_path) -> PlayedFrom:
    library = tmp_path / "library"
    return PlayedFrom(library_root=library, kino=library / "videos" / "videos" / "kino" / "2D" / "AI",
                   genau=library / "videos" / "videos" / "genau")


def _filed(folder, name: str):
    path = folder / "portrait" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not really a video")
    return path


def _outside(db, prompt_id: str, video, **fields) -> None:
    db.insert_rows([{"prompt_id": prompt_id, "source": GenerationSource.OUTSIDE,
                     "workflow_name": "outside:Example Site", "workflow_version": "outside",
                     "status": "completed", "workflow_json": "{}",
                     "params_json": json.dumps({"positive_prompt": "a slow walk", "seed": "7"}),
                     "output_files": json.dumps([{"filename": video.name,
                                                  "library_path": str(video)}]),
                     **fields}])


def _made_here(db, prompt_id: str, filename: str, **fields) -> None:
    db.insert_rows([{"prompt_id": prompt_id, "workflow_name": "wan22_i2v", "workflow_version": "1",
                     "status": "completed", "workflow_json": "{}", "params_json": "{}",
                     "output_files": json.dumps([{"filename": filename, "subfolder": "video"}]),
                     **fields}])


def _seconds(seconds: float):
    return lambda _video: seconds


def test_the_phone_gets_each_ai_videos_record_under_the_place_it_plays_from(tmp_path):
    db, played_from = Database(tmp_path / "gallery.db"), _played_from(tmp_path)
    video = _filed(played_from.kino, "scene one.mp4")
    _outside(db, "o1", video, starred=1, recipe_category="alpha", watch_completions=3,
             watch_skips=0, watch_locks=0)

    records = records_for_the_phone(db.list_generations(), played_from, length_of=_seconds(5.0))

    assert records == {"videos/videos/kino/2D/AI/portrait/scene one.mp4": {
        "video": {"prompt": "a slow walk", "seed": "7", "action": "alpha", "type": "excerpt"},
        "favorite": True,
        "watch": {"completions": 3, "skips": 0, "locks": 0, "weight": 2.0}}}


def test_a_copy_of_a_video_made_here_carries_that_videos_record_and_genaus_copies_are_flicks(
        tmp_path):
    db, played_from = Database(tmp_path / "gallery.db"), _played_from(tmp_path)
    _made_here(db, "m1", "wan22_i2v_00001_.mp4")
    _filed(played_from.kino, "wan22_i2v_00001__topaz.mp4")
    _filed(played_from.genau, "wan22_i2v_00001_-audio.mp4")

    records = records_for_the_phone(db.list_generations(), played_from, length_of=_seconds(60.0))

    assert {place: record["video"]["type"] for place, record in records.items()} == {
        "videos/videos/kino/2D/AI/portrait/wan22_i2v_00001__topaz.mp4": "full_length",
        "videos/videos/genau/portrait/wan22_i2v_00001_-audio.mp4": "genau_flick"}
    assert {record["favorite"] for record in records.values()} == {False}


def test_a_non_ai_video_a_file_being_written_and_a_video_with_no_row_are_left_off(tmp_path):
    db, played_from = Database(tmp_path / "gallery.db"), _played_from(tmp_path)
    _made_here(db, "m1", "wan22_i2v_00001_.mp4")
    _filed(played_from.genau / "non_AI", "wan22_i2v_00001_.mp4")
    _filed(played_from.kino, "wan22_i2v_00001_.partial.mp4")
    _filed(played_from.kino, "no row of its own.mp4")
    _filed(played_from.kino, "notes.txt")

    assert records_for_the_phone(db.list_generations(), played_from, length_of=_seconds(5.0)) == {}


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _phone(tmp_path, db, clock) -> PhoneRecords:
    return PhoneRecords(db, write_to=tmp_path / "metadata" / FILE_NAME, played_from=_played_from(tmp_path),
                        clock=clock, length_of=_seconds(5.0))


def test_the_file_is_written_at_start_and_again_only_once_changes_have_settled(tmp_path):
    db, clock = Database(tmp_path / "gallery.db"), _Clock()
    phone = _phone(tmp_path, db, clock)
    at_start = phone.due()
    phone.write()
    _outside(db, "o1", _filed(_played_from(tmp_path).kino, "scene one.mp4"))

    just_after, clock.now = phone.due(), clock.now + PhoneRecords.QUIET_SECONDS
    settled = phone.due()

    assert (at_start, just_after, settled) == (True, False, True)


def test_nothing_changed_since_the_file_was_written_writes_nothing_again(tmp_path):
    db, clock = Database(tmp_path / "gallery.db"), _Clock()
    phone = _phone(tmp_path, db, clock)
    phone.write()
    clock.now += 10 * PhoneRecords.QUIET_SECONDS

    assert phone.due() is False


def test_the_file_is_swapped_in_whole_and_holds_every_record(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _outside(db, "o1", _filed(_played_from(tmp_path).kino, "scene one.mp4"))
    phone = _phone(tmp_path, db, _Clock())

    assert phone.write() == 1

    written = tmp_path / "metadata" / FILE_NAME
    assert list(json.loads(written.read_text(encoding="utf-8"))) == [
        "videos/videos/kino/2D/AI/portrait/scene one.mp4"]
    assert [path.name for path in written.parent.iterdir()] == [FILE_NAME]


def test_with_nowhere_to_write_nothing_is_ever_due(tmp_path):
    db = Database(tmp_path / "gallery.db")
    phone = PhoneRecords(db, write_to=None, played_from=_played_from(tmp_path), clock=_Clock(),
                         length_of=_seconds(5.0))

    assert phone.due() is False


def test_a_write_is_handed_off_once_and_not_again_until_it_is_done(tmp_path):
    db = Database(tmp_path / "gallery.db")
    phone, handed = _phone(tmp_path, db, _Clock()), []

    phone.write_when_due(lambda work, done: handed.append((work, done)))
    phone.write_when_due(lambda work, done: handed.append((work, done)))
    [(work, done)] = handed
    done(work())

    assert (tmp_path / "metadata" / FILE_NAME).is_file()


def test_a_preview_never_writes_the_phones_file_into_the_library(tmp_path):
    db = Database(tmp_path / "gallery.db")

    assert PhoneRecords.of_this_library(db, preview=True).due() is False


def test_a_videos_kind_is_read_off_its_running_time_when_none_is_given(tmp_path):
    db, played_from = Database(tmp_path / "gallery.db"), _played_from(tmp_path)
    video = write_mp4(played_from.kino / "portrait" / "scene one.mp4")
    _outside(db, "o1", video)
    phone = PhoneRecords(db, write_to=tmp_path / "metadata" / FILE_NAME, played_from=played_from)

    phone.write()

    [record] = json.loads((tmp_path / "metadata" / FILE_NAME).read_text(encoding="utf-8")).values()
    assert record["video"]["type"] == "excerpt"


def test_the_phones_file_goes_in_the_folder_evolver_keeps_the_videos_records_in(tmp_path, monkeypatch):
    checkout = tmp_path / "evolver"
    checkout.mkdir()
    (checkout / "evolver_contract.json").write_text(
        json.dumps({"library_record": {"folder": "videos/records"}}), encoding="utf-8")
    monkeypatch.setattr(warm_gun_records, "evolver_checkout", lambda: checkout)
    written = []
    monkeypatch.setattr(PhoneRecords, "__init__",
                        lambda self, db, **where: written.append(where) or None)

    PhoneRecords.of_this_library(Database(tmp_path / "gallery.db"), preview=False)

    assert written == [{"write_to": config.LIBRARY_ROOT / "videos" / "records" / FILE_NAME,
                        "played_from": PlayedFrom(config.LIBRARY_ROOT, config.KINO_UPSCALES_DIR,
                                           config.GENAU_DIR)}]
