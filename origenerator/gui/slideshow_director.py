"""The fullscreen slideshows: opening them, placing them, feeding them, letting go.

The third of the gallery's screen concerns to come out of the view that used to
hold all of them, and the first one that owns a window. What lives here is a
slideshow's whole life -- built once however it was asked for, put on the monitor
standalone or on one of Fun Time's satellite regions, kept up with the folder it
is playing as generations land there, frozen with the room, and let go when it
closes (which puts a satellite region back on its base state).

The spoken words about a slideshow are here too -- close it, lock it, narrow it to
the favorites or to the enhanced ones, step off the slide, play a collection. They
are words about a slideshow rather than words about the microphone, and a router that
carried them would only have to hand every one of them straight back.

What stays with the host is what a slideshow is *of*: which folder or collection the
gallery is standing in, what plays from there, and what a gesture inside a slideshow
does back in the window. :class:`SlideshowHost` names each of those.
"""
from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, replace
from functools import partial
from random import randrange
from typing import Protocol

from funestra.hud_placement import HudCorner
from funestra.hud_title import LATEST_LABEL, SHUFFLE_LABEL
from funestra.modes import read_mode
from funestra.volume import VolumeHud
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QWidget
from shared_ui.orientation import orientation_of_size

from origenerator import gallery, points_of_interest
from origenerator.config import (
    EVOLVER_SOURCE,
    EVOLVER_UPSCALED_DIR,
    FRAMES_BEING_MADE_DIR,
    OUTPUT_PLACES,
)
from origenerator.evolver_upscales import EvolverUpscales
from origenerator.fun_time_bridge import ask_for_omnipause, ask_for_the_funestra
from origenerator.fun_time_mode import majority_shape, region_for_items
from origenerator.funscript import funscript_of
from origenerator.gallery.collection import (
    ENHANCED_KEY as _ENHANCED_KEY,
)
from origenerator.gallery.collection import (
    FAVORITES_KEY as _FAVORITES_KEY,
)
from origenerator.gallery.collection import (
    LATEST_KEY as _LATEST_KEY,
)
from origenerator.gallery.collection import folder_collection
from origenerator.gallery.sides import (
    ORIENTATIONS as _ORIENTATIONS,
)
from origenerator.gallery.sides import side_holds, the_one_shape_on, the_side_of
from origenerator.generation_state import GenerationSource, in_sight, source_of
from origenerator.gui.frame_files import FrameFiles
from origenerator.gui.funestra_slideshow import FunestraSlideshow
from origenerator.gui.hud_nav_map import NavMapNeighbors, NavMapRow
from origenerator.gui.message import FAVORITE, HEARD_MARK, INFO, WARNING
from origenerator.gui.region_openings import RegionOpening, RegionOpenings
from origenerator.gui.slideshow_pace import SlideshowPace
from origenerator.gui.slideshow_view import SlideshowView
from origenerator.gui.slideshow_wiring import HudFacts, SlideshowActions
from origenerator.gui.version_stepper import Version
from origenerator.item_names import ItemNames
from origenerator.media import MediaType
from origenerator.nav_map import (
    act_labels,
    beyond_the_row,
    one_per_stretch,
    surroundings,
)
from origenerator.one_look import looking_once
from origenerator.orientation import (
    filter_rows,
    oriented_key,
    row_orientation,
)
from origenerator.orientation import (
    split_key as _split_collection_key,
)
from origenerator.slideshow import (
    Slide,
    SlideshowFilters,
    SlideshowState,
    in_order,
)
from origenerator.slideshow_buttons import HUD_CORNER
from origenerator.voice.app_commands import AppCommand
from origenerator.voice.dictation import words_of
from origenerator.voice.slideshow_commands import SlideshowCommand
from origenerator.win32 import place_window_in_device_pixels
from origenerator.workflows.detail_parts import parts_framed_together

logger = logging.getLogger(__name__)

_ABOUT_THE_SLIDE_SAID_OVER = frozenset({AppCommand.CULL, AppCommand.FAVORITE, AppCommand.LOCK})

_OPENINGS_KEPT_FRESH_MS = 10 * 60 * 1000

_REGION_CAPTIONS = {"portrait": "Origenerator Portrait", "landscape": "Origenerator Landscape"}
_SWITCH_HELD_BY = {_FAVORITES_KEY: "favorites", _ENHANCED_KEY: "enhanced"}


class SlideshowHost(Protocol):
    """What the slideshows need of the gallery around them, and nothing else."""

    def slideshow_location(self) -> str | None:
        """Where the view on screen is playing FROM, as something re-askable: a
        collection key in a collection, else the open folder's key."""

    def rows_to_play(self) -> list[dict]:
        """The generations a slideshow opened from the view on screen would play."""

    def slideshow_subject(self) -> str:
        """What such a slideshow would be *of*, named the way the gallery names it."""

    def side_in_view(self) -> str:
        """Which of the two sides the tree is standing on."""

    def group_for_key(self, key: str):
        """The folder ``key`` names, as the side it is looked at from holds it."""

    def row_for(self, prompt_id: str) -> dict | None:
        """The generation row ``prompt_id`` names, or ``None``."""

    def image_config_index(self) -> dict:
        """The settings-signature index a folder name is derived against."""

    def listed_prompt_ids(self) -> list[str]:
        """The generations the Gallery pane lists, in the order shown."""

    def selected_prompt_ids(self) -> list[str]:
        """The generations picked in the Gallery pane, in the order shown."""

    def off_thread(self, work, done) -> None: ...

    def queue_now(self) -> tuple[list, int]:
        """What is in flight here, and how much of ComfyUI's queue is another
        app's -- the block a slideshow's HUD hangs at its foot."""

    def clear_foreign_queue(self) -> None:
        """Drop another app's work off ComfyUI, as that block's Clear does."""

    def start_now(self) -> None: ...

    def cancel_all(self) -> None: ...

    def window(self):
        """Core's window, which shows the Job Queue itself whenever it can be seen."""

    def follow_link(self, prompt_id: str) -> None:
        """Land on this generation: its folder, its tile, its Generate tab."""

    def show_generation(self, prompt_id: str) -> None:
        """That, with a hosting room asked for this window's place first."""

    def reveal(self, prompt_id: str) -> bool: ...

    def trash_generation(self, prompt_id: str) -> None:
        """Condemn it, as a slideshow's Up key does."""

    def favorite_generation(self, prompt_id: str, favorite: bool = True) -> None:
        """Favorite it, as a slideshow's Down key does — or take the favorite back,
        as its Up key does over a favorite."""

    def enhance_from_slideshow(self, prompt_id: str) -> bool:
        """Queue a better version of it, returning whether one was launched."""

    def toggle_osr2_drive(self) -> None:
        """Flip the one app-wide device switch, as Space does anywhere."""

    def reconcile_osr2(self) -> None:
        """Re-pick what the device follows, a surface having changed."""

    def set_room_paused(self, paused: bool) -> None:
        """Stop the room or play it again: the slideshows, the thumbnails, the sound
        and the device."""

    def say(self, message: str, *, mark: str = HEARD_MARK) -> None:
        """Flash a line on the gallery's own caption."""


@dataclass(frozen=True)
class HeldSlideshow:
    items: tuple
    side: str | None
    order_label: str
    state: SlideshowState
    filters: SlideshowFilters


class _KeptPerModel:
    def __init__(self, stamp_of):
        self._stamp_of = stamp_of
        self._stamp = None
        self._kept: dict = {}

    def get(self, key, work_out):
        stamp = self._stamp_of()
        if stamp != self._stamp:
            self._stamp, self._kept = stamp, {}
        if key not in self._kept:
            self._kept[key] = work_out()
        return self._kept[key]


def _still_up(slideshow):
    """*slideshow* if it is still on screen, else None — a closed one is no
    occupant of anything, however recently it was one."""
    return slideshow if slideshow is not None and slideshow.is_showing() else None


def _with_files(rows):
    for row in rows:
        resolved = gallery.resolve_preview(row, OUTPUT_PLACES)
        if resolved is not None:
            yield row, resolved


def _place_of(prompt_id: str, items) -> int | None:
    return next((index for index, item in enumerate(items) if item[2] == prompt_id), None)


def _screens():
    return QApplication.screens()


def _monitor_shaped(shape: str):
    return next((screen for screen in _screens()
                 if orientation_of_size(screen.geometry().width(),
                                        screen.geometry().height()) == shape), None)


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
    return replace(held, side=shape,
                   items=tuple(slide for slide in held.items if slide.prompt_id in ids),
                   state=_place_among(ids, held.state))


def _shapes_in(rows, items) -> list[str]:
    ids = {item[2] for item in items}
    return [row_orientation(row) for row in rows if row["prompt_id"] in ids]


def _side_of_the_set(rows, items) -> str | None:
    return the_side_of(_shapes_in(rows, items))


def _shape_of_the_set(rows, items) -> str:
    shapes = _shapes_in(rows, items)
    return majority_shape(shapes) if shapes else region_for_items(items)


def _shape_it_opens_on(side: str, rows, items, opened_on: str | None) -> str:
    if (row := next((row for row in rows if row["prompt_id"] == opened_on), None)) is not None:
        return row_orientation(row)
    if (shape := the_one_shape_on(side)) is not None:
        return shape
    return _shape_of_the_set(rows, items)


class SlideshowDirector:
    """Every fullscreen slideshow this window has open, and the words about them."""

    def __init__(self, host: SlideshowHost, *, db, gallery_pane, jobs, pace, motion,
                 fun_time, names: ItemNames, radio=None, turn_the_radio_on=None):
        self._host = host
        self._radio = radio
        self._turn_the_radio_on = turn_the_radio_on
        self._volume_left_at: VolumeHud | None = None
        self._db = db
        self._names = names
        self._gallery_pane = gallery_pane
        self._jobs = jobs
        self._pace = pace
        self._region_paces: dict[str, SlideshowPace] = {}
        self._motion = motion
        self._fun_time = fun_time
        # The fullscreen slideshow window while one is open — whether it was
        # started from the Gallery pane buttons (a whole folder, shuffled) or by
        # double-clicking an item (that folder in order). One place, because
        # it is one view.
        self._slideshow = None
        self._standalone_side: str | None = None
        self._standalone_shape: str | None = None
        self._standalone_showing: str | None = None
        self._hud_corners: dict[str, HudCorner] = {}
        self._hud_minimized: dict[str, bool] = {}
        # Every slideshow currently up, each with the collection/folder key it opened
        # from: what a landing generation is offered to, so a slideshow keeps up
        # with an auto-generating folder however far the Gallery pane has moved on.
        # A list rather than one, because Fun Time runs two at once.
        self._live_slideshows: list[tuple] = []
        # The regions the hosting session has handed over, until it takes
        # each back: a region it wants is never left empty -- what covers it
        # may end, but the base state comes back under it.
        self._regions_wanted: set[str] = set()
        self._openings = RegionOpenings(self._rows_of_the_base_state, self._opening_of,
                                        self._with_its_lead_on_the_map)
        self._openings_kept_fresh = QTimer()
        self._openings_kept_fresh.setInterval(_OPENINGS_KEPT_FRESH_MS)
        self._openings_kept_fresh.timeout.connect(self.make_the_openings_ready)
        # Slideshows asked for on a side the session has not handed over yet.
        self._asked_for: dict[str, partial] = {}
        # Inside Fun Time, what occupies each satellite region — a slideshow per
        # region, at most one each.  A slideshow is "open" while its window is
        # visible; a closed one just goes stale in its place until something
        # replaces it.
        self._region_slideshows: dict[str, QWidget | None] = (
            dict.fromkeys(_ORIENTATIONS) if fun_time is not None else {}
        )
        # Whether the room is paused, remembered so a slideshow opened mid-pause
        # opens frozen (see :meth:`_present_surface`).
        self._room_paused = False
        # Where the last slideshow was when it closed, so opening one comes back to
        # the slide it left off on rather than the top of a fresh shuffle.
        self._slideshow_state = SlideshowState()
        self._picked_as_the_slideshow_up_opened: tuple[str, ...] = ()
        self._filters = SlideshowFilters()
        self._enhance_status: dict[str, str] = {}
        self._held_at = _KeptPerModel(gallery_pane.model_stamp)
        self._library = _KeptPerModel(gallery_pane.model_stamp)
        self._rows_by_id = _KeptPerModel(gallery_pane.model_stamp)
        self._taken_into_the_session: dict[str, HeldSlideshow] = {}
        self._giving_them_back = False

    def become_hosted(self, session) -> None:
        self._taken_into_the_session = self._held_for_the_session()
        if self._slideshow is not None:
            self._slideshow.close()
        self._fun_time = session
        self._motion = None
        self._region_slideshows = dict.fromkeys(_ORIENTATIONS)
        self._region_paces = {}
        self.make_the_openings_ready()

    def become_standalone(self, motion) -> None:
        self._taken_into_the_session = {}
        self.close_the_slideshows()
        self._fun_time = None
        self._motion = motion
        self._region_slideshows = {}

    # --- what is up ---------------------------------------------------------

    @property
    def showing(self):
        """The slideshow in front of the user, or ``None`` with none up."""
        return self._slideshow

    def surfaces(self) -> list:
        """Every tracked full-screen surface, each once: the standalone singles
        and whatever the satellite regions hold inside Fun Time.  The
        enhancement feed and the media release address all of them — a surface
        that has since closed takes the note inertly, so nothing here polices
        visibility; only region occupancy does (see :meth:`region_slideshow`)."""
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

    def surface_for(self, side: str | None):
        """The slideshow a spoken command means: *side*'s region slideshow when it named
        one, else the slideshow that is up.

        Hosted, a named side that holds nothing is an answer in itself —
        falling back to the other region's slideshow would act on the slide the
        speaker did not name."""
        if side is not None and self._fun_time is not None:
            return self.region_slideshow(side)
        return self._slideshow

    def region_slideshow(self, side: str):
        """The slideshow occupying satellite region *side*, or None — a closed
        window is no occupant, however recently it was one."""
        return _still_up(self._region_slideshows.get(side))

    def _pace_on(self, side: str) -> SlideshowPace:
        if self._fun_time is None:
            return self._pace
        if side not in self._region_paces:
            self._region_paces[side] = SlideshowPace(self._pace.seconds)
        return self._region_paces[side]

    def _window_up(self):
        """The fullscreen window this app has on the monitor, or None — asked
        standalone, where that window is the whole of what is up."""
        return _still_up(self._slideshow)

    def anything_to_play(self) -> bool:
        """Whether the view on screen holds media a slideshow could play at all."""
        return next(_with_files(self._host.rows_to_play()), None) is not None

    # --- opening one --------------------------------------------------------

    def start(self, *, side: str | None = None):
        """Open what's on screen — a folder, or the Latest/Favorites collection —
        as a fullscreen slideshow at its side's Clip seconds, standing on the
        one generation picked there, else where the last slideshow was left
        when this comes back to it."""
        location = self._host.slideshow_location()
        base, located_on = _split_collection_key(location)
        collection = folder_collection(base)
        side = side or located_on
        # Favorites and Enhanced are not sets of their own: each is its folder
        # with its switch held down, so the switch can be let go to widen and
        # the order pair means the folder rather than what the collection lists.
        switch = _SWITCH_HELD_BY.get(collection.which) if collection is not None else None
        if switch is not None:
            side = side or self._host.side_in_view()
            location = oriented_key(collection.folder, side)
            rows = self.rows_at(location)
        else:
            rows = self._one_per_run_where_the_order_is_newest_first(
                location, self._host.rows_to_play())
        items = self.items_of(rows)
        if not items:
            return
        # Latest is Latest, exactly as on a Fun Time Funestra: the collection lists
        # newest first and its slideshow plays that order, where every other
        # set shuffles — and the slideshow's HUD title says which.  Latest
        # opens on the newest, whatever is picked or wherever the last Latest
        # slideshow stopped: the newest is what it is opened for.
        latest = collection is not None and collection.which == _LATEST_KEY
        picked = [] if latest else self._picked_since_the_slideshow_up_opened()
        one_picked = picked[0] if len(picked) == 1 else None
        resume = None if latest else self._place_coming_back_to(location, items)
        start = _place_of(one_picked, items) if one_picked is not None else None
        picked_elsewhere = (start is not None and resume is not None
                            and resume.current != one_picked)
        self.open(items, rows=rows, location=location, side=side, start=start,
                  resume=None if picked_elsewhere else resume,
                  filters=replace(self._filters, **{switch: True}) if switch else None,
                  **self._order(latest))
        logger.info("Slideshow of %s: %d items, %s",
                    self._host.slideshow_subject(), len(items),
                    "latest" if latest else "shuffled")

    def _picked_since_the_slideshow_up_opened(self) -> list[str]:
        picked = self._host.selected_prompt_ids()
        if (_still_up(self._slideshow) is not None
                and tuple(picked) == self._picked_as_the_slideshow_up_opened):
            return []
        return picked

    def _order(self, latest: bool) -> dict:
        return {"shuffle": in_order if latest else None,
                "hud": HudFacts(order_label=LATEST_LABEL if latest else SHUFFLE_LABEL,
                                favorite_ids=self._favorite_prompt_ids())}

    @looking_once
    def open_on_preview(self, media, generation):
        """A double-click on a tab's preview: open the folder of the generation
        it shows as a slideshow standing on that generation.

        The set is the folder as the gallery lists it, newest first, which is
        the order Latest plays.

        ``media`` is the file the pane is showing, or ``None`` while a generation
        is still running under it — in which case the slideshow opens on that run
        and goes on following it until it lands.
        """
        listed = self._listed_rows()
        hud = HudFacts(order_label=LATEST_LABEL, favorite_ids=self._favorite_prompt_ids())
        if media is None:  # following a run: it has no place among the files yet
            return self.open([], rows=listed, start=0, shuffle=in_order,
                             folder_items=self.items_of(listed), hud=hud)
        rows = (listed if any(row["prompt_id"] == generation for row in listed)
                else self.rows_at(self._location_of(self._host.row_for(generation))))
        opened_on = [row for row in rows if row["prompt_id"] == generation]
        items = self.items_of(opened_on)
        if not items:
            return self.open([(media[0], media[1], generation, None)], start=0, shuffle=in_order,
                             rows=[row for row in [self._host.row_for(generation)] if row],
                             hud=hud)
        side = majority_shape(map(row_orientation, rows))
        slideshow = self.open(items, rows=opened_on, start=0, side=side, shuffle=in_order,
                              hud=hud)
        if slideshow is not None and len(rows) > 1:
            self._host.off_thread(
                lambda: (self.items_of(rows), self.versions_of(rows)),
                partial(self._fill_in, slideshow, rows, generation, side=side, hud=hud))
        return slideshow

    def _listed_rows(self) -> list[dict]:
        by_id = self._rows_by_id.get(None, lambda: {
            row["prompt_id"]: row for row in self._db.list_generations()})
        rows = (by_id.get(prompt_id) or self._host.row_for(prompt_id)
                for prompt_id in self._host.listed_prompt_ids())
        return [row for row in rows if row is not None]

    def _fill_in(self, slideshow, rows, generation, folder, *, side, hud) -> None:
        if folder is None or slideshow is not self._slideshow or _still_up(slideshow) is None:
            return
        items, versions = folder
        start = _place_of(generation, items)
        if start is not None:
            self.open(items, rows=rows, start=start, side=side, shuffle=in_order, hud=hud,
                      versions=versions)

    def _location_of(self, row: dict | None) -> str | None:
        if row is None:
            return None
        key = gallery.settings_folder_key(row, self._host.image_config_index())
        return oriented_key(key, row_orientation(row))

    @looking_once
    def open(self, items, *, rows=(), folder_items=None, location=None,
             side=None, resume=None, filters=None, levels=None, **kwargs):
        """Build, wire and show a fullscreen slideshow of ``items``.

        The one place a slideshow is made, however it was asked for, so the Gallery pane buttons'
        and a double-click's differ only in the order they pass.
        ``folder_items`` is what to arm a slideshow that opened over a running
        generation with, since that one has no items of its own yet, and
        ``resume`` where a closed slideshow left off, for one picking that back up.

        ``rows`` are the library rows *items* were built from, and the folder
        rows for a live slideshow armed with one: the enhanced switch and the
        versions each item steps are both read off them, and a slideshow asked for
        them itself would be asking the library what its caller already knows.

        ``location`` is the collection or folder key the set came from, kept so the
        slideshow can be fed what lands there while it runs (:meth:`note_finished`) —
        a running slideshow has to keep up with the folder it is playing, and the
        Gallery pane will have moved on by then.  ``side`` names the satellite region
        to land it on inside Fun Time, for a slideshow asked for by side rather than
        routed by its own shape.
        """
        # Which side this slideshow belongs to: the one asked for, else the shape of
        # the run it is opened over, else the one its set's own shape belongs on.
        # Standalone it names nothing but the HUD's own verbs, since the monitor is
        # the whole screen.
        run = self._run_being_made_at(location) if not items else None
        where = side or (row_orientation(run) if run is not None
                         else _shape_of_the_set(rows, items or folder_items or []))
        # And what that side IS: one of the session's Funestras, where the session
        # handed them over, or a window of this app's over the region.
        channel = self._fun_time.funestra(where) if self._fun_time is not None else None
        follows_a_run = not items
        if follows_a_run and not folder_items and run is None:
            return None
        if (channel is not None and where not in self._regions_wanted
                and self._session_channel is not None):
            self._asked_for[where] = partial(
                self.open, items, rows=rows, folder_items=folder_items, location=location,
                side=where, resume=resume, filters=filters, **kwargs)
            ask_for_the_funestra(self._session_channel, where)
            return None
        if follows_a_run:
            items, kwargs["start"] = folder_items or [], None
        # Which of its items carry an enhancement, for the switch beside F-mode
        # on its HUD.
        opening = kwargs.pop("opening", None)
        hud = replace(kwargs.pop("hud", HudFacts()),
                      enhanced_ids=(self._enhanced_ids_of(rows) if opening is None
                                    else opening.enhanced_ids),
                      enhancing=self._enhance_status)
        # And the other axis: the versions of whichever item is on screen, which
        # the shifted step keys and the HUD's versions button walk.
        versions = self.versions_of(rows) if versions is None else versions
        actions = self._slideshow_actions(where)
        keep_the_slide = kwargs.get("start") is not None
        if channel is not None:
            slideshow = self._hand_to_the_funestra(items, where, channel, actions=actions,
                                            hud=hud, versions=versions, opening=opening, **kwargs)
        else:
            shape = (_shape_it_opens_on(where, rows, items,
                                        _item_opened_on(items, kwargs.get("start"), resume))
                     if self._fun_time is None else where)
            slideshow = self._open_a_window(items, where, shape=shape, actions=actions,
                                            hud=hud, versions=versions, **kwargs)
            if self._fun_time is None:
                self._standalone_showing = _side_of_the_set(rows, items) or shape
        self._slideshow = slideshow
        self._picked_as_the_slideshow_up_opened = tuple(self._host.selected_prompt_ids())
        already_live = any(live is slideshow for live, _where in self._live_slideshows)
        self._live_slideshows = [entry for entry in self._live_slideshows
                                 if entry[0] is not slideshow]
        self._live_slideshows.append((slideshow, location))
        if filters is None:
            filters = self._filters if self._fun_time is None else SlideshowFilters()
        slideshow.take_up(filters, keep_the_slide=keep_the_slide)
        if resume is not None:
            # After the versions a window armed above: the version a slide was
            # left showing is only a version once they are armed.
            slideshow.resume(resume, opened_on_it=keep_the_slide)
        if not keep_the_slide:
            self._offer_the_frames(slideshow, location, self._host.queue_now()[0])
            if follows_a_run:
                slideshow.follow_what_is_being_made()
            else:
                slideshow.lead_with_what_is_being_made()
        if not already_live:
            slideshow.open_requested.connect(self._pick_where_it_played)
            slideshow.closed.connect(lambda s=slideshow: self._on_closed(s))
            slideshow.media_changed.connect(self._host.reconcile_osr2)
        self._host.reconcile_osr2()
        return slideshow

    def _slideshow_actions(self, side: str) -> SlideshowActions:
        """What a press on a slideshow asks the gallery to do on its behalf, and what
        the gallery says about the library the slideshow on *side* is mapped
        against — that side's own shape of it."""
        return SlideshowActions(
            queue_now=self._host.queue_now,
            delete=self._host.trash_generation,
            enhance=self._host.enhance_from_slideshow,
            favorite=self._host.favorite_generation,
            unfavorite=partial(self._host.favorite_generation, favorite=False),
            # Two of these are a session's: a lock puts the locked item in
            # front of him, and a reset means the REGION's base state.
            lock=(self._show_the_locked_generation
                  if self._fun_time is not None else None),
            reset=(self.reset_region if self._fun_time is not None else None),
            reorder=self.reorder_slideshow,
            browse_all=self.browse_it_all,
            # The queue's own four: the block at the HUD's foot re-lines the
            # line, its Clear drops another app's work, its Start now ends a
            # video's wait and its Cancel All asks before it cancels every job.
            move=self._jobs.move,
            clear_queue=self._host.clear_foreign_queue,
            start_now=self._host.start_now,
            cancel_all=self._host.cancel_all,
            core_window=self._host.window,
            # Space reaches the one OSR2 switch, like every other surface's,
            # and the OSR2 controls' control group reads and sets that same one.
            drive_toggle=self._host.toggle_osr2_drive,
            osr2_control=self._host.osr2_control,
            omnipause=self._ask_the_room_to_pause(),
            neighbors=partial(self.neighbors_of, side=side),
            widen=partial(self.beyond_the_row_of, side=side),
            acts=partial(self.acts_of, side=side),
            slides=self.slides_for,
            move_hud=partial(self.move_the_hud, side=side),
            filters_changed=self._note_filters,
            volume_moved=self._volume_moved if self._fun_time is None else None,
        )

    def _the_sound_standing_on_its_own(self) -> dict:
        if self._fun_time is not None:
            return {}
        return {"radio": self._radio, "volume": self._volume_left_at}

    def _volume_moved(self, volume: VolumeHud) -> None:
        self._volume_left_at = volume
        if self._turn_the_radio_on is not None:
            self._turn_the_radio_on()


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

    def _hand_to_the_funestra(self, items, side: str, channel, *, actions, hud,
                            versions, opening=None, **kwargs):
        """A slideshow on one of the session's Funestras: the set goes to the Funestra
        and the HUD this app publishes goes with it — no window of ours."""
        occupant = self.region_slideshow(side)
        if occupant is not None:
            occupant.play(items, hud=hud, versions=versions, **kwargs)
            return occupant
        slideshow = FunestraSlideshow(items, side=side, channel=channel,
                          frames=FrameFiles(FRAMES_BEING_MADE_DIR / side),
                          actions=actions, pace=self._pace_on(side), hud=hud,
                          versions=versions, say=self._host.say, opening=opening, **kwargs)
        self._region_slideshows[side] = slideshow
        # A slideshow opened while the hosting session is frozen opens frozen, the
        # way a window one does.
        if self._room_paused:
            slideshow.set_paused(True)
        return slideshow

    def _open_a_window(self, items, side: str, *, shape: str, actions, hud, versions,
                       **kwargs):
        """A slideshow in a window of this app's: over the whole monitor standalone,
        or over one of the session's regions.

        Standalone the monitor holds one slideshow and only one, so a second set
        asked for while one is up re-points the window that is there rather
        than stacking another over it -- the same reuse a region's Funestra gets
        (:meth:`_hand_to_the_funestra`).  Inside a session the regions do their
        own replacing (:meth:`_present_surface`).
        """
        up = self._window_up() if self._fun_time is None else None
        view = up.shown if up is not None else None
        if self._fun_time is None:
            self._standalone_side = side
            self._standalone_shape = shape
        built = view is None
        if built:
            view = SlideshowView(items, side=side, actions=actions,
                                 pace=self._pace_on(side), motion=self._motion, hud=hud,
                                 versions=versions, **self._the_sound_standing_on_its_own(),
                                 **kwargs)
        else:
            view.slideshow.play(items, actions=actions, hud=hud, versions=versions, **kwargs)
        if built:
            self._present_surface(view, side)
        else:
            self._show_on_its_monitor(view, built=False)
        return view.slideshow

    def _show_on_its_monitor(self, view, *, built: bool) -> None:
        monitor = _monitor_shaped(self._standalone_shape)
        if monitor is not None and (built or view.screen().geometry() != monitor.geometry()):
            if view.isFullScreen():
                view.showNormal()
            area = monitor.geometry()
            view.setGeometry(area.x(), area.y(), area.width(), area.height())
            view.showFullScreen()
        elif built or view.isMinimized():
            view.showFullScreen()

    @looking_once
    def items_of(self, rows) -> list:
        """(path, media_type, prompt_id, thumbnail) for each of ``rows``, in the
        order given — the slideshow's playlist. The thumbnail is what the view
        draws for the item while it's a neighbor rather than the one on screen (a
        video has no other still). A video Evolver has upscaled plays as that
        upscale.

        A row with no file is left out, whether it never got one or is still
        being made: a slide with nothing to look at is a gap between slides,
        and one still in flight joins the running slideshow the moment it lands (see
        :meth:`note_finished`)."""
        upscales = EvolverUpscales.scan(EVOLVER_UPSCALED_DIR, EVOLVER_SOURCE)
        return [(upscales.upscale_of(path) or path, media_type, row["prompt_id"],
                 row.get("thumbnail_path"))
                for row, (path, media_type) in _with_files(rows)]

    @looking_once
    def versions_of(self, rows) -> dict:
        """Each of ``rows``' versions, newest first, keyed by the file its slide
        plays -- the axis Shift+Left/Right steps along. One with a single version
        has nothing to step between and is left out."""
        upscales = EvolverUpscales.scan(EVOLVER_UPSCALED_DIR, EVOLVER_SOURCE)
        framed_together = parts_framed_together()
        playlists = {}
        for row in rows:
            media_type = gallery.media_type_of_row(row)
            resolved = (gallery.resolve_preview(row, OUTPUT_PLACES)
                        if media_type == MediaType.VIDEO else None)
            upscale = upscales.upscale_of(resolved[0]) if resolved is not None else None
            versions = gallery.displayed_versions(row, upscale)
            if len(versions) <= 1:
                continue
            entries = [Version(gallery.output_file_path(version.file, OUTPUT_PLACES),
                               media_type, version.label,
                               points_of_interest.boxes_of(version.file, framed_together=framed_together))
                       for version in versions]
            playlists[str(entries[0][0])] = entries
        return playlists

    # --- the map around the slide on screen ---------------------------------

    def _library_of(self, side: str) -> list[dict]:
        """The generations a slideshow on *side* is mapped against: the whole
        library of that side's shape — what the Satellite Funestras map their
        videos against too, each over its own sources."""
        return self._library.get(side, lambda: filter_rows(
            [row for row in self._db.list_generations() if in_sight(row)], side))

    def _slides_of(self, rows) -> tuple[Slide, ...]:
        return tuple(Slide.of(item) for item in self.items_of(rows))

    def neighbors_of(self, prompt_id: str, *, side: str) -> NavMapNeighbors:
        """What the library says about one generation, for the map a slideshow on
        *side* draws around it: its act under other seeds along the row, and
        down the column the same seed under other configurations, then what
        else was made of its image — the videos animated from it, and for a
        video the image itself (:mod:`origenerator.nav_map`).  A
        configuration is named by its folder, as the tree names it, and the
        rest by the act each shows.  Nothing at all for a generation the
        gallery does not have a row for — a file being written, a set
        assembled without ids."""
        row = self._host.row_for(prompt_id) if prompt_id else None
        if row is None:
            return NavMapNeighbors()
        around = surroundings(row, self._library_of(side),
                              image_index=self._host.image_config_index())
        named = [(generation, self._folder_name(generation), True)
                 for generation in around.configs]
        named += [(generation, label, False) for generation, label in around.actions]
        # A generation with no file to play drops out of the column whole,
        # so its name can never end up on another row's cell.
        return NavMapNeighbors(
            seeds=self._slides_of(around.seeds),
            column=tuple(NavMapRow(slide, label, configuration)
                         for generation, label, configuration in named
                         for slide in self._slides_of([generation])),
            label=around.label or self._folder_name(row),
            group=self._slides_of((*around.configs, *around.group)),
        )

    def beyond_the_row_of(self, prompt_id: str, *, side: str) -> tuple[Slide, ...]:
        """The slides "more seeds" adds to a slideshow's row around *prompt_id*, or
        nothing when nothing lies beyond it."""
        row = self._host.row_for(prompt_id) if prompt_id else None
        if row is None:
            return ()
        return self._slides_of(beyond_the_row(
            row, self._library_of(side), image_index=self._host.image_config_index()))

    def acts_of(self, prompt_ids, *, side: str) -> dict[str, str]:
        """What the map names each of *prompt_ids* for, among the library of
        *side*'s shape — what an act filter matches a generation on.  One the
        library does not hold is left out, and answers to no act."""
        named_for = act_labels(self._library_of(side),
                               image_index=self._host.image_config_index())
        return {prompt_id: named_for[prompt_id] for prompt_id in prompt_ids
                if prompt_id in named_for}

    def slides_for(self, prompt_ids) -> tuple[Slide, ...]:
        return self._slides_of(row for row in map(self._db.get_generation, prompt_ids)
                               if row is not None)

    def rows_at(self, location) -> list[dict]:
        """What a slideshow opened at *location* would play if it opened now.

        Every key names a shape as well as a place: the collections narrow
        themselves (``rows_for_collection`` splits the key it is handed), and a
        folder row was built from one side's rows to begin with.  That is what
        lets a region's base state be "the whole library, this side's shape"
        and still be re-askable as the library grows.
        """
        if not location:
            return []
        rows = self._gallery_pane.rows_for_collection(location)
        if rows is not None:
            return self._one_per_run_where_the_order_is_newest_first(location, rows)
        group = self._host.group_for_key(location)
        return gallery.rows_under(group) if group is not None else []

    def _one_per_run_where_the_order_is_newest_first(self, location, rows) -> list[dict]:
        """Latest lists a sitting's generations one after another, several seeds
        of a configuration at a time; its slideshow plays one of each such run, and
        the map's row reaches the rest.  Every other set is shuffled, where a
        run is not a run of anything."""
        collection = folder_collection(_split_collection_key(location)[0])
        if collection is None or collection.which != _LATEST_KEY:
            return rows
        return one_per_stretch(rows, image_index=self._host.image_config_index())

    # --- putting one on screen ----------------------------------------------

    def _present_surface(self, view, side: str):
        """Put a full-screen surface on screen: over the whole monitor
        standalone, or — inside Fun Time — on the satellite region *side*,
        replacing whatever slideshow currently holds it.

        A region slideshow is frameless (the region IS the window, like every
        managed Funestra) and topmost, since the Satellite Funestra it covers is
        topmost itself; Fun Time restacks the layer as its modes change.

        Either way it ends up wearing the Funestras' HUD (:meth:`_wear_the_hud`):
        the HUD is about the slideshow, and a slideshow is a slideshow wherever it is.
        """
        if self._fun_time is None:
            self._show_on_its_monitor(view, built=True)
            self._wear_the_hud(view, side)
            return
        occupant = self._region_slideshows.get(side)
        if occupant is not None and occupant.is_showing():
            occupant.close()
        view.setWindowTitle(_REGION_CAPTIONS[side])
        view.setWindowFlags(
            view.windowFlags()
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        # Silent like every satellite: the session's Main Funestra owns the
        # room's audio, and this surface is landing on a satellite's region.
        # Standalone the same view is the deliberate foreground and plays sound.
        view.set_audio_muted(True)
        rect = self._fun_time.region_rect(side)
        # The rect as given, so the window opens at the right size and an
        # unscaled process is already correct here.
        view.setGeometry(rect.x, rect.y, rect.width, rect.height)
        view.show()
        # Then pinned in DEVICE pixels through Win32.  In a scaled process the
        # screens' logical rects overlap, so there is no logical x that lands
        # this window on a second monitor's edge at all -- see
        # origenerator.win32.place_window_in_device_pixels.  After show(),
        # because an unrealized window has no handle to place.
        place_window_in_device_pixels(int(view.winId()),
                                      rect.x, rect.y, rect.width, rect.height)
        # The slideshow answers its own keys (a slideshow's arrows, a fullscreen
        # view's paging), so it takes the keyboard the moment it opens —
        # left unfocused, those keys land in Core and the view
        # reads as dead.  raise_() first: activation alone does not lift a
        # window over the topmost Funestras it shares the region with.
        view.raise_()
        view.activateWindow()
        self._region_slideshows[side] = view.slideshow
        # A slideshow opened while the hosting session is frozen opens frozen: the
        # room's OmniPause holds everything, this surface included, from its
        # first frame — not from whenever the flag next changes.
        if self._room_paused:
            view.slideshow.set_paused(True)
        self._wear_the_hud(view, side)

    def hud_place(self, side: str) -> tuple[HudCorner, bool]:
        return (self._hud_corners.get(side, HudCorner.UPPER_LEFT),
                self._hud_minimized.get(side, False))

    def place_a_hud(self, side: str, action: str, argument: str) -> None:
        corner, minimized = self.hud_place(side)
        if action == HUD_CORNER:
            self._hud_corners[side] = read_mode(HudCorner, argument, corner)
        else:
            self._hud_minimized[side] = argument == "1"
        self._tell_the_slideshow_wearing_it(side)

    def move_the_hud(self, direction: str, *, side: str) -> None:
        self._hud_corners[side] = self.hud_place(side)[0].toward(direction)
        self._tell_the_slideshow_wearing_it(side)

    def collapse_the_hud(self, minimized: bool, *, side: str) -> None:
        self._hud_minimized[side] = minimized
        self._tell_the_slideshow_wearing_it(side)

    def open_the_hud_in(self, corner: HudCorner, *, side: str) -> None:
        self._hud_corners[side] = corner
        self._hud_minimized[side] = False
        self._tell_the_slideshow_wearing_it(side)

    def _tell_the_slideshow_wearing_it(self, side: str) -> None:
        for surface in self.surfaces():
            if getattr(surface.shown, "hud_side", "") == side:
                surface.shown.set_hud_place(*self.hud_place(side))

    def _wear_the_hud(self, view, side: str) -> None:
        """Put the Funestras' own HUD on *view* — the same HUD, rendered by the
        same shared code: the title, this side's transport, and the nav
        map speaking the set as a seed family.  The view's own furnishings come
        off with it, because the map says all of it.

        Hosted, the slideshow covers a Satellite Funestra's HUD and has to BE that
        HUD: its session commands go out on the session's channel and the mode
        pair leads the HUD.  Standalone the HUD is the same HUD minus
        those two — no channel to post on, so the transport lands on the slideshow
        itself, and no session to switch modes on, so no mode row.
        """
        corner, minimized = self.hud_place(side)
        view.wear_the_hud(side, dashboard_cmd_file=self._session_channel,
                          label_for=self._names.of, corner=corner, minimized=minimized,
                          collapse=partial(self.collapse_the_hud, side=side),
                          open_in=partial(self.open_the_hud_in, side=side))

    @property
    def _session_channel(self):
        return None if self._fun_time is None else self._fun_time.dashboard_cmd_file

    def _folder_name(self, row: dict) -> str:
        """The folder *row* sits in, by the name the tree gives it: the one the
        user typed onto it, else its short code."""
        workflow_name = row.get("workflow_name") or ""
        return gallery.config_folder_name(
            workflow_name,
            gallery.folder_signature(workflow_name, row.get("params_json"),
                                     self._host.image_config_index(),
                                     workflow_version=row.get("workflow_version")),
            self._db.folder_meta_map(),
        )

    # --- letting one go -----------------------------------------------------

    def _on_closed(self, slideshow=None):
        """A slideshow was dismissed (however): let it go, and hand the OSR2 back to
        whatever the toggle was driving. The mic is untouched — it answers to its own button,
        and "start slideshow" has to still be heard now there is no slideshow to
        hear it over.

        Named rather than assumed, because inside Fun Time two slideshows run at
        once: closing the portrait one must not forget the landscape one.
        """
        # Where it had got to, so the next one opens back on that slide: the
        # look at the folder under an item doesn't cost the place among them.
        if slideshow is not None:
            self._slideshow_state = self._where_it_stands(slideshow)
        self._live_slideshows = [entry for entry in self._live_slideshows
                            if entry[0] is not slideshow]
        side = self._side_of(slideshow) if slideshow is not None else None
        if slideshow is None or self._slideshow is slideshow:
            self._slideshow = next((s for s, _loc in reversed(self._live_slideshows)), None)
        self._host.reconcile_osr2()
        if side is not None:
            # Whatever ended it -- the loop button pressed off, a set culled
            # empty -- the region goes back to browsing its library.  The
            # Funestra under it is blacked for the whole mode, so an empty region
            # is a black rectangle, which is the one thing the base state is for.
            self._region_slideshows[side] = None
            self._refill_region(side)

    def _where_it_stands(self, slideshow) -> SlideshowState:
        return replace(slideshow.state(),
                       location=next((where for live, where in self._live_slideshows
                                      if live is slideshow), None))

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
        huds = {}
        for side in sorted(self._hud_corners.keys() | self._hud_minimized.keys()):
            corner, minimized = self.hud_place(side)
            huds[side] = {"corner": corner, "minimized": minimized}
        volume = self._volume_left_at
        return {"last_show": state.saved(), "filters": asdict(self._filters),
                "panels": huds, "pace": self._pace.seconds,
                "volume": None if volume is None else asdict(volume)}

    def remember(self, saved) -> None:
        if not isinstance(saved, dict):
            return
        self._slideshow_state = SlideshowState.restored(saved.get("last_show"))
        self._filters = SlideshowFilters.restored(saved.get("filters"))
        if type(saved.get("pace")) is int:
            self._pace.set_seconds(saved["pace"])
        self._volume_left_at = _volume_saved_as(saved.get("volume"))
        huds = saved.get("panels")
        for side, place in (huds.items() if isinstance(huds, dict) else ()):
            if isinstance(place, dict):
                self._hud_corners[side] = read_mode(HudCorner, place.get("corner"),
                                                    HudCorner.UPPER_LEFT)
                self._hud_minimized[side] = place.get("minimized") is True

    def slideshow_showing_on(self) -> str | None:
        return None if self._slideshow is None else self._standalone_showing

    def held_slideshow(self) -> HeldSlideshow | None:
        slideshow = self._slideshow
        if slideshow is None:
            return None
        return HeldSlideshow(items=tuple(slideshow.whole_set()),
                        side=self._base_side(slideshow), order_label=slideshow.hud_order_label,
                        state=self._where_it_stands(slideshow), filters=slideshow.filters)

    def _held_for_the_session(self) -> dict[str, HeldSlideshow]:
        held = self.held_slideshow()
        if held is None:
            return {}
        rows = self._rows_of(held.items)
        parts = ((shape, {row["prompt_id"] for row in filter_rows(rows, shape)})
                 for shape in _ORIENTATIONS if side_holds(self._standalone_showing, shape))
        return {shape: _narrowed_to(held, shape, ids) for shape, ids in parts if ids}

    def _rows_of(self, slides) -> list[dict]:
        ids = (slide.prompt_id for slide in slides if slide.prompt_id is not None)
        return [row for row in map(self._host.row_for, ids) if row is not None]

    def put_back(self, held: HeldSlideshow):
        return self.open(list(held.items), rows=self._rows_of(held.items),
                         location=held.state.location, side=held.side, resume=held.state,
                         filters=held.filters,
                         shuffle=None if held.order_label == SHUFFLE_LABEL else in_order,
                         hud=HudFacts(order_label=held.order_label,
                                      favorite_ids=self._favorite_prompt_ids()))

    def close_the_slideshows(self) -> None:
        """Give every slideshow back -- the session leaving origenerator mode, or
        this view going away with slideshows still up.

        The wanting is dropped first: a slideshow closing while the mode still wants
        its regions is refilled with the base state, and these closes must not
        be.
        """
        self._regions_wanted.clear()
        self._asked_for.clear()
        self._giving_them_back = True
        try:
            for slideshow, _location in list(self._live_slideshows):
                slideshow.close()
        finally:
            self._giving_them_back = False

    def close_the_slideshow(self, side: str) -> None:
        self._regions_wanted.discard(side)
        self._asked_for.pop(side, None)
        slideshow = self.region_slideshow(side)
        if slideshow is not None:
            slideshow.close()
        self._make_ready_what_opens_next(side)

    def _pick_where_it_played(self, prompt_id: str):
        """A slideshow handed its slide over on the way out: pick that item where
        the slideshow was playing, or open its own folder on it when what is on
        screen does not hold it, and put it in a tab the way a click on it would."""
        self._slideshow = None
        if not self._giving_them_back and not self._host.reveal(prompt_id):
            self._host.follow_link(prompt_id)

    def _show_the_locked_generation(self, prompt_id: str) -> None:
        if self._host.row_for(prompt_id) is None:
            return
        self._host.show_generation(prompt_id)

    # --- the satellite regions ----------------------------------------------

    def base_location(self, side: str) -> str:
        """Where a region plays from with nothing else asked for: the whole
        library, narrowed to that region's shape.

        The base state of origenerator mode, and what its reset goes back to.
        It is what the Satellite Funestras do in kino mode — each shuffles the
        whole library of its own orientation — and this side is meant to read
        the same way.
        """
        return oriented_key(gallery.ALL_KEY, side)

    def fill_the_wanted_regions(self) -> None:
        for side in _ORIENTATIONS:
            if side in self._regions_wanted:
                self.fill_the_region(side)

    def fill_the_region(self, side: str) -> None:
        self._regions_wanted.add(side)
        asked = self._asked_for.pop(side, None)
        if asked is not None:
            asked()
            return
        if self._put_back_what_was_taken_over(side) or self.region_slideshow(side) is not None:
            return
        if not self._fill_region(side):
            # Not a dead end: the tree this reads is built by the first
            # refresh, and the session's open can arrive before it (the
            # launch races the boot).  A region owed its base state gets it
            # on the next refresh -- see ``GalleryView.refresh`` -- because a
            # black rectangle is what this mode's base state exists to not be.
            logger.info("Nothing of %s shape to open on the %s region yet", side, side)

    def _put_back_what_was_taken_over(self, side: str) -> bool:
        taken = self._taken_into_the_session.pop(side, None)
        if taken is None:
            return False
        if self.put_back(taken) is None:
            return False
        logger.info("The %s region takes up the slideshow that was up when the "
                    "session took this window over: %d items", side, len(taken.items))
        return True

    def _fill_region(self, side: str) -> bool:
        """Put *side* on its base state, and say whether there was anything to
        put there.

        Timed, because what the owner judges this mode by is the wait between
        the press that opens it and the slides arriving -- and that press is
        answered on the same thread as everything else this window does, so a
        slow fill is a report about that thread rather than about how big the
        library has grown.
        """
        began = time.perf_counter()
        opening = self._openings.of(side) or self._opening_of(self._rows_of_the_base_state(side))
        if not opening.items:
            return False
        self.open(opening.items, rows=opening.rows, location=self.base_location(side), side=side,
                  hud=HudFacts(favorite_ids=self._favorite_prompt_ids()),
                  versions=opening.versions, opening=opening)
        logger.info("The %s region opens on the library of its shape: "
                    "%d items, filled in %d ms",
                    side, len(opening.items), (time.perf_counter() - began) * 1000)
        return True

    def _rows_of_the_base_state(self, side: str) -> list[dict]:
        return self.rows_at(self.base_location(side))

    @looking_once
    def _opening_of(self, rows: list[dict]) -> RegionOpening:
        items = self.items_of(rows)
        return RegionOpening(
            rows=rows, items=items, versions=self.versions_of(rows),
            enhanced_ids=self._enhanced_ids_of(rows),
            scripts={str(path): funscript_of(path, places=OUTPUT_PLACES)
                     for path, media_type, *_rest in items if media_type == MediaType.VIDEO},
            lead=randrange(len(items)) if items else 0)

    def _with_its_lead_on_the_map(self, opening: RegionOpening, side: str) -> RegionOpening:
        return replace(opening, lead_neighbors=self.neighbors_of(
            opening.items[opening.lead][2], side=side))

    def library_moved(self) -> None:
        self._openings.library_moved()
        self.make_the_openings_ready()
        self._openings_kept_fresh.start()

    def make_the_openings_ready(self) -> None:
        for side in _ORIENTATIONS:
            self._make_ready_what_opens_next(side)

    def _make_ready_what_opens_next(self, side: str) -> None:
        if (self._fun_time is not None and self._fun_time.funestra(side) is not None
                and self.region_slideshow(side) is None):
            self._openings.make_ready(side)

    def _refill_region(self, side: str) -> None:
        """Put *side* back on its base state, if the mode still wants it there.

        What a region does when the slideshow covering it ends -- the loop button
        pressed off, a set culled empty.  In origenerator mode the
        Funestra underneath is blacked for the whole mode, so a region left empty
        is a black rectangle rather than a fallback.
        """
        if side not in self._regions_wanted or self.region_slideshow(side) is not None:
            return
        self._fill_region(side)

    def _side_of(self, slideshow) -> str | None:
        """Which satellite region *slideshow* is holding, if it holds one."""
        return next((side for side, on_that_side in self._region_slideshows.items()
                     if on_that_side is slideshow), None)

    def reset_region(self, slideshow) -> None:
        """A region's reset: back to the base state, not to the top of whatever
        that region happens to be playing.

        The Funestras' own meaning of the button — reset drops the narrowing and
        leaves the satellite shuffling its whole library again — so a slideshow
        started on one folder goes back to the library of its shape.  A region
        with nothing to play there, and a slideshow holding no region at all, fall
        back to the slideshow's own reset rather than emptying the screen.
        """
        side = self._side_of(slideshow)
        if side is None:
            slideshow.reset_in_place()
            return
        key = self.base_location(side)
        rows = self.rows_at(key)
        items = self.items_of(rows)
        if not items:
            slideshow.reset_in_place()
            return
        self._repoint(slideshow, key)
        slideshow.set_versions(self.versions_of(rows))
        slideshow.retune(items, enhanced_ids=self._enhanced_ids_of(rows))

    def _repoint(self, slideshow, key: str) -> None:
        self._live_slideshows = [(live, key if live is slideshow else where)
                            for live, where in self._live_slideshows]

    def _base_side(self, slideshow) -> str | None:
        if self._fun_time is not None:
            return self._side_of(slideshow)
        return self._standalone_side if slideshow is self._slideshow else None

    def reorder_slideshow(self, slideshow, latest: bool) -> None:
        if not self._play_the_library(slideshow, latest=latest, keep_slide=False):
            slideshow.note_voice_command("Nothing there to play", kind=WARNING)
            return
        slideshow.note_voice_command(LATEST_LABEL if latest else SHUFFLE_LABEL)

    def browse_it_all(self, slideshow) -> bool:
        """The way out of a loop over a set that is one seed row: this slideshow's
        shape of the library, in the order its HUD says, from the slide up."""
        return self._play_the_library(
            slideshow, latest=slideshow.hud_order_label == LATEST_LABEL, keep_slide=True)

    def _play_the_library(self, slideshow, *, latest: bool, keep_slide: bool) -> bool:
        side = self._base_side(slideshow)
        key = oriented_key(_LATEST_KEY, side) if latest else self.base_location(side)
        rows = self.rows_at(key)
        items = self.items_of(rows)
        if not items:
            return False
        self._repoint(slideshow, key)
        slideshow.set_versions(self.versions_of(rows))
        slideshow.reorder(items, latest=latest, enhanced_ids=self._enhanced_ids_of(rows),
                     keep_slide=keep_slide)
        return True

    def set_room_paused(self, paused: bool) -> None:
        """The room's pause, applied to every open slideshow and remembered for the
        ones not opened yet (see :meth:`_present_surface`).  The gallery calls
        this on the pause's edges; the memory is what makes the freeze cover a
        slideshow the user opens mid-pause.

        Each slideshow is its own step, and one that raises must not take the rest
        with it: a freeze that stopped at the first slideshow left the others running
        with no sign of why.
        """
        self._room_paused = paused
        # Every slideshow this window has open, taken from the list it keeps of them
        # rather than from the region map: that map answers only for a slideshow it
        # considers VISIBLE, and a slideshow the session has covered or parked is
        # still a slideshow that must not go on playing through a frozen room.
        for slideshow, _where in list(self._live_slideshows):
            try:
                slideshow.set_paused(paused)
            except Exception:
                logger.exception("Freezing a slideshow failed")

    # --- keeping a running slideshow current -------------------------------------

    def note_finished(self, row: dict | None):
        """A generation landed: it joins every open slideshow that would be playing
        it had that slideshow opened now.

        Which is the whole point of watching a folder that is auto-generating —
        the playlist is otherwise the fixed set the slideshow opened with, so the
        items Auto-Generate makes while it runs are exactly the ones it never reaches.
        Asked of each slideshow's OWN location, remembered when it opened, rather
        than of the view on screen: inside Fun Time the slideshows play on the
        satellite regions while Core goes on being used, so by the
        time a generation lands the Gallery pane is usually somewhere else — and
        there may be two slideshows, of two different folders, both keeping up.
        """
        if row is None:
            return
        for slideshow, location in list(self._live_slideshows):
            if any(r["prompt_id"] == row["prompt_id"] for r in self.rows_at(location)):
                self._hand_the_file_to(slideshow, row)
        self._show_where_it_was_asked_for(row)

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
        """A run landed: every slideshow playing its frames plays its file in their
        place, wherever it opened.  Told before the run leaves the in-flight list,
        which reads to a slideshow still holding the frames as a run that stopped."""
        if row is None:
            return
        for slideshow, _location in self._live_slideshows:
            if slideshow.holds(row["prompt_id"]):
                self._hand_the_file_to(slideshow, row)

    def _hand_the_file_to(self, slideshow, row: dict) -> None:
        for item in self.items_of([row]):
            # With what the slideshow's two switches judge it by: whether it is
            # favorited, and whether it carries an enhancement.
            slideshow.note_added(*item, favorite=bool(row.get("starred")),
                                 enhanced=gallery.is_enhanced_row(row))

    def note_generating(self, prompt_id: str, frame: bytes):
        """A run streamed a frame: every open slideshow playing its folder takes it in
        as a slide of that frame, right now, and keeps it current from there.

        Waiting for the file is waiting minutes for the one thing the slideshow is
        being watched for. The first iterations are already worth looking at, so
        the run joins on its first frame and swaps for the file when it lands.

        A run the slideshow holds answers for itself, and one it turned down is
        asked again on its next frame, since the folder lists a new run a poll
        after it starts.
        """
        for slideshow, location in self._live_slideshows:
            if slideshow.holds(prompt_id) or self._would_play(prompt_id, location):
                slideshow.note_generating(prompt_id, frame)

    def _would_play(self, prompt_id: str, location=None) -> bool:
        """Whether a slideshow opened at *location* would be playing a generation
        that has no file yet — the question :meth:`note_finished` asks of its
        rows, asked a few minutes earlier.  A slideshow opened on a preview has no
        location, and is asked of the view on screen.

        A folder's slideshow answers off those rows as usual: the tree keeps a run in
        flight in the folder its settings put it in, so it is already among them.
        A collection's cannot — Latest is a collection of results and a run has none yet —
        so Latest answers for itself, by its own rule: every generation this app
        makes lands there, and this is one. The other collections are deliberate sets
        (favorited, requested, condemned) that nothing joins by being made, and a
        search's hits are a set that was already asked for.

        An enhancement is nobody's slide, wherever it is running. It is a better
        version of an image the slideshow may already be playing, and the HUD says
        so beside that image's name — a second slide of it half-rendered
        would be the same image twice, one of them worse.
        """
        row = self._db.get_generation(prompt_id)
        if row is None or row.get("workflow_name") == gallery.ENHANCE_WORKFLOW:
            return False
        held = (self._held_at_location(location) if location
                else {r["prompt_id"] for r in self._host.rows_to_play()})
        return prompt_id in held or self._latest_would_take(row, location)

    def _held_at_location(self, location) -> frozenset[str]:
        return self._held_at.get(location, lambda: frozenset(
            r["prompt_id"] for r in self.rows_at(location)))

    def _latest_would_take(self, row: dict, location) -> bool:
        base, side = _split_collection_key(location)
        latest = folder_collection(base)
        if location:
            playing_latest = latest is not None and latest.which == _LATEST_KEY
        else:
            playing_latest = (self._gallery_pane.showing_latest()
                               and not self._gallery_pane.showing_search())
        return bool(playing_latest
                    and source_of(row) == GenerationSource.GENERATED
                    and filter_rows([row], side)
                    and (latest is None or latest.folder in gallery.folder_chain(
                        row, self._host.image_config_index())))

    def note_in_flight(self, items):
        """Tell every open slideshow what is still being made, off the same in-flight
        list the queue plate in its corner is drawn from.

        Two things the frames alone can't say. A run whose frames began before the
        slideshow opened sends no new one for a while — the tail of a run is all decode
        and save — and would otherwise be missing from a slideshow of its own folder;
        and a run that was cancelled or failed sends nothing ever again, leaving
        the half-rendered frame it got to in the pass forever.
        """
        for slideshow, location in self._live_slideshows:
            self._offer_the_frames(slideshow, location, items)
            slideshow.note_in_flight({item.key for item in items})

    def _offer_the_frames(self, slideshow, location, items) -> None:
        for item in self._runs_shown_at(location, items, slideshow):
            slideshow.note_generating(item.key, item.reading.frame)

    def _runs_shown_at(self, location, items, slideshow=None) -> list:
        """The runs in flight among *items* whose frames a slideshow at *location*
        takes in, in the order it takes them."""
        return [item for item in items if item.reading.frame is not None and (
            (slideshow is not None and slideshow.holds(item.key))
            or self._would_play(item.key, location))]

    def _run_being_made_at(self, location) -> dict | None:
        shown = self._runs_shown_at(location, self._host.queue_now()[0])
        return self._db.get_generation(shown[0].key) if shown else None

    def note_enhanced(self, row: dict | None):
        """Hand a landed enhancement to every open slideshow, so the item becomes
        the better version there rather than the version it was made from.
        Every one is told; each ignores an id it isn't holding — hosted, two
        run at once on the satellite regions.

        Not only while that item is the one on screen: an enhancement asked for
        from a slideshow lands minutes later, by which time it has long paged on, so an
        upgrade it doesn't take here it never takes at all. The slideshow also draws
        each item small as a neighbor, so it takes the new thumbnail with the file.
        """
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

    def note_enhancing(self, statuses: dict, frames=None) -> None:
        self._enhance_status = dict(statuses)
        for surface in self.surfaces():
            surface.note_enhancing(statuses, frames)

    def note_queue(self, items, foreign_total: int) -> None:
        """Hand every open slideshow what is in flight, for the block its HUD hangs
        at its foot — the same line as the window's Job Queue, saying the same
        thing."""
        for slideshow in self.surfaces():
            slideshow.shown.set_queue(items, foreign_total)

    def note_voice_command(self, message: str, *, kind: str = INFO) -> None:
        """Put a spoken line in the slideshow's own message, if a slideshow is up."""
        if self._slideshow is not None:
            self._slideshow.note_voice_command(message, kind=kind)

    def note_voice_run(self, prompt_id: str | None, message: str, *,
                       kind: str = INFO) -> None:
        """Put a line about a launched run in the slideshow's own message."""
        if self._slideshow is not None:
            self._slideshow.note_voice_run(prompt_id, message, kind=kind)

    def release_media(self, paths) -> None:
        """Drop every surface's hold on ``paths`` — the files a delete is about
        to move. Windows won't move a file while a handle on it is open."""
        for surface in self.surfaces():
            surface.release_media(paths)

    # --- the spoken words about a slideshow --------------------------------------

    def answer(self, message: str, *, kind: str = INFO) -> None:
        """Say what a spoken command did, where the speaker is looking — the
        slideshow's own message while one is up, since the window under it is covered
        by the very thing being talked to, and the gallery's caption otherwise."""
        slideshow = self._slideshow
        if slideshow is not None:
            slideshow.note_voice_command(message, kind=kind)
        else:
            self._host.say(message)

    def run_slideshow_command(self, command: SlideshowCommand, side: str | None):
        """Get the slideshow going, pause the room, or close the slideshow — on
        *side*'s region when the utterance named one, else on the slideshow that
        is up."""
        slideshow = self.surface_for(side)
        if command is SlideshowCommand.STOP:
            if slideshow is None:
                self._host.say("no slideshow to close")
                return
            slideshow.close()
            self._host.say("slideshow closed")
            return
        if command is SlideshowCommand.PAUSE:
            self._ask_for_the_room(paused=True)
            if slideshow is None:
                self._host.say("paused")
            else:
                slideshow.note_voice_command("slideshow paused")
            return
        self._ask_for_the_room(paused=False)
        if slideshow is None:
            self.start(side=side)
            if self._slideshow is None:
                self._host.say("nothing here to play")
            return
        slideshow.note_voice_command(f"slideshow at {slideshow.dwell_s}s")

    def play_collection(self, command) -> None:
        """A spoken collection name, on the named side.

        "Favorites" is the exception, and it is the Funestras' own meaning: on a
        Funestra that word is F-mode — narrow what is playing to the favorites —
        so on a slideshow it is the same switch, the one its HUD draws.  Opening the
        collection as a fresh slideshow instead would answer a word the HUD already has a
        button for with something else entirely.

        The rest play: every collection belongs to one side, so a named side picks
        that side's copy and what lands on a region is homogeneous — exactly as
        it is when that collection's own slideshow button opens it — and Latest plays
        newest-first the way that collection's own slideshow does.  Standalone, and hosted
        with no side named, it is the collection on the side being browsed, the one
        the word meant.  The Gallery pane is left where it is: this starts a slideshow,
        it does not go browsing."""
        if command.collection_key == _FAVORITES_KEY:
            self.toggle_favorites_filter(command.side)
            return
        side = (command.side if command.side and self._fun_time is not None
                else self._host.side_in_view())
        key = oriented_key(command.collection_key, side)
        rows = self.rows_at(key)
        items = self.items_of(rows)
        if not items:
            self._host.say("nothing there to play")
            return
        self.open(items, rows=rows, location=key, side=command.side,
                  **self._order(command.collection_key == _LATEST_KEY))

    def toggle_favorites_filter(self, side) -> None:
        """The spoken "favorites": the slideshow's own F-mode switch, flipped.

        The same thing its HUD button does and the same thing the word does on
        a Funestra, so the readout — the lit button and the title — says so
        without anything here having to draw it."""
        slideshow = self.surface_for(side)
        if slideshow is None:
            self._host.say("F-mode needs a slideshow to narrow")
            return
        slideshow.toggle_favorites_filter()
        self._host.say("F-mode on" if slideshow.hud_favorites_filter else "F-mode off")

    def filter_enhanced(self, enhanced_only: bool, side: str | None = None):
        """Narrow the slideshow in front of the speaker to its enhanced images, or
        put them all back — the switch beside F-mode on its HUD, spoken.

        The slideshow's own switch, like the spoken "favorites": a word that set
        some other filter would leave the HUD's button dark over a narrowed
        slideshow. Hosted, a named side takes that region's slideshow, since two run at
        once and neither is the active window. With no slideshow up there is nothing
        for the word to narrow, and it says so rather than arming something.

        Answered with what is left rather than with the switch's name: a speaker
        who has just narrowed a slideshow wants to know there is still something in
        it, and "nothing here is enhanced" is the one answer worth hearing at
        once. Said even when the switch was already that way — a word that did
        nothing and said nothing reads as a mic that missed it.

        Turning it off takes F-mode and the act filter with it: said to a
        slideshow, "clear filter" is the way out of ALL of the narrowing.
        """
        slideshow = self.surface_for(side)
        if slideshow is None:
            self._host.say("the filter needs a slideshow to narrow")
            return
        if not enhanced_only:
            slideshow.clear_modes()
            slideshow.note_voice_command("showing all of them")
            return
        if slideshow.set_enhanced_mode(True) or slideshow.hud_enhanced_mode:
            slideshow.note_voice_command(
                f"enhanced only — {slideshow.pass_size()} to play")
        else:
            slideshow.note_voice_command("nothing here is enhanced", kind=WARNING)

    def run_on_slide(self, command: AppCommand, said_at: float | None = None) -> None:
        """A word about the slide filling the screen: step off it either way,
        take it away, lock it, or favorite it.

        The words are Fun Time's, and so is what they do — "weird" condemns what
        was on screen when it was said, a lock holds it — because the two rooms are
        one room to whoever is speaking, and a word that means one thing there and
        another here is a word nobody can use.
        """
        slideshow = self._slideshow
        if command in _ABOUT_THE_SLIDE_SAID_OVER:
            slideshow.back_to_what_was_said_over(said_at)
        kind = INFO
        if command is AppCommand.BACK:
            slideshow.slideshow_step(-1)
            said = "back"
        elif command is AppCommand.FORWARD:
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
        else:  # UNLOCK
            said, kind = (("let go", INFO) if slideshow.set_locked(False)
                          else ("nothing was locked", WARNING))
        self.answer(said, kind=kind)

    # --- what the HUD's two switches judge items by -------------------------

    def _favorite_prompt_ids(self) -> set[str]:
        """Which generations are favorites, for the slideshows' HUD: the star readout
        on the current item, and the favorites narrowing — the same concepts the
        Funestras' HUD wears, over the same items the Favorites collection lists.

        Those items, and not merely the marked rows: a folder favorited
        there stands for everything under it, so a slideshow narrowed to the
        favorites keeps what the collection would have shown.
        """
        marked = {row["prompt_id"] for row in self._db.list_generations()
                  if row.get("starred")}
        for side in _ORIENTATIONS:
            key = oriented_key(_FAVORITES_KEY, side)
            marked.update(row["prompt_id"]
                          for row in (self._gallery_pane.rows_for_collection(key) or ()))
        return marked

    def _enhanced_ids_of(self, rows) -> set[str]:
        """Which of *rows* carry an enhancement, for the switch beside F-mode
        on a slideshow's HUD — the question the thumbnails' yellow plus answers."""
        return {row["prompt_id"] for row in rows if gallery.is_enhanced_row(row)}


def _volume_saved_as(saved) -> VolumeHud | None:
    if (not isinstance(saved, dict) or type(saved.get("volume")) is not int
            or type(saved.get("muted")) is not bool):
        return None
    return VolumeHud(volume=saved["volume"], muted=saved["muted"])
