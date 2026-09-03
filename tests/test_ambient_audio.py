"""The audio bed — which clip each voice takes, and the players that run them."""

from pathlib import Path

import pytest
from PyQt6.QtMultimedia import QMediaPlayer

from origenerator.ambient_audio import AmbientRotation, find_clips
from origenerator.config import ambient_audio_dir
from origenerator.gui.ambient_audio import AmbientAudio


def _clips(*names):
    return [Path(name) for name in names]


def _in_order(order):
    """A ``shuffle`` that lays every voice's pass out as *order* — so a test can
    name exactly which clip each voice takes next."""
    def shuffle(target):
        target[:] = list(order)
    return shuffle


# --- find_clips ------------------------------------------------------------

def test_find_clips_reads_videos_at_any_depth_in_a_stable_order(tmp_path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "b.mp4").touch()
    (tmp_path / "a.mp4").touch()
    (tmp_path / "nested" / "c.webm").touch()

    assert [p.name for p in find_clips(tmp_path)] == ["a.mp4", "b.mp4", "c.webm"]


def test_find_clips_ignores_files_that_are_not_videos(tmp_path):
    (tmp_path / "clip.mp4").touch()
    (tmp_path / "cover.png").touch()
    (tmp_path / "notes.txt").touch()

    assert [p.name for p in find_clips(tmp_path)] == ["clip.mp4"]


@pytest.mark.parametrize("folder", [None, "does/not/exist"])
def test_find_clips_answers_a_missing_folder_with_silence(tmp_path, folder):
    # The committed example overlay names a folder that isn't there, so a public
    # checkout has to get an empty set rather than an exception.
    target = None if folder is None else tmp_path / folder
    assert find_clips(target) == []


# --- the overlay's folder --------------------------------------------------

def test_a_relative_ambient_folder_hangs_off_the_suite_root():
    resolved = ambient_audio_dir(
        {"suite_root": "C:/root", "ambient_audio_dir": "videos/clips"})
    assert resolved == Path("C:/root") / "videos/clips"


def test_an_absolute_ambient_folder_is_taken_as_given():
    resolved = ambient_audio_dir(
        {"suite_root": "C:/root", "ambient_audio_dir": "D:/elsewhere/clips"})
    assert resolved == Path("D:/elsewhere/clips")


def test_an_overlay_naming_no_ambient_folder_gives_none():
    assert ambient_audio_dir({"suite_root": "C:/root"}) is None


# --- the rotation ----------------------------------------------------------

def test_each_voice_walks_its_own_pass_independently():
    rotation = AmbientRotation(_clips("a", "b", "c"), 2, shuffle=_in_order([0, 1, 2]))

    # Voice 0 walks ahead; voice 1 is still at the start of its own pass, and
    # takes the first clip voice 0 is not holding.
    assert rotation.next_clip(0) == Path("a")
    assert rotation.next_clip(0) == Path("b")
    assert rotation.next_clip(1) == Path("a")


def test_a_voice_skips_a_clip_another_voice_has_on_air():
    rotation = AmbientRotation(_clips("a", "b", "c"), 2, shuffle=_in_order([0, 1, 2]))

    assert rotation.next_clip(0) == Path("a")
    assert rotation.next_clip(1) == Path("b")  # "a" is taken, so it steps past it


def test_finishing_a_clip_frees_it_for_the_other_voices():
    rotation = AmbientRotation(_clips("a", "b", "c"), 2, shuffle=_in_order([0, 1, 2]))
    rotation.next_clip(0)                       # voice 0 holds "a"
    rotation.next_clip(1)                       # voice 1 steps past it to "b"

    assert rotation.next_clip(0) == Path("c")   # voice 0 moves on, letting "a" go
    assert rotation.next_clip(1) == Path("a")   # so "a" is available again


def test_a_pass_reshuffles_when_it_runs_out():
    passes = [[0, 1], [1, 0]]
    rotation = AmbientRotation(
        _clips("a", "b"), 1, shuffle=lambda target: target.__setitem__(
            slice(None), passes.pop(0) if passes else [0, 1]),
    )
    assert rotation.next_clip(0) == Path("a")
    assert rotation.next_clip(0) == Path("b")
    # The pass is spent, so a fresh (re-shuffled) one starts.
    assert rotation.next_clip(0) == Path("b")


def test_more_voices_than_clips_doubles_up_rather_than_hanging():
    # One clip and three voices: the no-doubling rule can't be honored, and the
    # rotation has to hand it out anyway rather than loop forever looking.
    rotation = AmbientRotation(_clips("only"), 3, shuffle=_in_order([0]))
    assert [rotation.next_clip(v) for v in range(3)] == [Path("only")] * 3


def test_an_empty_clip_set_hands_out_nothing():
    rotation = AmbientRotation([], 3)
    assert [rotation.next_clip(v) for v in range(3)] == [None, None, None]


# --- the players -----------------------------------------------------------

class FakePlayer:
    """Enough of QMediaPlayer to record what the bed asks of one voice."""

    def __init__(self):
        self.sources = []
        self.play_count = 0
        self.stopped = 0
        self.active_video_track = 0
        self._on_status = None

    @property
    def mediaStatusChanged(self):
        player = self

        class _Signal:
            def connect(self, slot):
                player._on_status = slot

        return _Signal()

    def setSource(self, url):
        self.sources.append(url.toLocalFile())

    def play(self):
        self.play_count += 1

    def stop(self):
        self.stopped += 1

    def setActiveVideoTrack(self, track):
        self.active_video_track = track

    def load(self):
        """What Qt does once this voice's clip is open and its tracks are known."""
        self._on_status(QMediaPlayer.MediaStatus.LoadedMedia)

    def finish(self):
        """What Qt does when this voice's clip plays through."""
        self._on_status(QMediaPlayer.MediaStatus.EndOfMedia)


def _bed(tmp_path, clip_names=("a.mp4", "b.mp4", "c.mp4", "d.mp4"), voices=3):
    for name in clip_names:
        (tmp_path / name).touch()
    made = []

    def make_player():
        made.append(FakePlayer())
        return made[-1]

    return AmbientAudio(clips_dir=tmp_path, voices=voices,
                        make_player=make_player), made


def test_starting_plays_one_clip_per_voice(qtbot, tmp_path):
    bed, players = _bed(tmp_path)

    bed.start()

    assert len(players) == 3
    assert [p.play_count for p in players] == [1, 1, 1]
    # Three different clips, so the room hears three sources rather than an echo.
    playing = [p.sources[-1] for p in players]
    assert len(set(playing)) == 3


def test_a_loaded_clip_has_its_video_track_deselected(qtbot, tmp_path):
    # Nothing renders these frames, so decoding them is pure waste — it costs
    # about half of what the bed asks of a CPU that is also running ComfyUI.
    bed, players = _bed(tmp_path)
    bed.start()

    players[1].load()

    assert players[1].active_video_track == -1
    assert players[0].active_video_track == 0  # only the loaded voice is touched


def test_a_late_load_after_stopping_touches_nothing(qtbot, tmp_path):
    bed, players = _bed(tmp_path)
    bed.start()
    bed.stop()

    players[0].load()  # a status change arriving out of the teardown

    assert players[0].active_video_track == 0


def test_a_finished_clip_moves_only_its_own_voice_on(qtbot, tmp_path):
    bed, players = _bed(tmp_path)
    bed.start()
    before = [p.sources[-1] for p in players]

    players[1].finish()

    assert players[1].sources[-1] != before[1]  # that voice took a new clip
    assert players[1].play_count == 2
    assert [players[0].sources[-1], players[2].sources[-1]] == [before[0], before[2]]
    assert [players[0].play_count, players[2].play_count] == [1, 1]


def test_stopping_silences_and_releases_every_voice(qtbot, tmp_path):
    bed, players = _bed(tmp_path)
    bed.start()

    bed.stop()

    assert [p.stopped for p in players] == [1, 1, 1]
    assert [p.sources[-1] for p in players] == ["", "", ""]  # the source is let go


def test_a_late_end_of_clip_after_stopping_starts_nothing(qtbot, tmp_path):
    bed, players = _bed(tmp_path)
    bed.start()
    bed.stop()
    plays_at_stop = [p.play_count for p in players]

    players[0].finish()  # a status change arriving out of the teardown

    assert [p.play_count for p in players] == plays_at_stop


def test_starting_twice_does_not_double_the_voices(qtbot, tmp_path):
    bed, players = _bed(tmp_path)
    bed.start()
    bed.start()
    assert len(players) == 3


def test_a_folder_with_no_clips_stays_silent(qtbot, tmp_path):
    # A public checkout's example overlay points at a folder that isn't there:
    # the switch may be flipped, and nothing happens.
    bed, players = _bed(tmp_path, clip_names=())

    bed.start()

    assert players == []
    bed.stop()  # and stopping an empty bed is harmless


def test_the_bed_can_restart_after_being_stopped(qtbot, tmp_path):
    bed, players = _bed(tmp_path)
    bed.start()
    bed.stop()

    bed.start()

    assert len(players) == 6  # a fresh set of three
    assert [p.play_count for p in players[3:]] == [1, 1, 1]
