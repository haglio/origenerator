from __future__ import annotations

from pathlib import Path

import numpy as np
from funestra.funestra import Channels, Funestra
from funestra.funestra_setup import FunestraSetup
from funestra.funestra_verbs import QUIT, RELOAD_PLAYLIST
from funestra.genau_engine import EngineSeams
from funestra.off_the_loop import AtOnce
from funestra.playlist import read_playlist
from funestra.program.genau_here import kino_and_genau
from funestra.testing import FakeEngine, every_thread_now_but_the_ones_that_run_for_good
from PySide6.QtCore import QRect

from origenerator.gui.frame_files import FrameFiles
from origenerator.gui.funestra_asks import AsksFromTheFunestra
from origenerator.gui.funestra_program import Wearing, a_free_port, genau_beside
from origenerator.gui.funestra_slideshow import FunestraSlideshow
from origenerator.gui.on_its_own_funestra import USUAL_WIRING, OnItsOwnFunestra, OwnWiring
from origenerator.gui.slideshow_playing import Hosting, Playing, Seat
from origenerator.gui.slideshow_wiring import SlideshowActions
from origenerator.gui.standalone_genau import StandaloneGenau
from tests.genau_support import HeardBeat

VIEWPORT = (1280, 720)
USUAL_WEARING = Wearing()
GENAU_ON_A_FAKE_ENGINE = EngineSeams(
    decode=lambda _path: [np.zeros((8, 16, 3), dtype=np.uint8)] * 4,
    start_thread=every_thread_now_but_the_ones_that_run_for_good, off_the_loop=AtOnce)


class _ThisTests:
    folder: Path | None = None
    made = 0


def files_go_under(folder: Path) -> None:
    _ThisTests.folder, _ThisTests.made = folder, 0


def a_folder() -> Path:
    _ThisTests.made += 1
    return _ThisTests.folder / f"funestra {_ThisTests.made}"


def standalone(items, **how) -> StandaloneSlideshow:
    return StandaloneSlideshow(a_folder(), items, **how)


class _Window:
    def __init__(self) -> None:
        self.shown = False
        self.minimized = False
        self.on_top = False
        self.position = (0, 0)
        self.size = VIEWPORT

    def show(self) -> None:
        self.shown = True

    def hide(self) -> None:
        self.shown = False

    def minimize(self) -> None:
        self.minimized = True

    def restore(self) -> None:
        self.minimized = False


class _HandedStraightAcross:
    waits_on_the_disk = False

    def __init__(self, program: FakeProgram, folder: Path) -> None:
        self._program = program
        self.playlist = folder / "playlist.tsv"
        self.command_file = folder / "cmd.txt"
        self.status_file = folder / "status.txt"
        self.hud_file = folder / "hud.json"
        self.message_file = None

    def write_playlist(self, items) -> None:
        self._program.items = list(items)
        self._program.open_if_it_has_a_list()

    def send(self, verb: str) -> bool:
        self._program.sent.append(verb)
        self._program.apply(verb)
        return True

    def send_all(self, verbs: list[str]) -> bool:
        for verb in verbs:
            self.send(verb)
        return True

    def status(self) -> dict[str, str]:
        funestra = self._program.funestra
        if funestra is None or funestra.playback.has_nothing_to_play:
            return {}
        return funestra.status_fields()


class FakeProgram:
    def __init__(self, folder: Path, wearing: Wearing = USUAL_WEARING, *, clock=USUAL_WIRING.clock) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self.wearing = wearing
        self._clock = clock
        self.channel = _HandedStraightAcross(self, folder)
        self.asks_file = folder / "asks.txt"
        self.paused_file = folder / "paused.txt"
        self.genau = genau_beside(folder, beat_port=a_free_port())
        self.engine = FakeEngine()
        self.window = _Window()
        self.funestra: Funestra | None = None
        self.items: list = []
        self.sent: list[str] = []
        self._owed: list[str] = []
        self._paused = False
        self.place = None
        self.minimized = False
        self.shown_on: list = []
        self.started = False
        self.ended = False

    @property
    def running(self) -> bool:
        return self.started and not self.ended

    def start(self) -> None:
        self.started = True

    def open_if_it_has_a_list(self) -> None:
        if self.funestra is not None or not (self.items or read_playlist(self.genau.flicks)):
            return
        self.funestra = Funestra(self.engine, FunestraSetup(
            channels=Channels(hud=self.channel.hud_file, dashboard_cmd=self.asks_file),
            playlist=self.items, audible=True, clock=self._clock,
            users=kino_and_genau(self.genau, notice=None, seams=GENAU_ON_A_FAKE_ENGINE)))
        self.funestra.playback.set_paused(self._paused)
        owed, self._owed = self._owed, []
        for verb in owed:
            self.apply(verb)

    def apply(self, verb: str) -> None:
        if verb == QUIT:
            self.ended = True
        elif self.funestra is None:
            self._owed.append(verb)
            self.open_if_it_has_a_list()
        elif verb == RELOAD_PLAYLIST:
            self.funestra.take_the_list(self.items)
        else:
            self.funestra.apply(verb)

    def tick(self, viewport: tuple[int, int] = VIEWPORT) -> None:
        if self.funestra is not None:
            self.funestra.tick(viewport=viewport)

    def show_on(self, place) -> None:
        self.place, self.minimized = place, False
        self.shown_on.append(place)
        self.window.restore()
        self.window.show()

    def hide(self) -> None:
        self.window.hide()

    def minimize(self) -> None:
        self.minimized = True
        self.window.minimize()

    def stand_on_top(self, on: bool) -> None:
        self.window.on_top = on

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        if self.funestra is not None:
            self.funestra.playback.set_paused(paused)

    def end(self) -> None:
        self.ended = True
        if self.funestra is not None:
            self.funestra.close()


class FakeScreen:
    def __init__(self, width: int = VIEWPORT[0], height: int = VIEWPORT[1], *, x: int = 0,
                 y: int = 0, scale: float = 1.0) -> None:
        self._area, self._scale = QRect(x, y, width, height), scale

    def geometry(self) -> QRect:
        return QRect(self._area)

    def devicePixelRatio(self) -> float:
        return self._scale


class StandaloneSlideshow:
    def __init__(self, folder: Path, items, *, shape: str = "", start=None, shuffle=None,
                 actions=None, hud=None, versions=None, pace=None, frames=None,
                 locked: bool = False, motion=None, radio=None, volume=None,
                 clock=USUAL_WIRING.clock, message=None, engine=None, genau=None) -> None:
        self._clock = clock
        self.program = FakeProgram(folder, clock=clock)
        if engine is not None:
            self.program.engine = engine
        self.program.start()
        actions = actions if actions is not None else SlideshowActions()
        self.beat = HeardBeat()
        self.genau = (None if genau is None
                      else StandaloneGenau(self.program, genau, beat=self.beat))
        self.asks = AsksFromTheFunestra(self.program.asks_file, clock=clock)
        self.shown = OnItsOwnFunestra(
            self.program, shape, actions,
            OwnWiring(motion=motion, radio=radio, volume=volume, clock=clock), asks=self.asks,
            message=message, genau=self.genau)
        self.slideshow = FunestraSlideshow(
            Playing(items, start=start, shuffle=shuffle, hud=hud, actions=actions,
                    versions=versions, locked=locked),
            Seat(shape, self.shown.channel,
                 frames if frames is not None else FrameFiles(folder / "frames")),
            Hosting(pace=pace, shown=self.shown.shown_for))
        self.shown.setParent(self.slideshow)
        self._size = VIEWPORT
        self.shown.show_on(FakeScreen(*self._size))

    def __getattr__(self, name: str):
        return getattr(self.shown, name)

    @property
    def engine(self) -> FakeEngine:
        return self.program.engine

    @property
    def funestra(self) -> Funestra:
        return self.program.funestra

    def resize(self, width: int, height: int) -> None:
        self._size = (width, height)
        self.shown.show_on(FakeScreen(width, height))

    def width(self) -> int:
        return self._size[0]

    def height(self) -> int:
        return self._size[1]

    def is_up(self) -> bool:
        return self.slideshow.is_showing() and not self.program.ended

    def close(self) -> None:
        self.slideshow.close()

    def tick_the_funestra(self) -> None:
        self.program.tick(self._size)
        self.asks.read_now()

    def click(self, at: tuple[int, int]) -> None:
        self.funestra.press(*at, viewport=self._size)
        self.funestra.release()
        self.tick_the_funestra()

    def double_click(self, at: tuple[int, int]) -> None:
        self.click(at)
        self.funestra.press_again(*at, viewport=self._size)
        self.funestra.release()
        self.tick_the_funestra()

    def wheel(self, at: tuple[int, int], steps: int) -> None:
        self.funestra.wheel(*at, steps, viewport=self._size)
        self.asks.read_now()

    def key(self, name: str, held: str = "") -> None:
        self.shown.asked(f"key|{name}|{held}", self._clock())
