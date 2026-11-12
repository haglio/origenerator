from __future__ import annotations

import json
import threading

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
    return lambda _video, _row=None: seconds


def test_the_phone_gets_each_ai_videos_record_under_the_place_it_plays_from(tmp_path):
    db, played_from = Database(tmp_path / "gallery.db"), _played_from(tmp_path)
    video = _filed(played_from.kino, "scene one.mp4")
    _outside(db, "o1", video, starred=1, recipe_category="alpha", watch_completions=3,
             watch_skips=0, watch_locks=0)

    records = records_for_the_phone(db.list_generations(), played_from, length_of=_seconds(5.0))

    assert records == {"videos/videos/kino/2D/AI/portrait/scene one.mp4": {
        "video": {"prompt": "a slow walk", "seed": "7", "action": "alpha",
                  "orientation": "portrait", "type": "excerpt"},
        "favorite": True,
        "watch": {"completions": 3, "skips": 0, "locks": 0, "weight": 2.0}}}


def test_a_copy_of_a_video_made_here_carries_that_videos_record_and_genaus_copies_are_flicks(
        tmp_path):
    db, played_from = Database(tmp_path / "gallery.db"), _played_from(tmp_path)
    _made_here(db, "m1", "wan22_i2v_00001_.mp4")
    _filed(played_from.kino, "wan22_i2v_00001__topaz.mp4")
    _filed(played_from.genau / "loops" / "2D" / "AI", "wan22_i2v_00001_-audio.mp4")
    _filed(played_from.genau / "loops" / "VR", "wan22_i2v_00001_-audio.mp4")

    records = records_for_the_phone(db.list_generations(), played_from, length_of=_seconds(60.0))

    assert {place: record["video"]["type"] for place, record in records.items()} == {
        "videos/videos/kino/2D/AI/portrait/wan22_i2v_00001__topaz.mp4": "full_length",
        "videos/videos/genau/loops/2D/AI/portrait/wan22_i2v_00001_-audio.mp4": "genau_flick"}
    assert {record["favorite"] for record in records.values()} == {False}


def test_a_non_ai_video_a_vr_one_a_file_being_written_and_a_video_with_no_row_are_left_off(tmp_path):
    db, played_from = Database(tmp_path / "gallery.db"), _played_from(tmp_path)
    _made_here(db, "m1", "wan22_i2v_00001_.mp4")
    _filed(played_from.genau / "loops" / "2D" / "non_AI", "wan22_i2v_00001_.mp4")
    _filed(played_from.genau / "loops" / "VR", "wan22_i2v_00001_.mp4")
    _filed(played_from.kino, "wan22_i2v_00001_.partial.mp4")
    _filed(played_from.kino, "no row of its own.mp4")
    _filed(played_from.kino, "notes.txt")

    assert records_for_the_phone(db.list_generations(), played_from, length_of=_seconds(5.0)) == {}


class _Later:
    def __init__(self):
        self.waiting = []

    def __call__(self, seconds, work):
        entry = [seconds, work]
        self.waiting.append(entry)
        return lambda: self.waiting.remove(entry)

    def run(self):
        waiting, self.waiting = self.waiting, []
        for _seconds, work in waiting:
            work()


def _phone(tmp_path, db, later=None, measure=None) -> PhoneRecords:
    return PhoneRecords(db, write_to=tmp_path / "metadata" / FILE_NAME,
                        played_from=_played_from(tmp_path), later=later or _Later(),
                        measure=measure or _seconds(5.0))


def _written(tmp_path) -> dict:
    return json.loads((tmp_path / "metadata" / FILE_NAME).read_text(encoding="utf-8"))


def test_the_file_is_written_at_once_when_the_app_starts_watching(tmp_path):
    db, later = Database(tmp_path / "gallery.db"), _Later()
    _outside(db, "o1", _filed(_played_from(tmp_path).kino, "scene one.mp4"))

    _phone(tmp_path, db, later).watch()

    assert [seconds for seconds, _work in later.waiting] == [0]
    later.run()
    assert list(_written(tmp_path)) == ["videos/videos/kino/2D/AI/portrait/scene one.mp4"]


def test_a_change_to_the_gallery_writes_the_file_again_once_changes_have_settled(tmp_path):
    db, later = Database(tmp_path / "gallery.db"), _Later()
    _phone(tmp_path, db, later).watch()
    later.run()

    _outside(db, "o1", _filed(_played_from(tmp_path).kino, "scene one.mp4"))
    db.set_generation_favorite("o1", True)

    assert [seconds for seconds, _work in later.waiting] == [PhoneRecords.QUIET_SECONDS]
    later.run()
    assert [record["favorite"] for record in _written(tmp_path).values()] == [True]


def test_the_file_is_swapped_in_whole_and_nothing_is_left_beside_it(tmp_path):
    db = Database(tmp_path / "gallery.db")
    _outside(db, "o1", _filed(_played_from(tmp_path).kino, "scene one.mp4"))

    assert _phone(tmp_path, db).write() == 1

    assert [path.name for path in (tmp_path / "metadata").iterdir()] == [FILE_NAME]


def test_with_nowhere_to_write_watching_writes_nothing(tmp_path):
    db, later = Database(tmp_path / "gallery.db"), _Later()

    PhoneRecords(db, write_to=None, played_from=_played_from(tmp_path), later=later).watch()
    db.insert_rows([])

    assert later.waiting == []


def test_a_preview_never_writes_the_phones_file_into_the_library(tmp_path):
    later = _Later()

    PhoneRecords.of_this_library(Database(tmp_path / "gallery.db"), preview=True, later=later).watch()

    assert later.waiting == []


def test_a_videos_running_time_is_measured_once_ever_and_kept_on_its_row(tmp_path):
    db, later, measured = Database(tmp_path / "gallery.db"), _Later(), []
    _outside(db, "o1", _filed(_played_from(tmp_path).kino, "scene one.mp4"))
    phone = _phone(tmp_path, db, later, measure=lambda video: measured.append(video.name) or 4.0)
    phone.watch()

    later.run()
    phone.write()

    assert (measured, db.get_generation("o1")["video_seconds"], later.waiting) == (
        ["scene one.mp4"], 4.0, [])


def test_a_running_time_the_gallery_holds_is_never_measured_and_a_genau_copy_never_needs_one(
        tmp_path):
    db, played_from = Database(tmp_path / "gallery.db"), _played_from(tmp_path)
    _outside(db, "o1", _filed(played_from.kino, "scene one.mp4"), video_seconds=600.0)
    _made_here(db, "m1", "wan22_i2v_00001_.mp4")
    _filed(played_from.genau / "loops" / "2D" / "AI", "wan22_i2v_00001_-audio.mp4")

    def never(video):
        raise AssertionError(f"{video.name} has no need to be measured")

    _phone(tmp_path, db, measure=never).write()

    assert sorted(record["video"]["type"] for record in _written(tmp_path).values()) == [
        "full_length", "genau_flick"]


def test_a_video_whose_running_time_cannot_be_read_is_full_length(tmp_path):
    db, played_from = Database(tmp_path / "gallery.db"), _played_from(tmp_path)
    video = write_mp4(played_from.kino / "portrait" / "scene one.mp4")
    _outside(db, "o1", video)
    (played_from.kino / "portrait" / "scene two.mp4").write_bytes(b"not really a video")
    _outside(db, "o2", played_from.kino / "portrait" / "scene two.mp4")

    PhoneRecords(db, write_to=tmp_path / "metadata" / FILE_NAME, played_from=played_from).write()

    assert {place.rsplit("/", 1)[-1]: record["video"]["type"]
            for place, record in _written(tmp_path).items()} == {
        "scene one.mp4": "excerpt", "scene two.mp4": "full_length"}


def test_with_no_records_folder_in_the_library_there_is_nowhere_to_write(tmp_path, monkeypatch):
    checkout = tmp_path / "evolver"
    checkout.mkdir()
    (checkout / "evolver_contract.json").write_text(
        json.dumps({"library_record": {"folder": "no such folder"}}), encoding="utf-8")
    monkeypatch.setattr(warm_gun_records, "evolver_checkout", lambda: checkout)
    later = _Later()

    PhoneRecords.of_this_library(Database(tmp_path / "gallery.db"), preview=False,
                                 later=later).watch()

    assert later.waiting == []


def test_the_phones_file_goes_in_the_folder_evolver_keeps_the_videos_records_in(tmp_path, monkeypatch):
    checkout = tmp_path / "evolver"
    checkout.mkdir()
    (checkout / "evolver_contract.json").write_text(
        json.dumps({"library_record": {"folder": "videos/records"}}), encoding="utf-8")
    monkeypatch.setattr(warm_gun_records, "evolver_checkout", lambda: checkout)
    monkeypatch.setattr(warm_gun_records, "records_folder",
                        lambda _checkout, _root: tmp_path / "videos" / "records")
    (tmp_path / "videos" / "records").mkdir(parents=True)
    written = []
    monkeypatch.setattr(PhoneRecords, "__init__",
                        lambda self, db, **where: written.append(where) or None)

    PhoneRecords.of_this_library(Database(tmp_path / "gallery.db"), preview=False)

    assert written == [{"write_to": tmp_path / "videos" / "records" / FILE_NAME,
                        "played_from": PlayedFrom(config.LIBRARY_ROOT, config.KINO_UPSCALES_DIR,
                                                  config.GENAU_DIR)}]


def test_with_nowhere_to_write_a_write_writes_nothing(tmp_path):
    db = Database(tmp_path / "gallery.db")

    assert PhoneRecords(db, write_to=None, played_from=_played_from(tmp_path)).write() == 0


def test_left_to_itself_the_first_write_runs_on_a_thread_of_its_own(tmp_path):
    db, written_on = Database(tmp_path / "gallery.db"), []
    done = threading.Event()
    phone = PhoneRecords(db, write_to=tmp_path / "metadata" / FILE_NAME,
                         played_from=_played_from(tmp_path))
    phone.write = lambda: (written_on.append(threading.current_thread()), done.set())

    phone.watch()

    assert done.wait(timeout=10)
    assert written_on != [threading.current_thread()]
