from __future__ import annotations

from pathlib import Path

import pytest
from app_support.file_channel import read_key_values
from funestra.flick_list import RELOAD_FLICKS, flips_file_for
from funestra.funestra_verbs import NEXT, PREV, SHOW
from funestra.hud_kinds import HudKind, main_title
from funestra.main_hud import ModeHud
from funestra.modes import MainMode
from funestra.playlist import read_playlist

from origenerator.genau_flicks import AS_GENAU_STARTS, GenauFilters, GenauLeft
from origenerator.gui.standalone_genau import GenauSources, StandaloneGenau
from origenerator.osr2_motion_driver import Osr2MotionDriver
from tests.genau_support import FlicksLibrary, HeardBeat, looping_row
from tests.own_funestra_support import FakeProgram


class _Broker:
    def want(self, _on: bool) -> None:
        pass

    def ask(self, _verb: str) -> None:
        pass

    def send_position(self, _pos, _lead_ms) -> None:
        pass


class _Ticker:
    def __init__(self, _poll, _interval) -> None:
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class _Gallery:
    def __init__(self, favorites=()) -> None:
        self.favorites = set(favorites)
        self.trashed: list[str] = []
        self.unfavorited: list[str] = []
        self.flipped: list[tuple[str, bool]] = []

    def unfavorite(self, prompt_id: str) -> None:
        self.unfavorited.append(prompt_id)
        self.favorites.discard(prompt_id)

    def trash(self, prompt_id: str) -> None:
        self.trashed.append(prompt_id)


class Genau:
    def __init__(self, tmp_path: Path, rows, *, favorites=(), motion=None,
                 left: GenauLeft = AS_GENAU_STARTS) -> None:
        self.library = FlicksLibrary(rows, folder=tmp_path / "videos")
        self.library.folder.mkdir()
        for row in rows:
            self.library.file_of(row["prompt_id"]).write_bytes(b"made up")
        self.gallery = _Gallery(favorites)
        self.program = FakeProgram(tmp_path / "funestra")
        self.program.start()
        self.beat = HeardBeat()
        self.motion = motion
        self.genau = StandaloneGenau(self.program, GenauSources(
            library=lambda: self.library, is_favorite=self.gallery.favorites.__contains__,
            unfavorite=self.gallery.unfavorite, trash=self.gallery.trash,
            flip=lambda prompt_id, flipped: self.gallery.flipped.append((prompt_id, flipped)),
            name_of=lambda prompt_id: f"name of {prompt_id}", motion=motion, starts_with=left,
            flick_words=lambda: ("twirl", "twirls")), beat=self.beat)

    @property
    def launch(self):
        return self.program.genau

    def listed(self) -> list[str]:
        return [item.path.stem for item in read_playlist(self.launch.flicks)]

    def told(self) -> list[str]:
        file = self.launch.command
        return file.read_text(encoding="utf-8").splitlines() if file.exists() else []

    def up(self, *, path: Path | None = None) -> None:
        self.genau.show(path)
        self.program.channel.send(f"{SHOW} {MainMode.GENAU}")
        self.tick()

    def tick(self) -> None:
        self.program.tick()
        self.program.tick()
        self.genau.heard_from(read_key_values(self.launch.status))

    def on_screen(self) -> str:
        return Path(read_key_values(self.launch.status)["flick"]).stem


def _motion() -> Osr2MotionDriver:
    return Osr2MotionDriver(_Broker(), ticker_factory=_Ticker)


def test_shown_it_lists_every_looping_video_newest_first_and_tells_genau_to_read_them(tmp_path):
    genau = Genau(tmp_path, [looping_row("new"), looping_row("old")])

    genau.genau.show()

    assert genau.listed() == ["new", "old"]
    assert genau.program.sent[-1] == RELOAD_FLICKS


def test_first_shown_genau_is_put_back_as_it_was_left(tmp_path):
    genau = Genau(tmp_path, [looping_row("new"), looping_row("old")],
                  left=GenauLeft(latest=True, locked=False, seconds=9, flick="old"))

    genau.up()

    heard = genau.genau.heard
    assert genau.on_screen() == "old"
    assert (genau.genau.latest, heard.locked, heard.interval) == (True, False, 9)


def test_where_genau_stands_is_what_it_was_last_heard_to_be(tmp_path):
    genau = Genau(tmp_path, [looping_row("new"), looping_row("old")])
    genau.up(path=genau.library.file_of("old"))
    genau.genau.press("lock")
    genau.tick()

    assert genau.genau.left(showing=True) == GenauLeft(
        showing=True, locked=not AS_GENAU_STARTS.locked, flick="old")


def test_where_genau_stands_carries_the_order_he_picked(tmp_path):
    genau = Genau(tmp_path, [looping_row("new"), looping_row("old")])
    genau.up()

    genau.genau.press("latest")

    assert genau.genau.left(showing=True).latest


def test_genau_never_shown_stands_where_it_was_left(tmp_path):
    left = GenauLeft(filters=GenauFilters(favorites=True), latest=True, locked=False, seconds=9,
                     flick="old")
    genau = Genau(tmp_path, [looping_row("new"), looping_row("old")], left=left)

    assert genau.genau.left(showing=False) == left


def test_shown_on_a_flick_genau_plays_that_flick(tmp_path):
    genau = Genau(tmp_path, [looping_row("new"), looping_row("old")])

    genau.up(path=genau.library.file_of("old"))

    assert genau.on_screen() == "old"


def test_the_flips_its_items_record_go_with_the_list(tmp_path):
    genau = Genau(tmp_path, [looping_row("turned", flipped=True), looping_row("plain")])

    genau.genau.show()

    assert [item.path.stem for item in read_playlist(flips_file_for(genau.launch.flicks))] == [
        "turned"]


@pytest.mark.parametrize(("press", "verb"), [
    ("genau_prev_flick", PREV), ("genau_next_flick", NEXT),
    ("genau_flick_seconds_down", "FLICK_SECONDS_DOWN"),
    ("genau_flick_seconds_up", "FLICK_SECONDS_UP"),
    ("lock", "TOGGLE_LOCK"), ("latest", "LATEST"), ("shuffle", "SHUFFLE"),
])
def test_each_of_genaus_own_buttons_is_told_to_genau(tmp_path, press, verb):
    genau = Genau(tmp_path, [looping_row("one")])

    assert genau.genau.press(press)

    assert genau.told()[-1] == verb


def test_favorites_narrows_the_list_to_the_favorites(tmp_path):
    genau = Genau(tmp_path, [looping_row("liked", favorite=True), looping_row("plain")])

    genau.genau.press("favorites")

    assert (genau.listed(), genau.program.sent[-1]) == (["liked"], RELOAD_FLICKS)


def test_a_second_press_on_favorites_lets_every_flick_back(tmp_path):
    genau = Genau(tmp_path, [looping_row("liked", favorite=True), looping_row("plain")])
    genau.genau.press("favorites")

    genau.genau.press("favorites")

    assert genau.listed() == ["liked", "plain"]


def test_a_shape_left_out_takes_its_flicks_off_the_list_and_says_so(tmp_path):
    genau = Genau(tmp_path, [looping_row("tall"), looping_row("wide", shape="landscape")])

    genau.genau.press("orientation_landscape")

    assert genau.listed() == ["wide"]
    assert genau.program.sent[-1] == f"{RELOAD_FLICKS} Landscape only"


def test_reset_puts_genau_back_as_it_starts(tmp_path):
    genau = Genau(tmp_path, [looping_row("liked", favorite=True), looping_row("plain")])
    genau.genau.press("favorites")
    genau.genau.press("latest")

    genau.genau.press("genau_reset")

    assert genau.listed() == ["liked", "plain"]
    assert genau.told()[-2:] == ["LOCK_ON", "SHUFFLE"]
    assert (genau.genau.filters, genau.genau.latest) == (GenauFilters(), False)


def test_trash_sends_a_flick_that_is_no_favorite_to_the_apps_trash_and_moves_on(tmp_path):
    genau = Genau(tmp_path, [looping_row("doomed"), looping_row("kept")])
    genau.up(path=genau.library.file_of("doomed"))

    genau.genau.press("genau_trash_flick")

    assert genau.gallery.trashed == ["doomed"]
    assert "doomed" not in genau.listed()
    assert genau.told()[-1] == NEXT


def test_trash_on_a_favorite_only_unfavorites_it_and_moves_on(tmp_path):
    genau = Genau(tmp_path, [looping_row("liked"), looping_row("kept")], favorites={"liked"})
    genau.up(path=genau.library.file_of("liked"))

    genau.genau.press("genau_trash_flick")

    assert (genau.gallery.unfavorited, genau.gallery.trashed) == (["liked"], [])
    assert genau.told()[-1] == NEXT


def test_flip_is_recorded_on_the_flicks_item_and_told_to_genau(tmp_path):
    genau = Genau(tmp_path, [looping_row("one")])
    genau.up()

    genau.genau.press("genau_flip_ends")

    assert genau.gallery.flipped == [("one", True)]
    assert genau.told()[-1] == "FLIP_ENDS"


def test_a_flip_is_kept_on_the_list_written_after_it(tmp_path):
    genau = Genau(tmp_path, [looping_row("one")])
    genau.up()
    genau.genau.press("genau_flip_ends")

    genau.genau.press("favorites")
    genau.genau.press("favorites")

    assert [item.path.stem for item in read_playlist(flips_file_for(genau.launch.flicks))] == [
        "one"]


def test_the_speed_buttons_move_the_apps_own_osr2_speed(tmp_path):
    motion = _motion()
    genau = Genau(tmp_path, [looping_row("one")], motion=motion)
    before = motion.state.state.speed

    genau.genau.press("speed_up")

    assert motion.state.state.speed == before + 5


def test_a_press_genau_has_no_answer_for_is_left_to_the_slideshow(tmp_path):
    genau = Genau(tmp_path, [looping_row("one")])

    assert not genau.genau.press("cycle_seed")


def test_the_hud_follows_what_genau_says_of_its_flick(tmp_path):
    genau = Genau(tmp_path, [looping_row("one"), looping_row("two")], favorites={"one"})
    genau.up(path=genau.library.file_of("one"))
    genau.genau.press("lock")
    genau.genau.press("genau_flick_seconds_up")
    genau.tick()

    model = genau.genau.hud_model("portrait", None)

    assert (model.kind, model.facts.main_mode, model.facts.hosted) == (
        HudKind.SLIDESHOW, MainMode.GENAU, False)
    assert (model.facts.locked, model.facts.pace_s, model.facts.favorite) == (False, 11, True)
    assert (model.facts.flick_one, model.facts.flick_many) == ("twirl", "twirls")
    assert model.item_name == "name of one"
    assert model.title == main_title(model.facts, ModeHud())


def test_genau_as_it_starts_has_nothing_to_reset(tmp_path):
    genau = Genau(tmp_path, [looping_row("one")])
    genau.up()

    assert genau.genau.hud_model("portrait", None).facts.nothing_to_reset


def test_paused_genau_is_told_to_pause_and_its_flag_is_up(tmp_path):
    genau = Genau(tmp_path, [looping_row("one")])

    genau.genau.set_paused(True)

    assert genau.told()[-1] == "PAUSE"
    assert genau.launch.paused.read_text(encoding="utf-8") == "1"


def test_let_go_it_is_told_to_play(tmp_path):
    genau = Genau(tmp_path, [looping_row("one")])
    genau.genau.set_paused(True)

    genau.genau.set_paused(False)

    assert genau.told()[-1] == "RESUME"


def test_while_it_shows_and_the_osr2_is_driven_it_is_told_the_beat_and_its_pace(tmp_path):
    motion = _motion()
    genau = Genau(tmp_path, [looping_row("one")], motion=motion)
    motion.start()

    genau.genau.follow_the_beat(showing=True)

    assert genau.beat.said == ["drive 1", f"bpm {motion.state.bpm:g}"]


def test_a_new_speed_is_said_as_a_new_beat(tmp_path):
    motion = _motion()
    genau = Genau(tmp_path, [looping_row("one")], motion=motion)
    motion.start()
    genau.genau.follow_the_beat(showing=True)

    motion.adjust_speed(5)
    genau.genau.follow_the_beat(showing=True)

    assert genau.beat.said[-1] == f"bpm {motion.state.bpm:g}"


def test_each_time_the_motion_comes_round_genau_is_told_to_meet_it(tmp_path):
    motion = _motion()
    genau = Genau(tmp_path, [looping_row("one")], motion=motion)
    motion.start()
    genau.genau.follow_the_beat(showing=True)

    genau.genau.loop_came_round()

    assert genau.beat.said[-1] == "sync"


def test_with_kino_showing_it_follows_no_beat(tmp_path):
    motion = _motion()
    genau = Genau(tmp_path, [looping_row("one")], motion=motion)
    motion.start()
    genau.genau.follow_the_beat(showing=True)

    genau.genau.follow_the_beat(showing=False)
    genau.genau.loop_came_round()

    assert genau.beat.said[-1] == "drive 0"


def test_with_the_osr2_not_driven_genau_loops_on_its_own_at_the_speed_bars_pace(tmp_path):
    motion = _motion()
    genau = Genau(tmp_path, [looping_row("one")], motion=motion)

    genau.genau.follow_the_beat(showing=True)

    assert genau.beat.said == ["drive 0"]
    assert genau.told()[-1] == f"SPEED {motion.state.state.speed}"


def test_told_to_pause_twice_it_is_told_once(tmp_path):
    genau = Genau(tmp_path, [looping_row("one")])
    genau.genau.set_paused(True)

    genau.genau.set_paused(True)

    assert genau.told() == ["PAUSE"]


def test_with_no_osr2_controls_it_follows_no_beat_and_is_told_no_speed(tmp_path):
    genau = Genau(tmp_path, [looping_row("one")])

    genau.genau.follow_the_beat(showing=True)

    assert (genau.beat.said, genau.told()) == (["drive 0"], [])


def test_closed_while_it_follows_the_beat_it_lets_go_of_it(tmp_path):
    motion = _motion()
    genau = Genau(tmp_path, [looping_row("one")], motion=motion)
    motion.start()
    genau.genau.follow_the_beat(showing=True)

    genau.genau.close()

    assert genau.beat.said[-2:] == ["drive 0", "closed"]


def test_closed_while_it_follows_none_it_only_closes(tmp_path):
    genau = Genau(tmp_path, [looping_row("one")])

    genau.genau.close()

    assert genau.beat.said == ["closed"]


def test_trash_with_no_flick_up_yet_does_nothing(tmp_path):
    genau = Genau(tmp_path, [looping_row("one")])

    genau.genau.press("genau_trash_flick")

    assert (genau.gallery.trashed, genau.told()) == ([], [])


def test_flip_with_no_flick_up_yet_records_nothing(tmp_path):
    genau = Genau(tmp_path, [looping_row("one")])

    genau.genau.press("genau_flip_ends")

    assert genau.gallery.flipped == []


def test_before_genau_says_anything_its_status_reads_as_nothing(tmp_path):
    genau = Genau(tmp_path, [looping_row("one")])

    assert genau.genau.read_status() == {}


def test_once_genau_is_up_its_status_names_its_flick(tmp_path):
    genau = Genau(tmp_path, [looping_row("one")])
    genau.up()

    assert Path(genau.genau.read_status()["flick"]).stem == "one"
