from __future__ import annotations

from pathlib import Path

import pytest
from funestra.hud_kinds import HudKind, hud_rows
from funestra.modes import MainMode
from funestra.satellite_hud import parse_hud

from origenerator.gui.slideshow_wiring import SlideshowActions
from origenerator.gui.standalone_genau import GenauSources
from tests.genau_support import FlicksLibrary, looping_row
from tests.motion_doubles import FakeMotion
from tests.own_funestra_support import standalone

SHAPE = "portrait"


class _Gallery:
    def __init__(self) -> None:
        self.trashed: list[str] = []

    def trash(self, prompt_id: str) -> None:
        self.trashed.append(prompt_id)


def _slides(folder: Path, names) -> list[tuple]:
    folder.mkdir(parents=True, exist_ok=True)
    slides = []
    for name in names:
        (folder / name).write_bytes(b"made up")
        slides.append((str(folder / name), "video", name, None))
    return slides


def _shown(tmp_path, *, rows=("one", "two"), items=("a.mp4", "b.mp4", "c.mp4"), actions=None):
    library = FlicksLibrary([looping_row(name) for name in rows], folder=tmp_path / "flicks")
    library.folder.mkdir()
    for name in rows:
        library.file_of(name).write_bytes(b"made up")
    gallery = _Gallery()
    up = standalone(_slides(tmp_path / "slides", items), shape=SHAPE, actions=actions,
                    genau=GenauSources(library=lambda: library, is_favorite=lambda _id: False,
                                       unfavorite=lambda _id: None, trash=gallery.trash,
                                       flip=lambda _id, _flipped: None,
                                       name_of=lambda prompt_id: prompt_id,
                                       motion=FakeMotion(),
                                       flick_words=lambda: ("twirl", "twirls")))
    up.shown.wear_the_hud(SHAPE)
    up.tick_the_funestra()
    return up, library, gallery


def _flick_on_screen(up) -> str:
    up.tick_the_funestra()
    up.tick_the_funestra()
    up.shown.channel.status()
    return up.genau.prompt_id_on_screen()


def _hud(up):
    return parse_hud(up.program.channel.hud_file.read_text(encoding="utf-8"))


def test_the_genau_selector_shows_genau_and_holds_the_slideshow_still(tmp_path):
    up, _library, _gallery = _shown(tmp_path)

    up.shown.press("genau_activate")
    up.tick_the_funestra()

    assert up.funestra.showing == MainMode.GENAU
    assert up.funestra.playback.is_paused
    assert up.slideshow.is_showing()


def test_the_kino_selector_brings_the_slideshow_back_where_it_was(tmp_path):
    up, _library, _gallery = _shown(tmp_path)
    up.shown.press(f"{SHAPE}_next")
    up.tick_the_funestra()
    before = up.funestra.playback.current_video
    up.shown.press("genau_activate")
    up.tick_the_funestra()

    up.shown.press("main_kino_activate")
    up.tick_the_funestra()

    assert up.funestra.showing == MainMode.KINO
    assert up.funestra.playback.current_video == before
    assert not up.funestra.playback.is_paused


def test_back_in_genau_it_is_on_the_flick_it_was_on(tmp_path):
    up, library, _gallery = _shown(tmp_path)
    up.shown.show_genau(library.file_of("two"))
    assert _flick_on_screen(up) == "two"
    up.shown.press("main_kino_activate")
    up.tick_the_funestra()

    up.shown.press("genau_activate")

    assert _flick_on_screen(up) == "two"


def test_shown_on_a_flick_genau_plays_it(tmp_path):
    up, library, _gallery = _shown(tmp_path)

    up.shown.show_genau(library.file_of("two"))

    assert _flick_on_screen(up) == "two"


def test_while_genau_shows_the_hud_is_genaus(tmp_path):
    up, library, _gallery = _shown(tmp_path)

    up.shown.show_genau(library.file_of("one"))
    _flick_on_screen(up)

    hud = _hud(up)
    assert (hud.kind, hud.facts.main_mode, hud.item_name) == (
        HudKind.SLIDESHOW, MainMode.GENAU, "one")


def test_back_in_kino_the_hud_is_the_slideshows_again(tmp_path):
    up, _library, _gallery = _shown(tmp_path)
    up.shown.show_genau()

    up.shown.show_kino()

    assert _hud(up).facts.main_mode is MainMode.KINO


def test_every_button_genaus_hud_draws_is_answered(tmp_path):
    up, library, _gallery = _shown(tmp_path)
    up.shown.show_genau(library.file_of("one"))
    _flick_on_screen(up)
    facts = _hud(up).facts

    drawn = [button.command for row in hud_rows(HudKind.SLIDESHOW, facts) for button in row
             if button.command and not button.dim]

    assert [command for command in drawn if not up.shown.press(command)] == []


def test_the_room_paused_while_genau_shows_pauses_genau_too(tmp_path):
    up, _library, _gallery = _shown(tmp_path)
    up.shown.show_genau()

    up.shown.room_paused(True)

    assert up.program.genau.paused.read_text(encoding="utf-8") == "1"
    assert up.funestra.playback.is_paused


def test_with_kino_showing_genau_is_held_still(tmp_path):
    up, _library, _gallery = _shown(tmp_path)
    up.shown.show_genau()

    up.shown.show_kino()

    assert up.program.genau.paused.read_text(encoding="utf-8") == "1"


@pytest.mark.parametrize(("key", "verb"), [("right", "NEXT"), ("left", "PREV"),
                                           ("down", "TOGGLE_LOCK")])
def test_genaus_keys_are_the_slideshows_keys_for_the_same_thing(tmp_path, key, verb):
    up, _library, _gallery = _shown(tmp_path)
    up.shown.show_genau()

    up.key(key)

    assert up.program.genau.command.read_text(encoding="utf-8").splitlines()[-1] == verb


def test_up_in_genau_sends_its_flick_to_trash(tmp_path):
    up, library, gallery = _shown(tmp_path)
    up.shown.show_genau(library.file_of("one"))
    _flick_on_screen(up)

    up.key("up")

    assert gallery.trashed == ["one"]


def test_shift_left_in_genau_leaves_the_slideshow_alone(tmp_path):
    up, _library, _gallery = _shown(tmp_path)
    before = up.funestra.playback.current_video
    up.shown.show_genau()

    up.key("left", "shift")
    up.tick_the_funestra()

    assert up.funestra.playback.current_video == before


def test_enter_in_genau_shows_its_flicks_item_in_core(tmp_path):
    shown_in_core: list[str] = []
    up, library, _gallery = _shown(tmp_path, actions=SlideshowActions(
        leave_for_core=lambda prompt_id: shown_in_core.append(prompt_id) or True))
    up.shown.show_genau(library.file_of("two"))
    _flick_on_screen(up)

    up.key("return")

    assert shown_in_core == ["two"]


def test_the_kino_selector_on_a_slideshow_with_nothing_in_it_starts_one(tmp_path):
    started: list[str] = []
    up, _library, _gallery = _shown(tmp_path, items=(), actions=SlideshowActions(
        start_slideshow=lambda: started.append("started")))
    up.shown.show_genau()

    up.shown.press("main_kino_activate")

    assert started == ["started"]
