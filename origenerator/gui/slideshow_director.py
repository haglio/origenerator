from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, replace
from functools import cached_property, partial
from pathlib import Path
from random import randrange
from typing import Protocol

from app_support.gallery_rows import source_of
from funestra.hud_placement import HudCorner
from funestra.hud_title import LATEST_LABEL, SHUFFLE_LABEL
from funestra.volume import VolumeHud
from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget
from shared_ui.foreground import bring_to_front
from shared_ui.message_shape import FAVORITE, INFO, WARNING

from origenerator import gallery
from origenerator.config import FRAMES_BEING_MADE_DIR, OUTPUT_PLACES, STATE_DIR
from origenerator.fun_time_bridge import (
    ask_for_omnipause,
    ask_the_main_funestra_to_play,
    tell_of_a_lock,
)
from origenerator.fun_time_mode import majority_shape, region_for_items
from origenerator.funscript import funscript_of
from origenerator.gallery.collection import (
    FAVORITES_KEY as _FAVORITES_KEY,
)
from origenerator.gallery.collection import (
    LATEST_KEY as _LATEST_KEY,
)
from origenerator.gallery.collection import collection as _collection
from origenerator.gallery.collection import folder_collection
from origenerator.gallery.non_ai import video_kino_plays
from origenerator.gallery.shapes import (
    SHAPES as _SHAPES,
)
from origenerator.gallery.shapes import shape_holds, the_one_shape_on, the_shape_of
from origenerator.generation_state import GenerationSource
from origenerator.gui.action_presses import striking
from origenerator.gui.frame_files import FrameFiles
from origenerator.gui.funestra_asks import AsksFromTheFunestra
from origenerator.gui.funestra_program import OwnFunestras
from origenerator.gui.funestra_slideshow import (
    FunestraSlideshow,
    Hosting,
    Playing,
    Seat,
)
from origenerator.gui.hud_nav_map import NavMapNeighbors, NavMapRow
from origenerator.gui.hud_places import (
    HudPlaces,
    as_saved,
    collapsed,
    has_the_osr2,
    moved,
    opened_in,
    place_of,
    restore,
    told,
)
from origenerator.gui.on_its_own_funestra import HudWear, OnItsOwnFunestra, OwnWiring
from origenerator.gui.region_openings import RegionOpening, RegionOpenings
from origenerator.gui.regions_left import RegionLeft, restored_regions, saved_regions
from origenerator.gui.slideshow_lock import LockedOn, lock_held
from origenerator.gui.slideshow_pace import SlideshowPace
from origenerator.gui.slideshow_wiring import (
    NOTHING_CARRIED,
    Carrying,
    DirectorSources,
    DirectorSurroundings,
    HudFacts,
    Showing,
    SlideshowActions,
)
from origenerator.gui.two_screens import TwoScreens, monitor_shaped
from origenerator.gui.what_can_play import WhatCanPlay
from origenerator.item_shape import (
    filter_rows,
    plays_in_a_slideshow,
    row_shape,
    shaped_key,
    together,
    what_plays_at,
)
from origenerator.item_shape import (
    split_key as _split_collection_key,
)
from origenerator.media import MediaType
from origenerator.nav_map import (
    SlideGroups,
    actions_lines,
    beyond_the_row,
    one_per_stretch,
    surroundings,
)
from origenerator.one_look import looking_once
from origenerator.slideshow import (
    Slide,
    SlideshowFilters,
    SlideshowState,
    in_order,
)
from origenerator.voice.app_commands import AppCommand
from origenerator.voice.dictation import words_of
from origenerator.voice.slideshow_commands import SlideshowCommand

logger = logging.getLogger(__name__)

_ABOUT_THE_SLIDE_SAID_OVER = frozenset({AppCommand.CULL, AppCommand.FAVORITE, AppCommand.LOCK})

_OPENINGS_KEPT_FRESH_MS = 10 * 60 * 1000



class SlideshowHost(Protocol):
    def refresh(self) -> None: ...

    def off_thread(self, work, done) -> None: ...

    def window(self): ...

    def follow_link(self, prompt_id: str) -> None: ...

    def show_generation(self, prompt_id: str) -> None: ...

    def reveal(self, prompt_id: str) -> bool: ...

    def trash_generation(self, prompt_id: str) -> None: ...

    def favorite_generation(self, prompt_id: str, favorite: bool = True) -> None: ...

    def set_room_paused(self, paused: bool) -> None: ...


@dataclass(frozen=True)
class HeldSlideshow:
    items: tuple
    shape: str | None
    order_label: str
    state: SlideshowState
    filters: SlideshowFilters


def _still_up(slideshow):
    return slideshow if slideshow is not None and slideshow.is_showing() else None


def _place_of(prompt_id: str, items) -> int | None:
    return next((index for index, item in enumerate(items) if item[2] == prompt_id), None)


def _place_among(kept, state: SlideshowState) -> SlideshowState:
    order = tuple(prompt_id for prompt_id in state.order if prompt_id in kept)
    if state.current in kept:
        return replace(state, order=order)
    after = state.order.index(state.current) + 1 if state.current in state.order else 0
    following = next((prompt_id for prompt_id in (*state.order[after:], *state.order[:after])
                      if prompt_id in kept), None)
    return SlideshowState(order=order, current=following, location=state.location)


def _item_opened_on(items, start: int | None, resume: SlideshowState | None) -> str | None:
    if start is not None:
        return items[start][2]
    return resume.current if resume is not None else None


def _narrowed_to(held: HeldSlideshow, shape: str, ids) -> HeldSlideshow:
    return replace(held, shape=shape,
                   items=tuple(slide for slide in held.items if slide.prompt_id in ids),
                   state=_place_among(ids, held.state))


def _shapes_in(rows, items) -> list[str]:
    ids = {item[2] for item in items}
    return [row_shape(row) for row in rows if row["prompt_id"] in ids]


def _one_shape_of_the_set(rows, items) -> str | None:
    return the_shape_of(_shapes_in(rows, items))


def _shape_of_the_set(rows, items) -> str:
    shapes = _shapes_in(rows, items)
    return majority_shape(shapes) if shapes else region_for_items(items)


def _shape_it_opens_on(shape: str, rows, items, opened_on: str | None) -> str:
    if (row := next((row for row in rows if row["prompt_id"] == opened_on), None)) is not None:
        return row_shape(row)
    if (shape := the_one_shape_on(shape)) is not None:
        return shape
    return _shape_of_the_set(rows, items)


def _every(interval_ms: int, then) -> QTimer:
    timer = QTimer()
    timer.setInterval(interval_ms)
    timer.timeout.connect(then)
    return timer


class SlideshowDirector:
    def __init__(self, host: SlideshowHost, sources: DirectorSources,
                 surroundings: DirectorSurroundings):
        self._host = host
        self._radio = surroundings.radio
        self._genau = surroundings.genau
        self._buttons_of = surroundings.buttons_of
        self._enhancing_of = surroundings.enhancing_of
        self._volume_left_at: VolumeHud | None = None
        self._db = sources.db
        self._runs_being_made: dict[str, dict] = {}
        self._names = sources.names
        self._listing = sources.listing
        self._weight_of = sources.weight_of
        self._jobs = sources.jobs
        self._pace = surroundings.pace
        self._region_paces: dict[str, SlideshowPace] = {}
        self._motion = surroundings.motion
        self._osr2 = surroundings.osr2
        self._job_queue = surroundings.job_queue
        fun_time = self._fun_time = surroundings.fun_time
        self.two_screens = surroundings.two_screens or TwoScreens()
        self._own_funestras = surroundings.own_funestras or OwnFunestras(STATE_DIR / "funestras")
        application = QGuiApplication.instance()
        if application is not None:
            application.aboutToQuit.connect(self._own_funestras.end_the_one_waiting)
        self._asked_for_by_him = True
        self.two_screens.switched.connect(self._keep_the_slideshow_off_cores_monitor)
        self.two_screens.core_is_up.connect(self._have_a_funestra_waiting)
        self.two_screens.core_is_up.connect(self._keep_a_slideshow_up)
        self._slideshow = None
        self._standalone_shape: str | None = None
        self._standalone_window_shape: str | None = None
        self._standalone_showing: str | None = None
        self._huds = HudPlaces()
        self._live_slideshows: list[tuple] = []
        self._regions_wanted: set[str] = set()
        self._openings = RegionOpenings(self._rows_of_the_base_state, self._opening_of,
                                        self._with_its_lead_on_the_map)
        self._openings_kept_fresh = _every(_OPENINGS_KEPT_FRESH_MS, self.make_the_openings_ready)
        self._asked_for: dict[str, partial] = {}
        self._region_slideshows: dict[str, QWidget | None] = (
            dict.fromkeys(_SHAPES) if fun_time is not None else {}
        )
        self._room_paused = False
        self._slideshow_state = SlideshowState()
        self._picked_as_the_slideshow_up_opened: tuple[str, ...] = ()
        self._filters = SlideshowFilters()
        self._enhance_status: dict[str, str] = {}
        self._library = sources.library
        self._groups = SlideGroups(library=self._library, sources=sources)
        self._taken_into_the_session: dict[str, HeldSlideshow] = {}
        self._regions_left: dict[str, RegionLeft] = {}
        self._giving_them_back = False
        self._have_a_funestra_waiting()

    def become_hosted(self, session) -> None:
        self._taken_into_the_session = self._held_for_the_session()
        if self._slideshow is not None:
            self._slideshow.close()
        self._fun_time = session
        self._motion = None
        self._region_slideshows = dict.fromkeys(_SHAPES)
        self._region_paces = {}
        self.make_the_openings_ready()

    def become_standalone(self, motion) -> None:
        self._taken_into_the_session = {}
        self.close_the_slideshows()
        self._fun_time = None
        self._motion = motion
        self._region_slideshows = {}

    @property
    def showing(self):
        return self._slideshow

    def surfaces(self) -> list:
        candidates = [self._slideshow, *self._region_slideshows.values()]
        surfaces, seen = [], set()
        for surface in candidates:
            if surface is None or id(surface) in seen:
                continue
            seen.add(id(surface))
            surfaces.append(surface)
        return surfaces

    def any_up(self) -> bool:
        return any(surface.is_showing() for surface in self.surfaces())

    def locked_prompt_ids(self) -> set[str]:
        return {slideshow.locked_on for slideshow in self.surfaces()
                if slideshow.is_showing() and slideshow.locked_on is not None}

    def surface_for(self, shape: str | None):
        if shape is not None and self._fun_time is not None:
            return self.region_slideshow(shape)
        return self._slideshow

    def region_slideshow(self, shape: str):
        return _still_up(self._region_slideshows.get(shape))

    def _pace_on(self, shape: str) -> SlideshowPace:
        if self._fun_time is None:
            return self._pace
        if shape not in self._region_paces:
            self._region_paces[shape] = SlideshowPace(self._pace.seconds)
        return self._region_paces[shape]

    def _window_up(self):
        return _still_up(self._slideshow)

    @cached_property
    def _what_can_play(self) -> WhatCanPlay:
        return WhatCanPlay(lambda row: gallery.resolve_preview(row, OUTPUT_PLACES))

    def anything_to_play(self) -> bool:
        return self._what_can_play.anything_in(self._listing().rows)

    def start(self, *, shape: str | None = None):
        listing = self._listing()
        location = listing.location
        base, located_on = _split_collection_key(location)
        collection = folder_collection(base)
        shape = shape or located_on
        switch = _collection(collection.which).slideshow_filter if collection is not None else None
        if switch is not None:
            shape = shape or listing.shape
            location = shaped_key(collection.folder, shape)
            rows = together(self.rows_at(location), self.rows_at(shaped_key(collection.key, shape)))
        else:
            rows = self._one_per_run_where_the_order_is_newest_first(location, listing.rows)
        items = self.items_of(rows)
        if not items:
            return
        latest = collection is not None and collection.which == _LATEST_KEY
        picked = [] if latest else self._picked_since_the_slideshow_up_opened()
        one_picked = picked[0] if len(picked) == 1 else None
        resume = None if latest else self._place_coming_back_to(location, items)
        start = _place_of(one_picked, items) if one_picked is not None else None
        picked_elsewhere = (start is not None and resume is not None
                            and resume.current != one_picked)
        self.open(items, rows=rows, location=location, shape=shape, start=start,
                  carrying=Carrying(
                      resume=None if picked_elsewhere else resume,
                      filters=replace(self._filters, **{switch: True}) if switch else None),
                  **self._order(latest))
        logger.info("Slideshow of %s: %d items, %s",
                    listing.subject, len(items),
                    "latest" if latest else "shuffled")

    def _picked_since_the_slideshow_up_opened(self) -> list[str]:
        picked = self._listing().picked
        if (_still_up(self._slideshow) is not None
                and picked == self._picked_as_the_slideshow_up_opened):
            return []
        return list(picked)

    def _order(self, latest: bool) -> dict:
        return {"shuffle": in_order if latest else None,
                "hud": HudFacts(order_label=LATEST_LABEL if latest else SHUFFLE_LABEL)}

    @looking_once
    def open_on_preview(self, media, generation):
        if media is not None and self._plays_on_the_main_funestra(self._row_for(generation)):
            return None
        hud = HudFacts(order_label=LATEST_LABEL)
        if media is None:
            location = self._location_of(self._row_for(generation)) if generation else None
            listed = self.rows_at(location) if location else self._listed_rows()
            run = self._run_being_made_at(location)
            slideshow = self.open([], rows=listed, start=0, shuffle=in_order, location=location,
                                  carrying=Carrying(folder_items=self.items_of(listed)), hud=hud)
            logger.info("Slideshow of the frame being made, run %s, at %s: %d items, "
                        "run being made there %s, opened on %s", generation, location,
                        len(listed), run["prompt_id"] if run else None,
                        slideshow.hud_prompt_id if slideshow is not None else None)
            return slideshow
        logger.info("Slideshow of the preview's finished item, run %s, file %s",
                    generation, Path(media[0]).name)
        rows = [row for row in [self._row_for(generation)] if row]
        items = self.items_of(rows) or [(media[0], media[1], generation, None)]
        return self.open(items[:1], rows=rows, start=0, shuffle=in_order, hud=hud,
                         locked=True)

    @looking_once
    def open_on_tile(self, generation):
        row = self._row_for(generation)
        if self._plays_on_the_main_funestra(row):
            return None
        items = self.items_of([row]) if row is not None else []
        if not items:
            return None
        return self.open_in_its_folder(items[0][:2], generation)

    def _plays_on_the_main_funestra(self, row: dict | None) -> bool:
        kinos = video_kino_plays(row) if row is not None else None
        return kinos is not None and (
            ask_the_main_funestra_to_play(
                self._session_channel, kinos,
                in_genau=self._genau is not None and self._genau.holds(Path(kinos)))
            or self._fun_time is not None)

    @looking_once
    def open_in_its_folder(self, media, generation):
        listed = self._listed_rows()
        hud = HudFacts(order_label=LATEST_LABEL)
        if any(row["prompt_id"] == generation for row in listed):
            location, rows = self._listing().location, listed
        else:
            location = self._location_of(self._row_for(generation))
            rows = self.rows_at(location)
        opened_on = [row for row in rows if row["prompt_id"] == generation]
        items = self.items_of(opened_on)
        if not items:
            return self.open([(media[0], media[1], generation, None)], start=0, shuffle=in_order,
                             rows=[row for row in [self._row_for(generation)] if row],
                             location=location, hud=hud)
        shape = majority_shape(map(row_shape, rows))
        slideshow = self.open(items, rows=opened_on, location=location, start=0, shape=shape,
                              shuffle=in_order, hud=hud)

        def fill_in(folder) -> None:
            if folder is None or slideshow is not self._slideshow or _still_up(slideshow) is None:
                return
            folder_items, versions = folder
            start = _place_of(generation, folder_items)
            if start is not None:
                self.open(folder_items, rows=rows, location=location, start=start, shape=shape,
                          shuffle=in_order, hud=hud, carrying=Carrying(versions=versions))

        if slideshow is not None and len(rows) > 1:
            self._host.off_thread(
                lambda: (self.items_of(rows), self.versions_of(rows)), fill_in)
        return slideshow

    def _listed_rows(self) -> list[dict]:
        rows = map(self._row_for, self._listing().shown)
        return self._what_a_slideshow_may_hold(row for row in rows if row is not None)

    def _row_for(self, prompt_id: str) -> dict | None:
        return self._library().row_for(prompt_id) or self._db.get_generation(prompt_id)

    def _location_of(self, row: dict | None) -> str | None:
        if row is None:
            return None
        key = gallery.settings_folder_key(row, self._library().image_index)
        return shaped_key(key, row_shape(row))

    @looking_once
    def open(self, items, *, rows=(), location=None, shape=None,
             carrying: Carrying = NOTHING_CARRIED, **kwargs):
        run = self._run_being_made_at(location) if not items else None
        where = shape or (row_shape(run) if run is not None
                         else _shape_of_the_set(rows, items or carrying.folder_items or []))
        channel = self._fun_time.funestra(where) if self._fun_time is not None else None
        follows_a_run = not items
        if follows_a_run and not carrying.folder_items and run is None:
            return None
        if (channel is not None and where not in self._regions_wanted
                and self._session_channel is not None):
            self._asked_for[where] = partial(
                self.open, items, rows=rows, location=location, shape=where,
                carrying=replace(carrying, versions=None), **kwargs)
            return None
        if follows_a_run:
            items, kwargs["start"] = carrying.folder_items or [], None
        opening = kwargs.pop("opening", None)
        hud = replace(kwargs.pop("hud", HudFacts()), enhancing=self._enhance_status)
        versions = self.versions_of(rows) if carrying.versions is None else carrying.versions
        showing = Showing(self._slideshow_actions(where), hud, versions, opening)
        keep_the_slide = kwargs.get("start") is not None
        if channel is not None:
            slideshow = self._hand_to_the_funestra(items, where, channel, showing, **kwargs)
        elif self._fun_time is not None:
            logger.warning("The session handed this app no %s Funestra, so nothing opens there",
                           where)
            return None
        else:
            shape = _shape_it_opens_on(where, rows, items,
                                       _item_opened_on(items, kwargs.get("start"), carrying.resume))
            slideshow = self._hand_to_the_apps_own_funestra(
                items, where, showing, window_shape=shape, **kwargs)
            self._standalone_showing = _one_shape_of_the_set(rows, items) or shape
        self._slideshow = slideshow
        self._picked_as_the_slideshow_up_opened = self._listing().picked
        already_live = any(live is slideshow for live, _where in self._live_slideshows)
        self._live_slideshows = [entry for entry in self._live_slideshows
                                 if entry[0] is not slideshow]
        self._live_slideshows.append((slideshow, location))
        filters = carrying.filters
        if filters is None:
            filters = self._filters if self._fun_time is None else SlideshowFilters()
        slideshow.take_up(filters, keep_the_slide=keep_the_slide)
        if carrying.resume is not None:
            slideshow.resume(carrying.resume, opened_on_it=keep_the_slide)
        if not keep_the_slide:
            self._lead_with_what_is_being_made(slideshow, location,
                                               following=run if follows_a_run else None)
        if not already_live:
            slideshow.open_requested.connect(self._pick_where_it_played)
            slideshow.closed.connect(lambda s=slideshow: self._on_closed(s))
            slideshow.media_changed.connect(self._osr2.reconcile)
        self._osr2.reconcile()
        return slideshow

    def _enhance_from_slideshow(self, prompt_id: str) -> bool:
        return self._enhancing_of().enhance_from_slideshow(prompt_id)

    def _lead_with_what_is_being_made(self, slideshow, location, *, following) -> None:
        if following is not None:
            slideshow.watch(following["prompt_id"])
        self._offer_the_frames(slideshow, location, self._job_queue.now()[0])
        if following is not None:
            slideshow.follow_what_is_being_made()
        else:
            slideshow.lead_with_what_is_being_made()

    def _slideshow_actions(self, shape: str) -> SlideshowActions:
        def at_its_regions_base(slideshow) -> bool:
            shown_on = self._shape_of(slideshow)
            where = next((where for live, where in self._live_slideshows if live is slideshow), None)
            return shown_on is None or where == self.base_location(shown_on)

        return SlideshowActions(
            queue_now=self._job_queue.now,
            delete=self._host.trash_generation,
            enhance=self._enhance_from_slideshow,
            favorite=self._host.favorite_generation,
            is_favorite=self._is_favorite,
            is_enhanced=self._is_enhanced,
            unfavorite=partial(self._host.favorite_generation, favorite=False),
            lock=(partial(lock_held, LockedOn(self._row_for, self._host.show_generation,
                                              self._host.favorite_generation), self.items_of,
                          partial(tell_of_a_lock, self._session_channel, shape))
                  if self._fun_time is not None else None),
            reset=(self.reset_region if self._fun_time is not None else None),
            at_base=(at_its_regions_base if self._fun_time is not None else None),
            reorder=self.reorder_slideshow,
            browse_all=self.browse_it_all,
            move=self._jobs.move,
            clear_queue=self._job_queue.clear_foreign,
            start_now=self._job_queue.start_now,
            cancel_all=self._job_queue.cancel_all,
            cancel_below=self._job_queue.cancel_below,
            core_window=self._host.window,
            leave_for_core=self._leave_for_core,
            drive_toggle=self._osr2.toggle,
            omnipause=self._ask_the_room_to_pause(),
            neighbors=partial(self.neighbors_of, shape=shape),
            widen=partial(self.beyond_the_row_of, shape=shape),
            actions_of=partial(self.actions_of, shape=shape),
            strike_action=striking(self._db, self._host),
            weight_of=self._weight_of,
            group_of=partial(self._groups, shape=shape),
            slides=self.slides_for,
            move_hud=partial(self.move_the_hud, shape=shape),
            filters_changed=self._note_filters,
            volume_moved=self._volume_moved if self._fun_time is None else None,
            name_of=self._names.of,
        )

    def _the_audio_standing_on_its_own(self) -> dict:
        if self._fun_time is not None:
            return {}
        return {"radio": self._radio, "volume": self._volume_left_at}

    def _volume_moved(self, volume: VolumeHud) -> None:
        self._volume_left_at = volume
        if self._buttons_of is not None:
            self._buttons_of().turn_the_radio_on()


    def _note_filters(self, filters: SlideshowFilters) -> None:
        if self._fun_time is None:
            self._filters = filters

    def pause_or_play_the_room(self) -> None:
        if self._fun_time is None:
            self._host.set_room_paused(not self._room_paused)
        elif self._session_channel is not None:
            ask_for_omnipause(self._session_channel)

    def _ask_for_the_room(self, *, paused: bool) -> None:
        if paused != self._room_paused:
            self.pause_or_play_the_room()

    def _ask_the_room_to_pause(self):
        if self._fun_time is None:
            return self._pause_or_play_the_room_while_a_slideshow_is_up
        if self._session_channel is None:
            return None
        return self.pause_or_play_the_room

    def _pause_or_play_the_room_while_a_slideshow_is_up(self) -> None:
        if self._window_up() is not None:
            self.pause_or_play_the_room()

    def _hand_to_the_funestra(self, items, shape: str, channel, showing: Showing, **kwargs):
        occupant = self.region_slideshow(shape)
        if occupant is not None:
            occupant.play(Playing(items, hud=showing.hud, versions=showing.versions, **kwargs))
            return occupant
        slideshow = FunestraSlideshow(
            Playing(items, actions=showing.actions, hud=showing.hud, versions=showing.versions,
                    opening=showing.opening, **kwargs),
            Seat(shape, channel, FrameFiles(FRAMES_BEING_MADE_DIR / shape)),
            Hosting(pace=self._pace_on(shape)))
        self._region_slideshows[shape] = slideshow
        if self._room_paused:
            slideshow.set_paused(True)
        slideshow.transport.set_has_osr2(has_the_osr2(self._huds, shape))
        return slideshow

    def _a_funestra_of_the_apps_own(self, items, shape: str, showing: Showing, **kwargs):
        program = self._own_funestras.take()
        asks = AsksFromTheFunestra(program.asks_file)
        shown = OnItsOwnFunestra(
            program, shape, showing.actions,
            OwnWiring(motion=self._motion, **self._the_audio_standing_on_its_own()), asks=asks)
        slideshow = FunestraSlideshow(
            Playing(items, actions=showing.actions, hud=showing.hud, versions=showing.versions,
                    **kwargs),
            Seat(shape, shown.channel, FrameFiles(FRAMES_BEING_MADE_DIR / "fullscreen")),
            Hosting(pace=self._pace_on(shape), shown=shown.shown_for))
        shown.setParent(slideshow)
        asks.setParent(shown)
        asks.start()
        return slideshow

    def _hand_to_the_apps_own_funestra(self, items, shape: str, showing: Showing, *,
                                       window_shape: str, **kwargs):
        self._standalone_shape = shape
        self._standalone_window_shape = window_shape
        up = self._window_up()
        if up is not None:
            up.play(Playing(items, actions=showing.actions, hud=showing.hud,
                            versions=showing.versions, **kwargs))
            self._show_on_its_monitor(up.shown)
            return up
        slideshow = self._a_funestra_of_the_apps_own(items, shape, showing, **kwargs)
        self._show_on_its_monitor(slideshow.shown)
        self._wear_the_hud(slideshow.shown, shape)
        return slideshow

    def _show_on_its_monitor(self, shown) -> None:
        if self._asked_for_by_him:
            self.two_screens.put_the_slideshow_on(self._standalone_window_shape)
        monitor = (self.two_screens.slideshows_monitor()
                   or monitor_shaped(self._standalone_window_shape)
                   or QGuiApplication.primaryScreen())
        shown.show_on(monitor)

    def _have_a_funestra_waiting(self) -> None:
        if self._fun_time is None:
            self._own_funestras.have_one_waiting()

    def _has_a_monitor_of_its_own(self) -> bool:
        return self._fun_time is None and self.two_screens.slideshows_monitor() is not None

    def _keep_a_slideshow_up(self) -> None:
        if self._has_a_monitor_of_its_own() and self._window_up() is None:
            self._asked_for_by_him = False
            try:
                self.start()
            finally:
                self._asked_for_by_him = True

    def take_key(self, event) -> bool:
        up = self._window_up() if self._has_a_monitor_of_its_own() else None
        if up is None:
            return False
        up.shown.take_key(event)
        return True

    def _leave_for_core(self, prompt_id: str | None) -> bool:
        if not self._has_a_monitor_of_its_own():
            return False
        if prompt_id:
            self._show_in_core(prompt_id)
        bring_to_front(self._host.window())
        return True

    def _show_in_core(self, prompt_id: str) -> None:
        if not self._host.reveal(prompt_id):
            self._host.follow_link(prompt_id)

    def switch_sides(self) -> None:
        if self._fun_time is None:
            self.two_screens.switch()

    def _keep_the_slideshow_off_cores_monitor(self) -> None:
        up = self._window_up() if self._fun_time is None else None
        if up is not None:
            self._standalone_window_shape = self.two_screens.slideshow_on()
            self._show_on_its_monitor(up.shown)

    def items_of(self, rows) -> list:
        return self._library().slides_of(rows)

    def versions_of(self, rows) -> dict:
        return self._library().versions_of(rows)

    def _slides_of(self, rows) -> tuple[Slide, ...]:
        return tuple(Slide.of(item) for item in self.items_of(plays_in_a_slideshow(rows)))

    def neighbors_of(self, prompt_id: str, *, shape: str) -> NavMapNeighbors:
        row = self._row_for(prompt_id) if prompt_id else None
        if row is None:
            return NavMapNeighbors()
        around = surroundings(row, self._library().on_the_map(shape),
                              image_index=self._library().image_index,
                              filed=self._groups.loops_filed_for(row, shape=shape,
                                                                 items_of=self.items_of))
        named = [(generation, label, True) for generation, label in around.configs]
        named += [(generation, label, False) for generation, label in around.actions]
        return NavMapNeighbors(
            seeds=self._slides_of(around.seeds),
            column=tuple(NavMapRow(slide, label, configuration)
                         for generation, label, configuration in named
                         for slide in self._slides_of([generation])),
            label=around.label,
            group=self._slides_of((*(generation for generation, _label in around.configs),
                                   *around.group)),
        )

    def beyond_the_row_of(self, prompt_id: str, *, shape: str) -> tuple[Slide, ...]:
        row = self._row_for(prompt_id) if prompt_id else None
        if row is None:
            return ()
        return self._slides_of(beyond_the_row(
            row, self._library().on_the_map(shape), image_index=self._library().image_index,
            filed=self._groups.loops_filed_for(row, shape=shape, items_of=self.items_of)))

    def actions_of(self, prompt_ids, *, shape: str) -> dict[str, str]:
        named_for = actions_lines(self._library().on_the_map(shape),
                               image_index=self._library().image_index)
        return {prompt_id: named_for[prompt_id] for prompt_id in prompt_ids
                if prompt_id in named_for}

    def slides_for(self, prompt_ids) -> tuple[Slide, ...]:
        return self._slides_of(row for row in map(self._db.get_generation, prompt_ids)
                               if row is not None)

    def rows_at(self, location) -> list[dict]:
        if not location:
            return []
        return self._one_per_run_where_the_order_is_newest_first(
            location, self._what_a_slideshow_may_hold(
                what_plays_at(location, self._library().rows_at(location))))

    def _what_a_slideshow_may_hold(self, rows) -> list[dict]:
        if self._fun_time is None:
            return list(rows)
        return [row for row in rows if video_kino_plays(row) is None]

    def _one_per_run_where_the_order_is_newest_first(self, location, rows) -> list[dict]:
        if not _plays_latest(location):
            return rows
        return one_per_stretch(rows, image_index=self._library().image_index)

    def hud_place(self, shape: str) -> tuple[HudCorner, bool]:
        return place_of(self._huds, shape)

    def tell_the_hud(self, shape: str, action: str, argument: str) -> None:
        told(self._huds, shape, action, argument)
        self._tell_the_slideshow_wearing_it(shape)

    def move_the_hud(self, direction: str, *, shape: str) -> None:
        moved(self._huds, shape, direction)
        self._tell_the_slideshow_wearing_it(shape)

    def collapse_the_hud(self, minimized: bool, *, shape: str) -> None:
        collapsed(self._huds, shape, minimized)
        self._tell_the_slideshow_wearing_it(shape)

    def open_the_hud_in(self, corner: HudCorner, *, shape: str) -> None:
        opened_in(self._huds, shape, corner)
        self._tell_the_slideshow_wearing_it(shape)

    def _tell_the_slideshow_wearing_it(self, shape: str) -> None:
        for surface in self.surfaces():
            if getattr(surface.shown, "hud_shape", "") == shape:
                surface.shown.set_hud_place(*self.hud_place(shape))
        slideshow = self.region_slideshow(shape)
        if slideshow is not None:
            slideshow.transport.set_has_osr2(has_the_osr2(self._huds, shape))

    def _wear_the_hud(self, shown, shape: str) -> None:
        corner, minimized = self.hud_place(shape)
        shown.wear_the_hud(shape, HudWear(
            corner=corner, minimized=minimized,
            collapse=partial(self.collapse_the_hud, shape=shape),
            open_in=partial(self.open_the_hud_in, shape=shape)))

    @property
    def _session_channel(self):
        return None if self._fun_time is None else self._fun_time.dashboard_cmd_file

    def _on_closed(self, slideshow=None):
        shape = self._shape_of(slideshow) if slideshow is not None else None
        if slideshow is not None:
            self._slideshow_state = self._where_it_stands(slideshow)
        if shape is not None:
            self._regions_left[shape] = self._left_on(slideshow)
        self._live_slideshows = [entry for entry in self._live_slideshows
                            if entry[0] is not slideshow]
        if slideshow is None or self._slideshow is slideshow:
            self._slideshow = next((s for s, _loc in reversed(self._live_slideshows)), None)
        self._osr2.reconcile()
        if shape is not None:
            self._region_slideshows[shape] = None
            self._refill_region(shape)
        self._have_a_funestra_waiting()

    def _where_it_stands(self, slideshow) -> SlideshowState:
        return replace(slideshow.state(),
                       location=next((where for live, where in self._live_slideshows
                                      if live is slideshow), None))

    def _left_on(self, slideshow) -> RegionLeft:
        return RegionLeft(self._where_it_stands(slideshow), slideshow.filters)

    def remembered_regions(self) -> dict:
        live = {shape: self._left_on(slideshow) for shape in _SHAPES
                if (slideshow := self.region_slideshow(shape)) is not None}
        return saved_regions({**self._regions_left, **live})

    def remember_regions(self, saved) -> None:
        self._regions_left = restored_regions(saved, _SHAPES)

    def _place_left(self) -> SlideshowState:
        up = _still_up(self._slideshow)
        return self._where_it_stands(up) if up is not None else self._slideshow_state

    def _place_coming_back_to(self, location, items) -> SlideshowState | None:
        place = self._place_left()
        if place.location == location or any(item[2] == place.current for item in items):
            return place
        return None

    def remembered(self) -> dict:
        state = self._place_left()
        volume = self._volume_left_at
        return {"last_show": state.saved(), "filters": SlideshowFilters.saved(self._filters),
                "panels": as_saved(self._huds), "pace": self._pace.seconds,
                "volume": None if volume is None else asdict(volume)}

    def remember(self, saved) -> None:
        if self._fun_time is not None or not isinstance(saved, dict):
            return
        self._slideshow_state = SlideshowState.restored(saved.get("last_show"))
        self._filters = SlideshowFilters.restored(saved.get("filters"))
        if type(saved.get("pace")) is int:
            self._pace.set_seconds(saved["pace"])
        self._volume_left_at = _volume_saved_as(saved.get("volume"))
        restore(self._huds, saved.get("panels"))

    def slideshow_showing_on(self) -> str | None:
        return None if self._slideshow is None else self._standalone_showing

    def held_slideshow(self) -> HeldSlideshow | None:
        slideshow = self._slideshow
        if slideshow is None:
            return None
        return HeldSlideshow(items=tuple(slideshow.whole_set()),
                        shape=self._base_side(slideshow), order_label=slideshow.hud_order_label,
                        state=self._where_it_stands(slideshow), filters=slideshow.filters)

    def _held_for_the_session(self) -> dict[str, HeldSlideshow]:
        held = self.held_slideshow()
        if held is None:
            return {}
        rows = self._rows_of(held.items)
        parts = ((shape, {row["prompt_id"] for row in filter_rows(rows, shape)})
                 for shape in _SHAPES if shape_holds(self._standalone_showing, shape))
        return {shape: _narrowed_to(held, shape, ids) for shape, ids in parts if ids}

    def _rows_of(self, slides) -> list[dict]:
        ids = (slide.prompt_id for slide in slides if slide.prompt_id is not None)
        return self._what_a_slideshow_may_hold(
            row for row in map(self._row_for, ids) if row is not None)

    def put_back(self, held: HeldSlideshow):
        return self.open(list(held.items), rows=self._rows_of(held.items),
                         location=held.state.location, shape=held.shape,
                         carrying=Carrying(resume=held.state, filters=held.filters),
                         shuffle=None if held.order_label == SHUFFLE_LABEL else in_order,
                         hud=HudFacts(order_label=held.order_label))

    def close_the_slideshows(self) -> None:
        self._regions_wanted.clear()
        self._asked_for.clear()
        self._giving_them_back = True
        try:
            for slideshow, _location in list(self._live_slideshows):
                slideshow.close()
        finally:
            self._giving_them_back = False

    def _pick_where_it_played(self, prompt_id: str):
        self._slideshow = None
        if not self._giving_them_back:
            self._show_in_core(prompt_id)

    def base_location(self, shape: str) -> str:
        return shaped_key(gallery.ALL_KEY, shape)

    def fill_the_wanted_regions(self) -> None:
        for shape in _SHAPES:
            if shape in self._regions_wanted:
                self.fill_the_region(shape)

    def fill_the_region(self, shape: str) -> None:
        self._regions_wanted.add(shape)
        asked = self._asked_for.pop(shape, None)
        if asked is not None:
            asked()
            return
        if self._put_back_what_was_taken_over(shape) or self.region_slideshow(shape) is not None:
            return
        if self._open_where_it_was_left(shape):
            return
        if not self._fill_region(shape):
            logger.info("Nothing of %s shape to open on the %s region yet", shape, shape)

    def _put_back_what_was_taken_over(self, shape: str) -> bool:
        taken = self._taken_into_the_session.pop(shape, None)
        if taken is None:
            return False
        if self.put_back(taken) is None:
            return False
        logger.info("The %s region takes up the slideshow that was up when the "
                    "session took this window over: %d items", shape, len(taken.items))
        return True

    def _open_where_it_was_left(self, shape: str) -> bool:
        left = self._regions_left.get(shape)
        if left is None:
            return False
        location = left.state.location
        ready = self._openings.of(shape) if location == self.base_location(shape) else None
        rows = ready.rows if ready is not None else self.rows_at(location)
        items = ready.items if ready is not None else self.items_of(rows)
        if not items:
            return False
        self.open(items, rows=rows, location=location, shape=shape,
                  start=_place_of(left.state.current, items),
                  carrying=Carrying(resume=left.state, filters=left.filters,
                                    versions=ready.versions if ready is not None else None),
                  **self._order(_plays_latest(location)))
        logger.info("The %s region opens where it was left: %d items", shape, len(items))
        return True

    def _fill_region(self, shape: str) -> bool:
        began = time.perf_counter()
        opening = self._openings.of(shape) or self._opening_of(self._rows_of_the_base_state(shape))
        if not opening.items:
            return False
        self.open(opening.items, rows=opening.rows, location=self.base_location(shape), shape=shape,
                  carrying=Carrying(versions=opening.versions), opening=opening)
        logger.info("The %s region opens on the library of its shape: "
                    "%d items, filled in %d ms",
                    shape, len(opening.items), (time.perf_counter() - began) * 1000)
        return True

    def _rows_of_the_base_state(self, shape: str) -> list[dict]:
        return self.rows_at(self.base_location(shape))

    @looking_once
    def _opening_of(self, rows: list[dict]) -> RegionOpening:
        items = self.items_of(rows)
        videos = [path for path, media_type, *_rest in items if media_type == MediaType.VIDEO]
        self._groups.learn(videos)
        return RegionOpening(
            rows=rows, items=items, versions=self.versions_of(rows),
            scripts={str(path): funscript_of(path, places=OUTPUT_PLACES) for path in videos},
            lead=randrange(len(items)) if items else 0)

    def _with_its_lead_on_the_map(self, opening: RegionOpening, shape: str) -> RegionOpening:
        return replace(opening, lead_neighbors=self.neighbors_of(
            opening.items[opening.lead][2], shape=shape))

    def library_moved(self) -> None:
        self._openings.library_moved()
        self.make_the_openings_ready()
        self._openings_kept_fresh.start()

    def make_the_openings_ready(self) -> None:
        for shape in _SHAPES:
            self._make_ready_what_opens_next(shape)

    def _make_ready_what_opens_next(self, shape: str) -> None:
        if (self._fun_time is not None and self._fun_time.funestra(shape) is not None
                and self.region_slideshow(shape) is None):
            self._openings.make_ready(shape)

    def _refill_region(self, shape: str) -> None:
        if shape not in self._regions_wanted or self.region_slideshow(shape) is not None:
            return
        self._fill_region(shape)

    def _shape_of(self, slideshow) -> str | None:
        return next((shape for shape, on_that_side in self._region_slideshows.items()
                     if on_that_side is slideshow), None)

    def reset_region(self, slideshow) -> None:
        shape = self._shape_of(slideshow)
        if shape is None:
            slideshow.reset_in_place()
            return
        key = self.base_location(shape)
        rows = self.rows_at(key)
        items = self.items_of(rows)
        if not items:
            slideshow.reset_in_place()
            return
        self._repoint(slideshow, key)
        slideshow.set_versions(self.versions_of(rows))
        slideshow.retune(items)

    def _repoint(self, slideshow, key: str) -> None:
        self._live_slideshows = [(live, key if live is slideshow else where)
                            for live, where in self._live_slideshows]

    def _base_side(self, slideshow) -> str | None:
        if self._fun_time is not None:
            return self._shape_of(slideshow)
        return self._standalone_shape if slideshow is self._slideshow else None

    def reorder_slideshow(self, slideshow, latest: bool) -> None:
        if not self._play_the_library(slideshow, latest=latest, keep_slide=False):
            slideshow.note_voice_command("Nothing there to play", kind=WARNING)
            return
        slideshow.note_voice_command(LATEST_LABEL if latest else SHUFFLE_LABEL)

    def browse_it_all(self, slideshow) -> bool:
        return self._play_the_library(
            slideshow, latest=slideshow.hud_order_label == LATEST_LABEL, keep_slide=True)

    def _play_the_library(self, slideshow, *, latest: bool, keep_slide: bool) -> bool:
        shape = self._base_side(slideshow)
        key = shaped_key(_LATEST_KEY, shape) if latest else self.base_location(shape)
        rows = self.rows_at(key)
        items = self.items_of(rows)
        if not items:
            return False
        self._repoint(slideshow, key)
        slideshow.set_versions(self.versions_of(rows))
        slideshow.reorder(items, latest=latest, keep_slide=keep_slide)
        return True

    def set_room_paused(self, paused: bool) -> None:
        self._room_paused = paused
        for slideshow, _where in list(self._live_slideshows):
            try:
                slideshow.set_paused(paused)
            except Exception:
                logger.exception("Freezing a slideshow failed")

    def note_finished(self, row: dict | None):
        if row is None:
            return
        self._line_up_where_it_plays(row, list(self._live_slideshows))
        self._show_where_it_was_asked_for(row)

    def note_arrived(self, rows) -> None:
        in_latest = [(slideshow, location) for slideshow, location in self._live_slideshows
                     if _plays_latest(location)]
        for row in rows:
            self._line_up_where_it_plays(row, in_latest)

    def _line_up_where_it_plays(self, row: dict, live) -> None:
        for slideshow, location in live:
            if any(r["prompt_id"] == row["prompt_id"] for r in self.rows_at(location)):
                self._hand_the_file_to(slideshow, row)

    def _show_where_it_was_asked_for(self, row: dict) -> None:
        request = self._db.get_request(row["prompt_id"])
        if not words_of(request):
            return
        for surface in self.surfaces():
            if surface.is_showing() and surface.locked_on == request["source_prompt_id"]:
                self._hand_the_file_to(surface, row)
                for path, *_rest in self.items_of([row]):
                    surface.show_locked(path)

    def note_landed(self, row: dict | None):
        if row is None:
            return
        for slideshow, _location in self._live_slideshows:
            if slideshow.holds(row["prompt_id"]):
                self._hand_the_file_to(slideshow, row)

    def _hand_the_file_to(self, slideshow, row: dict) -> None:
        for item in self.items_of([row]):
            slideshow.note_added(Slide(*item))

    def note_generating(self, prompt_id: str, frame: bytes):
        for slideshow, location in self._live_slideshows:
            if slideshow.holds(prompt_id) or self._would_play(prompt_id, location):
                slideshow.note_generating(prompt_id, frame)

    def _would_play(self, prompt_id: str, location=None) -> bool:
        row = self._run_being_made(prompt_id)
        if row is None or row.get("workflow_name") == gallery.ENHANCE_WORKFLOW:
            return False
        held = (self._library().ids_at(location) if location
                else {r["prompt_id"] for r in self._listing().rows})
        return prompt_id in held or self._latest_would_take(row, location)

    def _latest_would_take(self, row: dict, location) -> bool:
        base, shape = _split_collection_key(location)
        latest = folder_collection(base)
        if location:
            playing_latest = latest is not None and latest.which == _LATEST_KEY
        else:
            playing_latest = self._listing().latest
        return bool(playing_latest
                    and source_of(row) == GenerationSource.GENERATED
                    and filter_rows([row], shape)
                    and (latest is None or latest.folder in gallery.folder_chain(
                        row, self._library().image_index)))

    def _run_being_made(self, prompt_id: str) -> dict | None:
        row = self._runs_being_made.get(prompt_id) or self._db.get_generation(prompt_id)
        if row is not None:
            self._runs_being_made[prompt_id] = row
        return row

    def note_in_flight(self, items):
        in_flight = {item.key for item in items}
        self._runs_being_made = {prompt_id: row for prompt_id, row in self._runs_being_made.items()
                                 if prompt_id in in_flight}
        for slideshow, location in self._live_slideshows:
            self._offer_the_frames(slideshow, location, items)
            slideshow.note_in_flight(in_flight)

    def _offer_the_frames(self, slideshow, location, items) -> None:
        for item in self._runs_shown_at(location, items, slideshow):
            slideshow.note_generating(item.key, item.reading.frame)

    def _runs_shown_at(self, location, items, slideshow=None) -> list:
        return [item for item in items if item.reading.frame is not None and (
            (slideshow is not None and slideshow.holds(item.key))
            or self._would_play(item.key, location))]

    def _run_being_made_at(self, location) -> dict | None:
        shown = self._runs_shown_at(location, self._job_queue.now()[0])
        return self._db.get_generation(shown[0].key) if shown else None

    def note_enhanced(self, row: dict | None):
        if row is None:
            return
        preview = gallery.resolve_preview(row, OUTPUT_PLACES)
        if preview is None:
            return
        versions = self.versions_of([row])
        for surface in self.surfaces():
            surface.note_enhanced(row["prompt_id"], preview[0], preview[1],
                                  still=row.get("thumbnail_path"))
            surface.add_versions(versions)

    def note_versions_deleted(self, row: dict) -> None:
        preview = gallery.resolve_preview(row, OUTPUT_PLACES)
        if preview is None:
            return
        versions = self.versions_of([row])
        for surface in self.surfaces():
            surface.note_versions_deleted(row["prompt_id"], preview[0], preview[1],
                                          still=row.get("thumbnail_path"), versions=versions)

    def note_enhancing(self, statuses: dict, frames=None) -> None:
        self._enhance_status = dict(statuses)
        for surface in self.surfaces():
            surface.note_enhancing(statuses, frames)

    def note_queue(self, items, foreign_total: int) -> None:
        for slideshow in self.surfaces():
            slideshow.shown.set_queue(items, foreign_total)

    def note_voice_command(self, message: str, *, kind: str = INFO) -> None:
        if self._slideshow is not None:
            self._slideshow.note_voice_command(message, kind=kind)

    def note_voice_run(self, prompt_id: str | None, message: str, *,
                       kind: str = INFO) -> None:
        if self._slideshow is not None:
            self._slideshow.note_voice_run(prompt_id, message, kind=kind)

    def release_media(self, paths, *, the_item_stays: bool = False) -> None:
        for surface in self.surfaces():
            surface.release_media(paths, the_item_stays=the_item_stays)

    def run_slideshow_command(self, command: SlideshowCommand, shape: str | None):
        slideshow = self.surface_for(shape)
        if command is SlideshowCommand.STOP:
            if slideshow is not None and not self._leave_for_core(slideshow.hud_prompt_id):
                slideshow.close()
            return
        if command is SlideshowCommand.PAUSE:
            self._ask_for_the_room(paused=True)
            if slideshow is not None:
                slideshow.note_voice_command("slideshow paused")
            return
        self._ask_for_the_room(paused=False)
        if slideshow is None:
            self.start(shape=shape)
            return
        slideshow.note_voice_command(f"slideshow at {slideshow.dwell_s}s")

    def play_collection(self, command) -> None:
        if command.collection_key == _FAVORITES_KEY:
            self.set_favorites_filter(command.shape, True)
            return
        shape = (command.shape if command.shape and self._fun_time is not None
                else self._listing().shape)
        key = shaped_key(command.collection_key, shape)
        rows = self.rows_at(key)
        items = self.items_of(rows)
        if not items:
            return
        self.open(items, rows=rows, location=key, shape=command.shape,
                  **self._order(command.collection_key == _LATEST_KEY))

    def set_favorites_filter(self, shape, on: bool) -> None:
        slideshow = self.surface_for(shape)
        if slideshow is None:
            return
        slideshow.set_favorites_filter(on)
        slideshow.note_voice_command("Favorites on" if on else "Favorites off")

    def clear_action_filter(self, shape: str | None = None) -> None:
        slideshow = self.surface_for(shape)
        if slideshow is not None:
            slideshow.action_presses.clear_filter()

    def set_enhanced_filter(self, shape: str | None, on: bool) -> None:
        slideshow = self.surface_for(shape)
        if slideshow is None:
            return
        if not on:
            slideshow.set_enhanced_filter(False)
            slideshow.note_voice_command("Enhanceds off")
        elif slideshow.set_enhanced_filter(True) or slideshow.hud_enhanced_filter:
            slideshow.note_voice_command(f"Enhanceds — {slideshow.pass_size()} to play")
        else:
            slideshow.note_voice_command("nothing here is enhanced", kind=WARNING)


    def run_on_slide(self, command: AppCommand, said_at: float | None = None) -> None:
        slideshow = self._slideshow
        if command in _ABOUT_THE_SLIDE_SAID_OVER:
            slideshow.back_to_what_was_said_over(said_at)
        kind = INFO
        already_done = said_at is not None and slideshow.moved_on_by_itself_since(said_at)
        if command is AppCommand.BACK:
            if not already_done:
                slideshow.slideshow_step(-1)
            said = "back"
        elif command is AppCommand.FORWARD:
            if not already_done:
                slideshow.slideshow_step(1)
            said = "next"
        elif command is AppCommand.CULL:
            slideshow.cull()
            said = "gone"
        elif command is AppCommand.FAVORITE:
            said, kind = (("favorited", FAVORITE) if slideshow.favorite()
                          else ("nothing here to favorite", WARNING))
        elif command is AppCommand.LOCK:
            said, kind = (("locked this one", INFO) if slideshow.set_locked(True)
                          else ("already locked", WARNING))
        else:
            said, kind = (("let go", INFO) if slideshow.set_locked(False)
                          else ("nothing was locked", WARNING))
        self.note_voice_command(said, kind=kind)

    def _is_favorite(self, prompt_id: str) -> bool:
        return self._library().is_favorite(prompt_id)

    def _is_enhanced(self, prompt_id: str) -> bool:
        return self._library().is_enhanced_id(prompt_id)


def _plays_latest(location) -> bool:
    collection = folder_collection(_split_collection_key(location)[0])
    return collection is not None and collection.which == _LATEST_KEY


def _volume_saved_as(saved) -> VolumeHud | None:
    if (not isinstance(saved, dict) or type(saved.get("volume")) is not int
            or type(saved.get("muted")) is not bool):
        return None
    return VolumeHud(volume=saved["volume"], muted=saved["muted"])
