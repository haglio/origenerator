"""Origenerator Radio: the videos it deals out, Standalone's switch, and a session's Funestras' stations."""
from __future__ import annotations

from pathlib import Path

import pytest
from funestra import mpv_engine
from funestra.radio import radio_file_for, read_radio

from origenerator import funestras_engine
from origenerator import radio as radio_module
from origenerator.config import radio_dir
from origenerator.radio import OrigeneratorRadio, deal_stations, deal_to_the_funestras, find_videos


def _videos(*names):
    return [Path(name) for name in names]


def _kept_in_order(target):
    """A shuffle that leaves the videos as they were, so a test can name what
    each station is dealt."""


def _reversed(target):
    target.reverse()


# --- the videos -------------------------------------------------------------

def test_find_clips_reads_videos_at_any_depth_in_a_stable_order(tmp_path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "b.mp4").touch()
    (tmp_path / "a.mp4").touch()
    (tmp_path / "nested" / "c.webm").touch()

    assert [p.name for p in find_videos(tmp_path)] == ["a.mp4", "b.mp4", "c.webm"]


def test_find_clips_ignores_files_that_are_not_videos(tmp_path):
    (tmp_path / "clip.mp4").touch()
    (tmp_path / "cover.png").touch()
    (tmp_path / "notes.txt").touch()

    assert [p.name for p in find_videos(tmp_path)] == ["clip.mp4"]


@pytest.mark.parametrize("folder", [None, "does/not/exist"])
def test_find_clips_answers_a_missing_folder_with_silence(tmp_path, folder):
    # The committed example settings name a folder that isn't there, so a public
    # checkout has to get an empty set rather than an exception.
    target = None if folder is None else tmp_path / folder
    assert find_videos(target) == []


# --- the folder the settings name ------------------------------------------

def test_a_relative_radio_folder_hangs_off_the_library_root():
    resolved = radio_dir({"library_root": "C:/root", "ambient_audio_dir": "videos/clips"})
    assert resolved == Path("C:/root") / "videos/clips"


def test_an_absolute_radio_folder_is_taken_as_given():
    resolved = radio_dir({"library_root": "C:/root", "ambient_audio_dir": "D:/elsewhere/clips"})
    assert resolved == Path("D:/elsewhere/clips")


def test_settings_naming_no_radio_folder_give_none():
    assert radio_dir({"library_root": "C:/root"}) is None


# --- dealing the stations --------------------------------------------------

def test_each_station_is_dealt_its_own_share_of_the_videos():
    stations = deal_stations(_videos("a", "b", "c", "d", "e", "f", "g"), 3,
                             shuffle=_kept_in_order)

    assert stations == [_videos("a", "d", "g"), _videos("b", "e"), _videos("c", "f")]


def test_the_clips_are_shuffled_before_they_are_dealt():
    stations = deal_stations(_videos("a", "b", "c"), 3, shuffle=_reversed)

    assert stations == [_videos("c"), _videos("b"), _videos("a")]


def test_fewer_clips_than_stations_still_gives_every_station_something_to_play():
    stations = deal_stations(_videos("only", "other"), 3, shuffle=_kept_in_order)

    assert stations == [_videos("only", "other"), _videos("other", "only"),
                        _videos("only", "other")]


def test_no_clips_deal_no_stations():
    assert deal_stations([], 3) == []


# --- Standalone's switch ---------------------------------------------------

class FakeStation:
    def __init__(self, videos) -> None:
        self.videos = list(videos)
        self.heard_at: int | None = None
        self.paused = False
        self.closed = False

    def tune(self, level: int | None) -> None:
        self.heard_at = level

    def set_paused(self, paused: bool) -> None:
        self.paused = paused

    def close(self) -> None:
        self.closed = True


def _radio(tmp_path, video_names=("a.mp4", "b.mp4", "c.mp4", "d.mp4"), stations=3):
    for name in video_names:
        (tmp_path / name).touch()
    opened: list[FakeStation] = []

    def open_station(videos):
        opened.append(FakeStation(videos))
        return opened[-1]

    return OrigeneratorRadio(videos_dir=tmp_path, stations=stations,
                             open_station=open_station), opened


def test_turning_the_radio_on_tunes_in_every_station_each_on_clips_of_its_own(tmp_path):
    radio, stations = _radio(tmp_path)

    radio.start()

    assert len(stations) == 3
    assert [station.heard_at for station in stations] == [100, 100, 100]
    dealt = [video for station in stations for video in station.videos]
    assert len(dealt) == len(set(dealt)) == 4


def test_turning_it_off_lets_every_station_go(tmp_path):
    radio, stations = _radio(tmp_path)
    radio.start()

    radio.stop()

    assert [station.closed for station in stations] == [True, True, True]


def test_turning_it_on_twice_does_not_double_the_stations(tmp_path):
    radio, stations = _radio(tmp_path)

    radio.start()
    radio.start()

    assert len(stations) == 3


def test_a_folder_with_no_clips_stays_silent(tmp_path):
    # A public checkout's example settings point at a folder that isn't there:
    # the switch may be flipped, and nothing happens.
    radio, stations = _radio(tmp_path, video_names=())

    radio.start()

    assert stations == []
    radio.stop()  # and turning off a silent radio is harmless


def test_turned_on_again_it_is_dealt_a_fresh_set_of_stations(tmp_path):
    radio, stations = _radio(tmp_path)
    radio.start()
    radio.stop()

    radio.start()

    assert len(stations) == 6
    assert [station.heard_at for station in stations[3:]] == [100, 100, 100]


def test_a_station_that_will_not_open_leaves_the_radio_silent_and_says_why(tmp_path, caplog):
    for name in ("a.mp4", "b.mp4"):
        (tmp_path / name).touch()
    opened: list[FakeStation] = []

    def open_station(videos):
        if opened:
            raise OSError("The engine (libmpv) could not be loaded.")
        opened.append(FakeStation(videos))
        return opened[-1]

    radio = OrigeneratorRadio(videos_dir=tmp_path, stations=2, open_station=open_station)

    radio.start()

    assert [station.closed for station in opened] == [True]
    assert "could not be loaded" in caplog.text


def test_a_station_is_one_of_the_funestras_own_opened_once_their_engine_is_found(monkeypatch):
    asked = []
    monkeypatch.setattr(funestras_engine, "offer_the_copy_beside_the_checkouts",
                        lambda: asked.append("the engine found"))
    monkeypatch.setattr(mpv_engine.MpvStation, "opened",
                        classmethod(lambda cls, videos: asked.append(list(videos))))

    radio_module._open_a_station(_videos("a.mp4", "b.mp4"))

    assert asked == ["the engine found", _videos("a.mp4", "b.mp4")]


# --- the Standalone Slideshow ---------------------------------------------

def test_a_radio_a_slideshow_holds_is_heard_while_its_image_is_up_at_its_level(tmp_path):
    radio, stations = _radio(tmp_path)
    radio.start()
    held = radio.held_by_a_slideshow()

    held.tick(image=True, level=40, paused=False)

    assert [station.heard_at for station in stations] == [40, 40, 40]


def test_a_radio_a_slideshow_lets_go_is_heard_at_full_level_again(tmp_path):
    radio, stations = _radio(tmp_path)
    radio.start()
    held = radio.held_by_a_slideshow()
    held.tick(image=False, level=40, paused=False)

    held.close()

    assert [station.heard_at for station in stations] == [100, 100, 100]


def test_a_radio_a_slideshow_holds_still_holds_still_with_the_room(tmp_path):
    radio, stations = _radio(tmp_path)
    radio.start()
    held = radio.held_by_a_slideshow()

    radio.set_frozen(True)
    held.tick(image=True, level=40, paused=False)

    assert [station.paused for station in stations] == [True, True, True]


# --- the room's pause ------------------------------------------------------

def test_a_frozen_room_holds_every_station_and_lets_them_all_play_again(tmp_path):
    radio, stations = _radio(tmp_path)
    radio.start()

    radio.set_frozen(True)
    assert [station.paused for station in stations] == [True, True, True]

    radio.set_frozen(False)
    assert [station.paused for station in stations] == [False, False, False]


def test_a_radio_turned_on_in_a_frozen_room_waits_for_it_to_play(tmp_path):
    radio, stations = _radio(tmp_path)
    radio.set_frozen(True)

    radio.start()
    assert [station.paused for station in stations] == [True, True, True]

    radio.set_frozen(False)
    assert [station.paused for station in stations] == [False, False, False]


# --- a session's Funestras -------------------------------------------------

def test_each_funestra_is_dealt_stations_of_its_own_beside_its_playlist(tmp_path):
    videos = tmp_path / "clips"
    videos.mkdir()
    for index in range(7):
        (videos / f"clip{index}.mp4").touch()
    playlists = {"portrait": tmp_path / "portrait_playlist.tsv",
                 "landscape": tmp_path / "landscape_playlist.tsv"}

    written = deal_to_the_funestras(playlists, videos_dir=videos, stations=3,
                                    shuffle=_kept_in_order)

    assert written == [radio_file_for(playlist) for playlist in playlists.values()]
    portrait, landscape = (read_radio(path) for path in written)
    assert (len(portrait), len(landscape)) == (3, 3)
    heard_on_one = {video for station in portrait for video in station}
    heard_on_the_other = {video for station in landscape for video in station}
    assert heard_on_one.isdisjoint(heard_on_the_other)
    assert len(heard_on_one | heard_on_the_other) == 7


def test_a_folder_with_no_clips_deals_each_funestra_a_radio_with_no_stations(tmp_path):
    playlists = {"portrait": tmp_path / "portrait_playlist.tsv"}
    radio_file_for(playlists["portrait"]).write_text("0\tstale.mp4\n", encoding="utf-8")

    written = deal_to_the_funestras(playlists, videos_dir=tmp_path / "nowhere", stations=3)

    assert read_radio(written[0]) == []
