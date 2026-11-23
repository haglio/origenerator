from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from app_support.file_channel import publish_whole, read_key_values
from funestra.broker_feed import BeatSender
from funestra.file_channel import append_command
from funestra.flick_list import RELOAD_FLICKS, write_flicks
from funestra.funestra_verbs import LOCK_OFF, LOCK_ON, NEXT, TOGGLE_LOCK, play_file
from funestra.genau_buttons import FLIP_THE_FLICK, GENAU_VERBS, TRASH_FLICK
from funestra.genau_controls import FLICK_SECONDS, PAUSE, RESUME
from funestra.genau_status import GenauStatus, genau_status_from
from funestra.hud_kinds import HudFacts, HudKind, main_title
from funestra.inclusion_pair import orientation_pair as shape_pair
from funestra.main_hud import ModeHud
from funestra.modes import MainMode
from funestra.playlist import PlaylistItem
from funestra.satellite_hud import HudModel

from origenerator.content import genau_flick_words
from origenerator.genau_flicks import (
    AS_GENAU_STARTS,
    NO_FILTER,
    Flick,
    FlicksLibrary,
    GenauFilters,
    GenauLeft,
    flicks_of,
)
from origenerator.gui.osr2_controls_state import post_device_action

GENAU_RESET = "genau_reset"
_ORDERS = {"latest": True, "shuffle": False}
_SHAPES = {command.partition("_")[2]: included
                 for command, included in shape_pair("").asked.items()}
_COLLECTIONS = ("favorites", "enhanced")
_SPEED_STEPS = ("speed_up", "speed_down")
_SPEED = "SPEED"


@dataclass(frozen=True)
class GenauSources:
    library: Callable[[], FlicksLibrary]
    is_favorite: Callable[[str], bool]
    unfavorite: Callable[[str], None]
    trash: Callable[[str], None]
    flip: Callable[[str, bool], None]
    name_of: Callable[[str], str]
    motion: object = None
    starts_with: GenauLeft = AS_GENAU_STARTS
    flick_words: Callable[[], tuple[str, str]] = genau_flick_words


class StandaloneGenau:
    def __init__(self, program, sources: GenauSources, *, beat=None) -> None:
        self._launch = program.genau
        self._channel = program.channel
        self._sources = sources
        self._beat = beat if beat is not None else BeatSender(program.genau.beat_port)
        self._left_as: GenauLeft | None = sources.starts_with
        self.filters = sources.starts_with.filters
        self.latest = sources.starts_with.latest
        self.heard = GenauStatus()
        self._flicks: dict[Path, Flick] = {}
        self._flipped_here: dict[str, bool] = {}
        self._gone: set[str] = set()
        self._paused: bool | None = None
        self._driving: bool | None = None
        self._bpm: float | None = None
        self._speed: int | None = None

    def show(self, path: Path | None = None) -> None:
        self._list()
        left, self._left_as = self._left_as, None
        if left is not None:
            path = path or self._put_back_as(left)
        if path is not None:
            self._tell(play_file(PlaylistItem(Path(path))))

    def _put_back_as(self, left: GenauLeft) -> Path | None:
        self._tell("LATEST" if left.latest else "SHUFFLE")
        self._tell(LOCK_ON if left.locked else LOCK_OFF)
        self._tell(f"{FLICK_SECONDS} {left.seconds}")
        return next((path for path, flick in self._flicks.items()
                     if flick.prompt_id == left.flick), None)

    def left(self, *, showing: bool) -> GenauLeft:
        if self._left_as is not None:
            return replace(self._left_as, filters=self.filters, showing=showing)
        return GenauLeft(filters=self.filters, showing=showing, latest=self.latest,
                         locked=self.heard.locked, seconds=self.heard.interval,
                         flick=self.prompt_id_on_screen() or "")

    def press(self, action: str) -> bool:
        if action in GENAU_VERBS:
            if action == FLIP_THE_FLICK:
                self._flip()
            self._tell(GENAU_VERBS[action])
        elif action == TRASH_FLICK:
            self._trash()
        elif action == "lock":
            self._tell(TOGGLE_LOCK)
        elif action == GENAU_RESET:
            self._reset()
        elif action in _ORDERS:
            self.latest = _ORDERS[action]
            self._tell(action.upper())
        elif action in _COLLECTIONS:
            self._narrow(replace(self.filters, **{action: not getattr(self.filters, action)}))
        elif action in _SHAPES:
            included = _SHAPES[action]
            self._narrow(replace(self.filters, shapes=included),
                         says=shape_pair("").flash(included))
        elif action in _SPEED_STEPS:
            post_device_action(f"robot_hand_{action}", motion=self._sources.motion)
        else:
            return False
        return True

    def read_status(self) -> dict[str, str]:
        try:
            return read_key_values(self._launch.status)
        except OSError:
            return {}

    def heard_from(self, values: dict[str, str]) -> bool:
        heard = genau_status_from(values) if values else self.heard
        changed, self.heard = heard != self.heard, heard
        return changed

    def prompt_id_on_screen(self) -> str | None:
        flick = self._flick_on_screen()
        return None if flick is None else flick.prompt_id

    def hud_model(self, shape: str, foot) -> HudModel:
        one, many = self._sources.flick_words()
        prompt_id = self.prompt_id_on_screen()
        heard, filters = self.heard, self.filters
        portrait, landscape = filters.shapes
        facts = HudFacts(
            funestra=shape, main_mode=MainMode.GENAU, hosted=False, locked=heard.locked,
            flipped=heard.flipped,
            favorite=prompt_id is not None and self._sources.is_favorite(prompt_id),
            favorites=filters.favorites, enhanced=filters.enhanced, latest=self.latest,
            plays_portrait=portrait, plays_landscape=landscape, pace_s=heard.interval,
            nothing_to_reset=filters == NO_FILTER and heard.locked and not self.latest,
            flick_one=one, flick_many=many)
        return HudModel(
            funestra=shape, locked=facts.locked, kind=HudKind.SLIDESHOW, facts=facts,
            title=main_title(facts, ModeHud()), is_favorite=facts.favorite,
            item_name="" if prompt_id is None else self._sources.name_of(prompt_id), foot=foot)

    def set_paused(self, paused: bool) -> None:
        if paused == self._paused:
            return
        self._paused = paused
        publish_whole(self._launch.paused, "1" if paused else "0")
        self._tell(PAUSE if paused else RESUME)

    def follow_the_beat(self, *, showing: bool) -> None:
        motion = self._sources.motion
        driving = showing and motion is not None and motion.active
        if driving != self._driving:
            self._driving, self._bpm = driving, None
            self._beat.drive(driving)
        if motion is None:
            return
        if driving and motion.state.bpm != self._bpm:
            self._bpm = motion.state.bpm
            self._beat.bpm(self._bpm)
        speed = motion.state.state.speed
        if speed != self._speed:
            self._speed = speed
            self._tell(f"{_SPEED} {speed}")

    def loop_came_round(self) -> None:
        if self._driving:
            self._beat.sync()

    def close(self) -> None:
        if self._driving:
            self._driving = False
            self._beat.drive(False)
        self._beat.close()

    def _tell(self, verb: str) -> None:
        append_command(self._launch.command, verb)

    def _list(self, says: str = "") -> None:
        listed = [replace(flick, flipped=self._flipped_here.get(flick.prompt_id, flick.flipped))
                  for flick in flicks_of(self._sources.library(), self.filters)
                  if flick.prompt_id not in self._gone]
        self._flicks = {flick.path: flick for flick in listed}
        write_flicks(self._launch.flicks, [flick.path for flick in listed],
                     flipped={flick.path for flick in listed if flick.flipped})
        self._channel.send(f"{RELOAD_FLICKS} {says}".strip())

    def _narrow(self, filters: GenauFilters, *, says: str = "") -> None:
        self.filters = filters
        self._list(says)

    def _reset(self) -> None:
        self.latest = False
        self._narrow(NO_FILTER)
        self._tell(LOCK_ON)
        self._tell("SHUFFLE")

    def _flick_on_screen(self) -> Flick | None:
        return self._flicks.get(Path(self.heard.flick)) if self.heard.flick else None

    def _flip(self) -> None:
        flick = self._flick_on_screen()
        if flick is None:
            return
        flipped = not self.heard.flipped
        self._flipped_here[flick.prompt_id] = flipped
        self._sources.flip(flick.prompt_id, flipped)

    def _trash(self) -> None:
        prompt_id = self.prompt_id_on_screen()
        if prompt_id is None:
            return
        if self._sources.is_favorite(prompt_id):
            self._sources.unfavorite(prompt_id)
        else:
            self._sources.trash(prompt_id)
            self._gone.add(prompt_id)
            self._list()
        self._tell(NEXT)
