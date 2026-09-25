"""The fullscreen shows: opening them, placing them, feeding them, letting go.

The third of the gallery's screen concerns to come out of the view that used to
hold all of them, and the first one that owns a window. What lives here is a
show's whole life -- built once however it was asked for, put on the monitor
standalone or on one of Fun Time's satellite regions, kept up with the folder it
is playing as generations land there, frozen with the room, and let go when it
closes (which puts a satellite region back on its base state).

The eight pieces of state a show needs are here and only here: the show that is
up, the shape a show on its own was opened on, every show that is up (hosted,
two run at once), what each satellite region holds, whether the session still
wants its regions filled, whether the room is frozen, where the last show left
off, and how the enhancements in flight are going.

The spoken words about a show are here too -- close it, lock it, narrow it to
the favorites or to the enhanced ones, step off the slide, play a shelf. They
are words about a show rather than words about the microphone, and a router that
carried them would only have to hand every one of them straight back.

What stays with the host is what a show is *of*: which folder or shelf the
gallery is standing in, what plays from there, and what a gesture inside a show
does back in the window. :class:`ShowHost` names each of those.
"""
from __future__ import annotations

import logging
import time
from dataclasses import replace
from functools import partial
from typing import Protocol

from player_core.hud_status import LATEST_LABEL, SHUFFLE_LABEL
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QWidget

from origenerator import gallery
from origenerator.config import COMFYUI_OUTPUT_DIR, EVOLVER_SOURCE, EVOLVER_UPSCALED_DIR
from origenerator.evolver_upscales import EvolverUpscales
from origenerator.fun_time_bridge import ask_for_omnipause
from origenerator.fun_time_mode import SHOW_TITLES, region_for_items
from origenerator.gallery.shelves import (
    FAVORITES_KEY as _FAVORITES_KEY,
)
from origenerator.gallery.shelves import (
    RECENTS_KEY as _RECENTS_KEY,
)
from origenerator.gallery.shelves import folder_shelf
from origenerator.generation_state import GenerationSource, source_of
from origenerator.gui.notice_overlay import FAVORITE, NOTICE, WARNING
from origenerator.gui.player_show import PlayerShow
from origenerator.gui.show_hud import ShowHud
from origenerator.gui.show_map import MapNeighbors, MapRow
from origenerator.gui.show_wiring import HudFacts, ShowActions
from origenerator.gui.slideshow_view import SlideshowView
from origenerator.media import MediaType
from origenerator.nav_map import (
    act_labels,
    beyond_the_row,
    one_per_stretch,
    surroundings,
)
from origenerator.orientation import (
    ORIENTATIONS as _ORIENTATIONS,
)
from origenerator.orientation import (
    filter_rows,
    oriented_key,
    row_orientation,
)
from origenerator.orientation import (
    split_key as _split_shelf_key,
)
from origenerator.slideshow import DEFAULT_IMAGE_DWELL_MS, ShowState, Slide, in_order
from origenerator.voice.app_commands import AppCommand
from origenerator.voice.show_commands import ShowCommand
from origenerator.win32 import place_window_in_device_pixels

logger = logging.getLogger(__name__)


class ShowHost(Protocol):
    """What the shows need of the gallery around them, and nothing else."""

    def show_location(self) -> str | None:
        """Where the view on screen is playing FROM, as something re-askable: a
        shelf key on a shelf, else the open folder's key."""

    def rows_to_play(self) -> list[dict]:
        """The generations a show opened from the view on screen would play."""

    def slideshow_subject(self) -> str:
        """What such a show would be *of*, named the way the gallery names it."""

    def side_in_view(self) -> str:
        """Which of the two sides the tree is standing on."""

    def group_for_key(self, key: str):
        """The folder ``key`` names, as the side it is looked at from holds it."""

    def media_types(self) -> set[str]:
        """The media types the gallery's two ticks currently include."""

    def row_for(self, prompt_id: str) -> dict | None:
        """The generation row ``prompt_id`` names, or ``None``."""

    def image_config_index(self) -> dict:
        """The settings-signature index a folder name is derived against."""

    def visible_prompt_ids(self) -> list[str]:
        """The generations the browser lists, in the order shown."""

    def queue_now(self) -> tuple[list, int]:
        """What is in flight here, and how much of ComfyUI's queue is another
        app's -- the plate a show floats in its corner."""

    def clear_foreign_queue(self) -> None:
        """Drop another app's work off ComfyUI, as that plate's Clear does."""

    def follow_link(self, prompt_id: str) -> None:
        """Land on this generation: its folder, its tile, its config tab."""

    def trash_generation(self, prompt_id: str) -> None:
        """Condemn it, as a show's Up key does."""

    def favorite_generation(self, prompt_id: str, favorite: bool = True) -> None:
        """Bookmark it, as a show's Down key does — or take the bookmark back,
        as its Up key does over a favorite."""

    def enhance_from_slideshow(self, prompt_id: str) -> bool:
        """Queue a better version of it, returning whether one was launched."""

    def toggle_osr2_drive(self) -> None:
        """Flip the one app-wide device switch, as Space does anywhere."""

    def reconcile_osr2(self) -> None:
        """Re-pick what the device follows, a surface having changed."""

    def say(self, message: str) -> None:
        """Flash a line on the gallery's own caption."""


def _still_up(show):
    """*show* if it is still on screen, else None — a closed one is no
    occupant of anything, however recently it was one."""
    return show if show is not None and show.is_showing() else None


class ShowDirector:
    """Every fullscreen show this window has open, and the words about them."""

    def __init__(self, host: ShowHost, *, db, browser, jobs, pace, motion,
                 fun_time):
        self._host = host
        self._db = db
        self._browser = browser
        self._jobs = jobs
        self._pace = pace
        self._motion = motion
        self._fun_time = fun_time
        # The fullscreen slideshow window while one is open — whether it was
        # started from the toolbar (a whole folder, shuffled) or by
        # double-clicking a picture (that folder in order, held at a pace of
        # nought). One slot, because it is one view.
        self._slideshow = None
        self._standalone_side: str | None = None
        # Every show currently up, each with the shelf/folder key it opened
        # from: what a landing generation is offered to, so a show keeps up
        # with an auto-generating folder however far the browser has moved on.
        # A list rather than one, because Fun Time runs two at once.
        self._live_shows: list[tuple] = []
        # Whether the hosting session has asked for its regions (OPEN_SHOWS,
        # until CLOSE_SHOWS): a region it wants is never left empty -- what
        # covers it may end, but the base state comes back under it.
        self._regions_wanted = False
        # Inside Fun Time, what occupies each satellite region — a show per
        # region, at most one each.  A show is "open" while its window is
        # visible; a closed one just goes stale in its slot until something
        # replaces it.
        self._region_shows: dict[str, QWidget | None] = (
            dict.fromkeys(_ORIENTATIONS) if fun_time is not None else {}
        )
        # Whether the hosting session is OmniPaused, remembered so a show
        # opened mid-pause opens frozen (see :meth:`_present_surface`).
        self._session_paused = False
        # Where the last show was when it closed, so opening one comes back to
        # the slide it left off on rather than the top of a fresh shuffle.
        self._show_state = ShowState()
        self._enhance_status: dict[str, str] = {}

    def become_hosted(self, session) -> None:
        if self._slideshow is not None:
            self._slideshow.close()
        self._fun_time = session
        self._motion = None
        self._region_shows = dict.fromkeys(_ORIENTATIONS)

    def become_standalone(self, motion) -> None:
        self.close_the_shows()
        self._fun_time = None
        self._motion = motion
        self._region_shows = {}

    # --- what is up ---------------------------------------------------------

    @property
    def showing(self):
        """The show in front of the user, or ``None`` with none up."""
        return self._slideshow

    @property
    def regions_wanted(self) -> bool:
        """Whether the hosting session still wants its regions filled."""
        return self._regions_wanted

    def surfaces(self) -> list:
        """Every tracked full-screen surface, each once: the standalone singles
        and whatever the satellite regions hold inside Fun Time.  The
        enhancement feed and the media release address all of them — a surface
        that has since closed takes the note inertly, so nothing here polices
        visibility; only region occupancy does (see :meth:`region_show`)."""
        candidates = [self._slideshow, *self._region_shows.values()]
        surfaces, seen = [], set()
        for surface in candidates:
            if surface is None or id(surface) in seen:
                continue
            seen.add(id(surface))
            surfaces.append(surface)
        return surfaces

    def surface_for(self, side: str | None):
        """The show a spoken command means: *side*'s region show when it named
        one, else the show that is up.

        Hosted, a named side that holds nothing is an answer in itself —
        falling back to the other region's show would act on the picture the
        speaker did not name."""
        if side is not None and self._fun_time is not None:
            return self.region_show(side)
        return self._slideshow

    def region_show(self, side: str):
        """The show occupying satellite region *side*, or None — a closed
        window is no occupant, however recently it was one."""
        return _still_up(self._region_shows.get(side))

    def _window_up(self):
        """The fullscreen window this app has on the monitor, or None — asked
        standalone, where that window is the whole of what is up."""
        return _still_up(self._slideshow)

    def is_in_front(self) -> bool:
        """True when the window ahead of the gallery is our own fullscreen
        slideshow — one of the things Esc turns off, rather than a window to hand
        the key back to. A dialog or popup over the show still owns it."""
        if self._slideshow is None:
            return False
        if QApplication.activeModalWidget() or QApplication.activePopupWidget():
            return False
        return QApplication.activeWindow() is self._slideshow

    def anything_to_play(self) -> bool:
        """Whether the view on screen holds media a show could play at all."""
        return bool(self.items_of(self._host.rows_to_play()))

    # --- opening one --------------------------------------------------------

    def start(self, *, side: str | None = None):
        """Open what's on screen — a folder, or the Latest/Favorites shelf —
        as a fullscreen slideshow, shuffled and running at the app-wide pace,
        and standing where the last show was closed when that slide is in
        here."""
        location = self._host.show_location()
        base, orientation = _split_shelf_key(location)
        shelf = folder_shelf(base)
        side = side or orientation
        # Favorites is not a set of its own: it is its folder with the
        # favorites switch held down, so the switch can be let go to widen and
        # the order pair means the folder rather than the bookmarks.
        favorites = shelf is not None and shelf.shelf == _FAVORITES_KEY
        if favorites:
            side = side or self._host.side_in_view()
            location = oriented_key(shelf.folder, side)
            rows = self.rows_at(location)
        else:
            rows = self._one_per_run_where_the_order_is_newest_first(
                location, self._host.rows_to_play())
        items = self.items_of(rows)
        if not items:
            return
        # Recents is Latest, exactly as on a Fun Time player: the shelf lists
        # newest first and its slideshow plays that order, where every other
        # set shuffles — and the show's HUD status line says which.  Latest
        # opens on the newest rather than where the last Latest show stopped:
        # the newest is what it is opened for.
        latest = shelf is not None and shelf.shelf == _RECENTS_KEY
        show = self.open(items, rows=rows, location=location, side=side,
                         resume=None if latest else self._show_state,
                         **self._order(latest))
        if favorites:
            show.set_favorites_filter(True)
        logger.info("Slideshow of %s: %d items, %s",
                    self._host.slideshow_subject(), len(items),
                    "latest" if latest else "shuffled")

    def _order(self, latest: bool) -> dict:
        return {"shuffle": in_order if latest else None,
                "hud": HudFacts(order_label=LATEST_LABEL if latest else SHUFFLE_LABEL,
                                favorite_ids=self._favorite_prompt_ids())}

    def open_on_preview(self, media, frame, generation):
        """A double-click on a tab's preview: open the folder of the generation
        it shows as a slideshow standing on that generation.

        The pace is nought — nothing moves until an arrow does, or until the
        console's clip-seconds pair is turned up — and the order is the browser's
        rather than a shuffle, because this is the folder you were already looking
        at rather than a set to be played. That is the whole of what used to be a
        second fullscreen viewer: the arrows, the counter, the neighbor stills,
        Up and Down, are the show's own.

        ``media`` is the file the pane is showing, or ``None`` while a generation
        is still running under it — in which case the show opens over ``frame``,
        that run's latest, and goes on following it until the pane hands over the
        file it lands as.
        """
        listed = self._folder_rows()
        folder_items = None
        if media is None:  # following a run: it has no place among the files yet
            items, rows, start, folder_items = [], listed, 0, self.items_of(listed)
        else:
            rows = (listed if any(row["prompt_id"] == generation for row in listed)
                    else self.rows_at(self._location_of(self._host.row_for(generation))))
            items = self.items_of(rows)
            start = next((i for i, item in enumerate(items) if item[2] == generation),
                         None)
            if start is None:
                items, start = [(media[0], media[1], generation, None)], 0
                rows = [row for row in [self._host.row_for(generation)] if row is not None]
        # Neither shuffled nor newest-first, and not a loop: this is one folder
        # in the browser's own order, held on one picture.  Said plainly rather
        # than left at the defaults, because the HUD reads them now — an order
        # slot saying "Shuffle" over a folder listed in its own order would be
        # the panel making something up.
        return self.open(items, rows=rows, start=start, frame=frame,
                         image_dwell_ms=0, shuffle=in_order,
                         folder_items=folder_items,
                         hud=HudFacts(
                             order_label="",
                             favorite_ids=self._favorite_prompt_ids()))

    def _folder_rows(self) -> list[dict]:
        """The rows the browser lists, in its order."""
        rows = (self._host.row_for(pid) for pid in self._host.visible_prompt_ids())
        return [row for row in rows if row is not None]

    def _location_of(self, row: dict | None) -> str | None:
        if row is None:
            return None
        key = gallery.settings_folder_key(row, self._host.image_config_index())
        return oriented_key(key, row_orientation(row))

    def open(self, items, *, rows=(), folder_items=None, location=None,
             side=None, resume=None, **kwargs):
        """Build, wire and show a fullscreen slideshow of ``items``.

        The one place a show is made, however it was asked for, so the toolbar's
        and a double-click's differ only in the order and the pace they pass.
        ``folder_items`` is what to arm a show that opened over a running
        generation with, since that one has no items of its own yet, and
        ``resume`` where a closed show left off, for one picking that back up
        rather than naming its own opening slide.

        ``rows`` are the library rows *items* were built from, and the folder
        rows for a live show armed with one: the enhanced switch and the
        versions each item steps are both read off them, and a show asked for
        them itself would be asking the library what its caller already knows.

        ``location`` is the shelf or folder key the set came from, kept so the
        show can be fed what lands there while it runs (:meth:`note_finished`) —
        a running show has to keep up with the folder it is playing, and the
        browser will have moved on by then.  ``side`` names the satellite region
        to land it on inside Fun Time, for a show asked for by side rather than
        routed by its own shape.
        """
        # Which side this show belongs to: the one asked for, else the one this
        # set's own shape belongs on.  Standalone it names nothing but the
        # panel's own verbs, since the monitor is the whole screen.
        where = side or region_for_items(items)
        # And what that side IS: one of the session's players, where the session
        # handed them over, or a window of this app's over the region.
        channel = self._fun_time.player(where) if self._fun_time is not None else None
        if channel is not None and not items:
            return None  # a player is handed files, and a run being made has none yet
        # Which of its items carry an enhancement, for the switch beside F-mode
        # on its HUD.
        hud = replace(kwargs.pop("hud", HudFacts()),
                      enhanced_ids=self._enhanced_ids_of(rows),
                      enhancing=self._enhance_status)
        # And the other axis: the versions of whichever item is on screen, which
        # the shifted step keys and the band's versions button walk.
        levels = self.versions_of(rows)
        actions = self._show_actions(where)
        if channel is not None:
            show = self._hand_to_the_player(items, where, channel, actions=actions,
                                            hud=hud, levels=levels, **kwargs)
        else:
            show = self._open_a_window(items, where, actions=actions, hud=hud,
                                       levels=levels,
                                       folder_items=folder_items, **kwargs)
        self._slideshow = show
        already_live = any(live is show for live, _where in self._live_shows)
        self._live_shows = [entry for entry in self._live_shows if entry[0] is not show]
        self._live_shows.append((show, location))
        if resume is not None:
            # After the levels a window armed above: the version a slide was
            # left showing is only a version once they are armed.
            show.resume(resume)
        if kwargs.get("start") is None:
            self._offer_the_frames(show, self._host.queue_now()[0])
            show.lead_with_what_is_being_made()
        if not already_live:
            show.open_requested.connect(self._open_from_slideshow)
            show.closed.connect(lambda s=show: self._on_closed(s))
            show.media_changed.connect(self._host.reconcile_osr2)
        self._host.reconcile_osr2()
        # However the show was asked for, it now owns the card it is drawn with: a
        # video generation would saturate that card, and a show is exactly the
        # stretch when nobody is waiting on a video. The queue holds them until it
        # closes and keeps making images.
        self._jobs.hold_videos(True)
        return show

    def _show_actions(self, side: str) -> ShowActions:
        """What a press on a show asks the gallery to do on its behalf, and what
        the gallery says about the library the show on *side* is mapped
        against — that side's own shape of it."""
        return ShowActions(
            delete=self._host.trash_generation,
            enhance=self._host.enhance_from_slideshow,
            favorite=self._host.favorite_generation,
            unfavorite=partial(self._host.favorite_generation, favorite=False),
            # Three of these are a session's: a lock opens the locked item as a
            # generate tab, a reset means the REGION's base state, and a click
            # on the picture asks the room to pause.
            lock=(self._open_generate_tab_for
                  if self._fun_time is not None else None),
            reset=(self.reset_region if self._fun_time is not None else None),
            reorder=self.reorder_show,
            # Space reaches the one OSR2 switch, like every other surface's,
            # and the console's control group reads and sets that same one.
            drive_toggle=self._host.toggle_osr2_drive,
            osr2_control=self._host.osr2_control,
            omnipause=(partial(ask_for_omnipause, self._session_channel)
                       if self._session_channel is not None else None),
            neighbors=partial(self.neighbors_of, side=side),
            widen=partial(self.beyond_the_row_of, side=side),
            acts=partial(self.acts_of, side=side),
        )

    def _hand_to_the_player(self, items, side: str, channel, *, actions, hud,
                            levels, **kwargs):
        """A show on one of the session's players: the set goes to the player
        and the panel this app publishes goes with it — no window of ours.

        A frame is dropped on the way in: a player is handed files to play, and
        a generation still being made has none yet.
        """
        kwargs.pop("frame", None)
        occupant = self.region_show(side)
        if occupant is not None:
            occupant.play(items, hud=hud, **kwargs)
            occupant.set_levels(levels)
            return occupant
        show = PlayerShow(items, side=side, channel=channel,
                          actions=actions, pace=self._pace, hud=hud,
                          say=self._host.say, **kwargs)
        show.set_levels(levels)
        self._region_shows[side] = show
        # A show opened while the hosting session is frozen opens frozen, the
        # way a window one does.
        if self._session_paused:
            show.set_paused(True)
        return show

    def _open_a_window(self, items, side: str, *, actions, hud, levels,
                       folder_items=None, **kwargs):
        """A show in a window of this app's: over the whole monitor standalone,
        or over one of the session's regions.

        Standalone the monitor holds one show and only one, so a second set
        asked for while one is up re-points the window that is there rather
        than stacking another over it -- the same reuse a region's player gets
        (:meth:`_hand_to_the_player`).  Inside a session the regions do their
        own replacing (:meth:`_present_surface`).
        """
        view = self._window_up() if self._fun_time is None else None
        built = view is None
        if built:
            view = SlideshowView(items, actions=actions,
                                 pace=self._pace, motion=self._motion, hud=hud,
                                 **kwargs)
        else:
            view.play(items, actions=actions, hud=hud, **kwargs)
        if folder_items and view.is_live():
            # Watching something render is no reason to lose the folder it is
            # being made in: the first arrow leaves the live frames for it.
            view.set_playlist(folder_items, 0)
        # Shift+Left/Right gets its own axis, so a level can be compared against
        # the one below it at full size rather than in a thumbnail.
        view.set_levels(levels)
        if built:
            self._present_surface(view, side)
            # The queue it floats in its corner is the same widget as the lower
            # strip and asks for the same things, so it goes to the same
            # handlers: a row dragged there re-lines the queue, and its Clear
            # drops another app's work off ComfyUI.
            view.queue().reorder_requested.connect(self._jobs.reorder)
            view.queue().clear_queue_requested.connect(self._host.clear_foreign_queue)
            # And fill it at once rather than a poll later: the hold on videos is
            # this opening's own doing, so the corner comes up already saying what
            # is waiting on it rather than blank for a second and a half.
            view.set_queue(*self._host.queue_now())
        return view

    def items_of(self, rows) -> list:
        """(path, media_type, prompt_id, thumbnail) for each of ``rows``, in the
        order given — the slideshow's playlist. The thumbnail is what the view
        draws for the item while it's a neighbor rather than the one on screen (a
        video has no other still). A video Evolver has upscaled plays as that
        upscale.

        A row with no file is left out, whether it never got one or is still
        being made: a slide with nothing to look at is a gap between pictures,
        and one still in flight joins the running show the moment it lands (see
        :meth:`note_finished`)."""
        upscales = EvolverUpscales.scan(EVOLVER_UPSCALED_DIR, EVOLVER_SOURCE)
        items = []
        for row in rows:
            resolved = gallery.resolve_preview(row, COMFYUI_OUTPUT_DIR)
            if resolved is None:
                continue  # nothing to look at yet, or ever
            path, media_type = resolved
            items.append((upscales.upscale_of(path) or path, media_type, row["prompt_id"],
                          row.get("thumbnail_path")))
        return items

    def versions_of(self, rows) -> dict:
        """Each of ``rows``' versions, newest first, keyed by the file its slide
        plays -- the axis Shift+Left/Right steps along. One with a single version
        has nothing to step between and is left out."""
        upscales = EvolverUpscales.scan(EVOLVER_UPSCALED_DIR, EVOLVER_SOURCE)
        playlists = {}
        for row in rows:
            media_type = gallery.media_type_of_row(row)
            resolved = (gallery.resolve_preview(row, COMFYUI_OUTPUT_DIR)
                        if media_type == MediaType.VIDEO else None)
            upscale = upscales.upscale_of(resolved[0]) if resolved is not None else None
            levels = gallery.displayed_levels(row, upscale)
            if len(levels) < 2:
                continue
            entries = [(gallery.output_file_path(level.file, COMFYUI_OUTPUT_DIR),
                        media_type, level.label) for level in levels]
            playlists[str(entries[0][0])] = entries
        return playlists

    # --- the map around the slide on screen ---------------------------------

    def _library_of(self, side: str) -> list[dict]:
        """The generations a show on *side* is mapped against: the whole
        library of that side's shape — what the satellite players map their
        clips against too, each over its own sources.  Every generation of
        that shape, whatever the gallery's two ticks are showing: the ticks
        narrow what is browsed, and a map is drawn against what exists."""
        return filter_rows(self._db.list_generations(), side)

    def _slides_of(self, rows) -> tuple[Slide, ...]:
        return tuple(Slide.of(item) for item in self.items_of(rows))

    def neighbors_of(self, prompt_id: str, *, side: str) -> MapNeighbors:
        """What the library says about one generation, for the map a show on
        *side* draws around it: its act under other seeds along the row, and
        down the column the same seed under other configurations, then what
        else was made of its picture — the videos animated from it, and for a
        video the picture itself (:mod:`origenerator.nav_map`).  A
        configuration is named by its folder, as the tree names it, and the
        rest by the act each shows.  Nothing at all for a generation the
        gallery does not have a row for — a file being written, a set
        assembled without ids."""
        row = self._host.row_for(prompt_id) if prompt_id else None
        if row is None:
            return MapNeighbors()
        around = surroundings(row, self._library_of(side),
                              image_index=self._host.image_config_index())
        named = [(generation, self._folder_name(generation), True)
                 for generation in around.configs]
        named += [(generation, label, False) for generation, label in around.actions]
        # A generation with no file to play drops out of the column whole,
        # so its name can never end up on another row's cell.
        return MapNeighbors(
            seeds=self._slides_of(around.seeds),
            column=tuple(MapRow(slide, label, configuration)
                         for generation, label, configuration in named
                         for slide in self._slides_of([generation])),
            label=around.label or self._folder_name(row),
            group=self._slides_of((*around.configs, *around.group)),
        )

    def beyond_the_row_of(self, prompt_id: str, *, side: str) -> tuple[Slide, ...]:
        """The slides "more seeds" adds to a show's row around *prompt_id*, or
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

    def rows_at(self, location) -> list[dict]:
        """What a show opened at *location* would play if it opened now.

        Every key names a shape as well as a place: the shelves narrow
        themselves (``rows_for_shelf`` splits the key it is handed), and a
        folder row was built from one side's rows to begin with.  That is what
        lets a region's base state be "the whole library, this side's shape"
        and still be re-askable as the library grows.
        """
        if not location:
            return []
        rows = self._browser.rows_for_shelf(location)
        if rows is not None:
            return self._one_per_run_where_the_order_is_newest_first(location, rows)
        group = self._host.group_for_key(location)
        return gallery.rows_under(group) if group is not None else []

    def _one_per_run_where_the_order_is_newest_first(self, location, rows) -> list[dict]:
        """Latest lists a sitting's generations one after another, several seeds
        of a configuration at a time; its show plays one of each such run, and
        the map's row reaches the rest.  Every other set is shuffled, where a
        run is not a run of anything."""
        shelf = folder_shelf(_split_shelf_key(location)[0])
        if shelf is None or shelf.shelf != _RECENTS_KEY:
            return rows
        return one_per_stretch(rows, image_index=self._host.image_config_index())

    # --- putting one on screen ----------------------------------------------

    def _present_surface(self, view, side: str):
        """Put a full-screen surface on screen: over the whole monitor
        standalone, or — inside Fun Time — on the satellite region *side*,
        replacing whatever show currently holds it.

        A region show is frameless (the region IS the window, like every
        managed player) and topmost, since the satellite player it covers is
        topmost itself; Fun Time restacks the band as its modes change.

        Either way it ends up wearing the players' HUD (:meth:`_wear_the_hud`):
        the panel is about the show, and a show is a show wherever it is.
        """
        if self._fun_time is None:
            view.showFullScreen()
            self._standalone_side = side
            self._wear_the_hud(view, side)
            return
        occupant = self._region_shows.get(side)
        if occupant is not None and occupant.is_showing():
            occupant.close()
        view.setWindowTitle(SHOW_TITLES[side])
        view.setWindowFlags(
            view.windowFlags()
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        # Silent like every satellite: the session's main player owns the
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
        # The show answers its own keys (a slideshow's arrows, a fullscreen
        # view's paging), so it takes the keyboard the moment it opens —
        # left unfocused, those keys land in the main window and the view
        # reads as dead.  raise_() first: activation alone does not lift a
        # window over the topmost players it shares the region with.
        view.raise_()
        view.activateWindow()
        self._region_shows[side] = view
        # A show opened while the hosting session is frozen opens frozen: the
        # room's OmniPause holds everything, this surface included, from its
        # first frame — not from whenever the flag next changes.
        if self._session_paused:
            view.set_paused(True)
        self._wear_the_hud(view, side)

    def _wear_the_hud(self, view, side: str) -> None:
        """Put the players' own HUD on *view* — the same panel, rendered by the
        same shared code: the status line, this side's transport, and the nav
        map speaking the set as a seed family.  The view's own furnishings come
        off with it, because the map says all of it.

        Hosted, the show covers a satellite player's HUD and has to BE that
        HUD: its session commands go out on the session's channel and the mode
        pair leads the panel.  Standalone the panel is the same panel minus
        those two — no channel to post on, so the transport lands on the show
        itself, and no session to switch modes on, so no mode row.
        """
        # The view is handed the panel itself rather than only told one is on:
        # a motion key redraws the device rows riding on it.
        view.adopt_hud(ShowHud(view, side=side,
                               dashboard_cmd_file=self._session_channel,
                               label_for=self._item_label))

    @property
    def _session_channel(self):
        return None if self._fun_time is None else self._fun_time.dashboard_cmd_file

    def _item_label(self, prompt_id: str) -> str:
        """What to call the item on a show's HUD, in this app's vocabulary.

        ``<folder> / seed <n>`` — the folder by the name the tree gives it (the
        one the user typed, else its short code) and the item by its seed, which
        is exactly what its tile in the browser is captioned with.  Off the
        disk's own names on purpose: those read "image / ComfyUI_00123_", a
        media type and a counter that appear nowhere in this UI.

        Falls back to whichever half it can find, and to nothing at all for a
        file no row claims — a still being written, say.
        """
        row = self._host.row_for(prompt_id) if prompt_id else None
        if not row:
            return ""
        seed = row.get("seed")
        item = f"seed {seed}" if seed is not None else ""
        return " / ".join(part for part in (self._folder_name(row), item) if part)

    def _folder_name(self, row: dict) -> str:
        """The folder *row* sits in, by the name the tree gives it: the one the
        user typed onto it, else its short code."""
        workflow_name = row.get("workflow_name") or ""
        return gallery.config_folder_name(
            workflow_name,
            gallery.settings_signature(workflow_name, row.get("params_json"),
                                       self._host.image_config_index(),
                                       workflow_version=row.get("workflow_version")),
            self._db.folder_meta_map(),
        )

    # --- letting one go -----------------------------------------------------

    def _on_closed(self, show=None):
        """A show was dismissed (however): let it go, with the hold it put on
        videos, and hand the OSR2 back to whatever the toggle was driving. The
        mic is untouched — it answers to its own button, and "start slideshow"
        has to still be heard now there is no show to hear it over.

        Named rather than assumed, because inside Fun Time two shows run at
        once: closing the portrait one must not forget the landscape one — and
        the videos stay held while the other one is still playing them.
        """
        # Where it had got to, so the next one opens back on that slide: the
        # look at the folder under a picture doesn't cost the place among them.
        if show is not None:
            self._show_state = show.state()
        self._live_shows = [entry for entry in self._live_shows
                            if entry[0] is not show]
        side = self._side_of(show) if show is not None else None
        if show is None or self._slideshow is show:
            self._slideshow = next((s for s, _loc in reversed(self._live_shows)), None)
        if self._slideshow is None:
            self._jobs.hold_videos(False)
        self._host.reconcile_osr2()
        if side is not None:
            # Whatever ended it -- the loop button pressed off, an Escape, a set
            # culled empty -- the region goes back to browsing its library.  The
            # player under it is blacked for the whole mode, so an empty region
            # is a black rectangle, which is the one thing the base state is for.
            self._region_shows[side] = None
            self._refill_region(side)

    def close_live(self):
        """Dismiss a show that was watching a generation which ended with
        nothing to show — left up, it would sit on a stale partial frame forever."""
        show = self._slideshow
        if show is not None and show.is_live():
            show.close()

    def close_the_shows(self) -> None:
        """Give every show back -- the session leaving origenerator mode, or
        this view going away with shows still up.

        The wanting is dropped first: a show closing while the mode still wants
        its regions is refilled with the base state, and these closes must not
        be.
        """
        self._regions_wanted = False
        for show, _location in list(self._live_shows):
            show.close()

    def _open_from_slideshow(self, prompt_id: str):
        """A slideshow handed its item over on the way out — Enter, or a show
        ended while that slide was locked. Land in the item's own folder with it
        selected, the same jump a shelf tile's double-click makes, and open the
        item itself in a config tab.

        The tab matters as much as the folder: leaving a show *for* an item is a
        decision to work on it, and a folder open under a form still holding
        whatever was there before the show is not that — which landing on the
        item gives it, the way a click on it would (``ShowHost.follow_link``).
        The slideshow has already closed itself, so this arrives on the gallery.
        """
        self._slideshow = None
        self._host.follow_link(prompt_id)

    def _open_generate_tab_for(self, prompt_id: str) -> None:
        """A lock on a hosted show: go to the locked item, in the browser and in
        the tabs — the way the RFB answers a lock by opening the video's tab.

        The item itself, not one of its siblings.  Asking the pane to reveal a
        config brings forward whichever tab is already on that SETTINGS folder,
        and every seed of one recipe shares that folder — so the tab that came
        up was a sibling of the locked picture rather than the picture, which is
        the "wrong item, a similar one" this used to open.  So the browser is
        navigated to the item itself (its own folder, its own tile picked), and
        that navigation loads the row into a tab the way a click on it would.
        """
        if self._host.row_for(prompt_id) is None:
            return
        self._host.follow_link(prompt_id)  # its folder, its tile, its tab

    # --- the satellite regions ----------------------------------------------

    def base_location(self, side: str) -> str:
        """Where a region plays from with nothing else asked for: the whole
        library, narrowed to that region's shape.

        The base state of origenerator mode, and what its reset goes back to.
        It is what the satellite players do in player mode — each shuffles the
        whole library of its own orientation — and this side is meant to read
        the same way.
        """
        return oriented_key(gallery.ALL_KEY, side)

    def fill_the_regions(self) -> None:
        """Put a show on each region: the whole library, shuffled, one shape each.

        What entering origenerator mode means — the session's own mode opens
        with both players playing, so this one opens with both regions playing
        rather than with two empty rectangles and a mode that has to be started
        by hand.  Each side gets the shape it can show, and a region already
        holding a show is left alone: the switch is no reason to interrupt
        something already up.
        """
        self._regions_wanted = True
        for side in _ORIENTATIONS:
            if self.region_show(side) is not None:
                continue
            if not self._fill_region(side):
                # Not a dead end: the tree this reads is built by the first
                # refresh, and the session's OPEN_SHOWS can arrive before it
                # (the launch races the boot).  A region owed its base state
                # gets it on the next refresh -- see ``GalleryView.refresh`` --
                # because a black rectangle is what this mode's base state
                # exists to not be.
                logger.info("Nothing of %s shape to open on the %s region yet",
                            side, side)

    def _fill_region(self, side: str) -> bool:
        """Put *side* on its base state, and say whether there was anything to
        put there.

        Timed, because what the owner judges this mode by is the wait between
        the press that opens it and the pictures arriving -- and that press is
        answered on the same thread as everything else this window does, so a
        slow fill is a report about that thread rather than about how big the
        library has grown.
        """
        began = time.perf_counter()
        key = self.base_location(side)
        rows = self.rows_at(key)
        items = self.items_of(rows)
        if not items:
            return False
        self.open(items, rows=rows, location=key, side=side,
                  hud=HudFacts(favorite_ids=self._favorite_prompt_ids()))
        logger.info("The %s region opens on the library of its shape: "
                    "%d items, filled in %d ms",
                    side, len(items), (time.perf_counter() - began) * 1000)
        return True

    def _refill_region(self, side: str) -> None:
        """Put *side* back on its base state, if the mode still wants it there.

        What a region does when the show covering it ends -- the loop button
        pressed off, an Escape, a set culled empty.  In origenerator mode the
        player underneath is blacked for the whole mode, so a region left empty
        is a black rectangle rather than a fallback.
        """
        if not self._regions_wanted or self.region_show(side) is not None:
            return
        self._fill_region(side)

    def _side_of(self, show) -> str | None:
        """Which satellite region *show* is holding, if it holds one."""
        return next((side for side, on_that_side in self._region_shows.items()
                     if on_that_side is show), None)

    def reset_region(self, show) -> None:
        """A region's reset: back to the base state, not to the top of whatever
        that region happens to be playing.

        The players' own meaning of the button — reset drops the narrowing and
        leaves the satellite shuffling its whole library again — so a show
        started on one folder goes back to the library of its shape.  A region
        with nothing to play there, and a show holding no region at all, fall
        back to the show's own reset rather than emptying the screen.
        """
        side = self._side_of(show)
        if side is None:
            show.reset_in_place()
            return
        key = self.base_location(side)
        rows = self.rows_at(key)
        items = self.items_of(rows)
        if not items:
            show.reset_in_place()
            return
        self._repoint(show, key)
        show.set_levels(self.versions_of(rows))
        show.retune(items, enhanced_ids=self._enhanced_ids_of(rows))

    def _repoint(self, show, key: str) -> None:
        self._live_shows = [(live, key if live is show else where)
                            for live, where in self._live_shows]

    def _base_side(self, show) -> str | None:
        if self._fun_time is not None:
            return self._side_of(show)
        return self._standalone_side if show is self._slideshow else None

    def reorder_show(self, show, latest: bool) -> None:
        side = self._base_side(show)
        key = oriented_key(_RECENTS_KEY, side) if latest else self.base_location(side)
        rows = self.rows_at(key)
        items = self.items_of(rows)
        if not items:
            show.note_voice_command("Nothing there to play", kind=WARNING)
            return
        self._repoint(show, key)
        show.set_levels(self.versions_of(rows))
        show.reorder(items, latest=latest, enhanced_ids=self._enhanced_ids_of(rows))
        show.note_voice_command(LATEST_LABEL if latest else SHUFFLE_LABEL)

    def set_session_paused(self, paused: bool) -> None:
        """The hosting session's OmniPause, applied to every open show and
        remembered for the ones not opened yet (see :meth:`_present_surface`).
        The bridge calls this on the flag's edges; the memory is what makes the
        freeze cover a show the user opens mid-pause.

        Each show is its own step, and one that raises must not take the rest
        with it: a freeze that stopped at the first show left the others running
        with no sign of why.
        """
        self._session_paused = paused
        # Every show this window has open, taken from the list it keeps of them
        # rather than from the region map: that map answers only for a show it
        # considers VISIBLE, and a show the session has covered or parked is
        # still a show that must not go on playing through a frozen room.
        for show, _where in list(self._live_shows):
            try:
                show.set_paused(paused)
            except Exception:
                logger.exception("Freezing a show failed")

    # --- keeping a running show current -------------------------------------

    def note_finished(self, row: dict | None):
        """A generation landed: it joins every open show that would be playing
        it had that show opened now.

        Which is the whole point of watching a folder that is auto-generating —
        the playlist is otherwise the fixed set the show opened with, so the
        items the loop makes while it runs are exactly the ones it never reaches.
        Asked of each show's OWN location, remembered when it opened, rather
        than of the view on screen: inside Fun Time the shows play on the
        satellite regions while the main window goes on being used, so by the
        time a generation lands the browser is usually somewhere else — and
        there may be two shows, of two different folders, both keeping up.
        """
        if row is None:
            return
        for show, location in list(self._live_shows):
            if not any(r["prompt_id"] == row["prompt_id"]
                       for r in self.rows_at(location)):
                continue
            for item in self.items_of([row]):
                # With what the show's two switches judge it by: whether it is
                # favorited, and whether it carries an enhancement.
                show.note_added(*item, favorite=bool(row.get("starred")),
                                enhanced=gallery.is_enhanced_row(row))

    def note_generating(self, prompt_id: str, frame: bytes):
        """A run streamed a frame: an open show playing its folder takes it in as
        a slide of that frame, right now, and keeps it current from there.

        Waiting for the file is waiting minutes for the one thing the show is
        being watched for. The first iterations are already worth looking at, so
        the run joins on its first frame and swaps for the file when it lands.

        A run the show holds answers for itself, and one it turned down is
        asked again on its next frame, since the folder lists a new run a poll
        after it starts.
        """
        show = self._slideshow
        if show is None or show.is_live():
            return  # a show already following one run full-screen is that run's
        if not show.holds(prompt_id) and not self._would_play(prompt_id):
            return
        show.note_generating(prompt_id, frame)

    def _would_play(self, prompt_id: str) -> bool:
        """Whether the open show would be playing a generation that has no file
        yet — the question :meth:`note_finished` asks of the rows on screen,
        asked a few minutes earlier.

        A folder's show answers off those rows as usual: the tree keeps a run in
        flight in the folder its settings put it in, so it is already among them.
        A shelf's cannot — Recents is a shelf of results and a run has none yet —
        so Recents answers for itself, by its own rule: every generation this app
        makes lands there, and this is one. The other shelves are deliberate sets
        (favorited, requested, condemned) that nothing joins by being made, and a
        search's hits are a set that was already asked for.

        An enhancement is nobody's slide, wherever it is running. It is a better
        version of a picture the show may already be playing, and the HUD says
        so beside that picture's name — a second slide of it half-rendered
        would be the same image twice, one of them worse.
        """
        row = self._db.get_generation(prompt_id)
        return bool(
            row is not None
            and row.get("workflow_name") != gallery.ENHANCE_WORKFLOW
            and (any(r["prompt_id"] == prompt_id for r in self._host.rows_to_play())
                 # Recents by its own rule, having no list of its own to consult.
                 or (self._browser.showing_recents()
                     and not self._browser.showing_search()
                     and source_of(row) == GenerationSource.GENERATED
                     and gallery.media_type_of_row(row) in self._host.media_types()))
        )

    def note_in_flight(self, items):
        """Tell an open show what is still being made, off the same in-flight list
        the queue plate in its corner is drawn from.

        Two things the frames alone can't say. A run whose frames began before the
        show opened sends no new one for a while — the tail of a run is all decode
        and save — and would otherwise be missing from a show of its own folder;
        and a run that was cancelled or failed sends nothing ever again, leaving
        the half-rendered frame it got to in the pass forever.
        """
        show = self._slideshow
        if show is None or show.is_live():
            return
        self._offer_the_frames(show, items)
        show.note_in_flight({item.key for item in items})

    def _offer_the_frames(self, show, items) -> None:
        for item in items:
            if item.reading.frame is not None and (show.holds(item.key)
                                           or self._would_play(item.key)):
                show.note_generating(item.key, item.reading.frame)

    def note_enhanced(self, row: dict | None):
        """Hand a landed enhancement to every open show, so the item becomes
        the better version there rather than the version it was made from.
        Every one is told; each ignores an id it isn't holding — hosted, two
        run at once on the satellite regions.

        Not only while that item is the one on screen: an enhancement asked for
        from a show lands minutes later, by which time it has long paged on, so an
        upgrade it doesn't take here it never takes at all. The show also draws
        each item small as a neighbor, so it takes the new thumbnail with the file.
        """
        if row is None:
            return
        preview = gallery.resolve_preview(row, COMFYUI_OUTPUT_DIR)
        if preview is None:
            return
        versions = self.versions_of([row])
        for surface in self.surfaces():
            surface.note_enhanced(row["prompt_id"], preview[0], preview[1],
                                  still=row.get("thumbnail_path"))
            surface.add_levels(versions)

    def note_enhancing(self, statuses: dict) -> None:
        self._enhance_status = dict(statuses)
        for surface in self.surfaces():
            surface.note_enhancing(statuses)

    def note_queue(self, items, foreign_total: int) -> None:
        """Redraw the queue plate a show floats in its corner — the same widget
        as the window's lower strip, saying the same thing."""
        if self._slideshow is not None:
            self._slideshow.set_queue(items, foreign_total)

    def note_voice_command(self, message: str, *, kind: str = NOTICE) -> None:
        """Put a spoken line in the show's own corner, if a show is up."""
        if self._slideshow is not None:
            self._slideshow.note_voice_command(message, kind=kind)

    def note_voice_run(self, prompt_id: str | None, message: str, *,
                       kind: str = NOTICE) -> None:
        """Put a line about a launched run in the show's own corner."""
        if self._slideshow is not None:
            self._slideshow.note_voice_run(prompt_id, message, kind=kind)

    def release_media(self, paths) -> None:
        """Drop every surface's hold on ``paths`` — the files a delete is about
        to move. Windows won't move a file while a handle on it is open."""
        for surface in self.surfaces():
            surface.release_media(paths)

    # --- the spoken words about a show --------------------------------------

    def answer(self, message: str, *, kind: str = NOTICE) -> None:
        """Say what a spoken command did, where the speaker is looking — the
        show's own corner while one is up, since the window under it is covered
        by the very thing being talked to, and the gallery's caption otherwise."""
        show = self._slideshow
        if show is not None:
            show.note_voice_command(message, kind=kind)
        else:
            self._host.say(message)

    def run_show_command(self, command: ShowCommand, side: str | None):
        """Get the show going, pause it, or close it — on *side*'s region when
        the utterance named one, else on the show that is up.

        Pausing is a pace of nought and starting is that pace back at the
        standard number, because a show that never moves on is exactly what a
        stopped picture is here — there is no separate paused state to keep.

        The pace is set through the show when there is one, not only posted to
        the app-wide number: a show sitting at nought while that number already
        reads four would get no word of a change that never happened, and would
        stay frozen through the very command meant to start it.
        """
        show = self.surface_for(side)
        if command is ShowCommand.STOP:
            if show is None:
                self._host.say("🎤 no slideshow to close")
                return
            show.close()
            self._host.say("🎤 slideshow closed")
            return
        seconds = 0 if command is ShowCommand.PAUSE else DEFAULT_IMAGE_DWELL_MS // 1000
        if show is None:
            self._pace.set_seconds(seconds)  # what the next show opens at
            if command is ShowCommand.PAUSE:
                self._host.say("🎤 no slideshow to pause")
                return
            self.start(side=side)
            if self._slideshow is None:
                self._host.say("🎤 nothing here to play")
            return
        show.set_dwell_s(seconds)
        show.note_voice_command(
            "🎤 slideshow paused" if command is ShowCommand.PAUSE
            else f"🎤 slideshow at {seconds}s"
        )

    def play_shelf(self, command) -> None:
        """A spoken shelf name, on the named side.

        "Favorites" is the exception, and it is the players' own meaning: on a
        player that word is F-mode — narrow what is playing to the favorites —
        so on a show it is the same switch, the one its HUD draws.  Opening the
        shelf as a fresh show instead would answer a word the HUD already has a
        button for with something else entirely.

        The rest play: every shelf belongs to one side, so a named side picks
        that side's copy and what lands on a region is homogeneous — exactly as
        it is when that shelf's own slideshow button opens it — and Latest plays
        newest-first the way that shelf's own show does.  Standalone, and hosted
        with no side named, it is the shelf on the side being browsed: there is
        no shelf spanning both to fall back to, and the half you are looking at
        is the half the word meant.  The browser is left where it is: this
        starts a show, it does not go browsing."""
        if command.shelf_key == _FAVORITES_KEY:
            self.toggle_favorites_filter(command.side)
            return
        orientation = (command.side if command.side and self._fun_time is not None
                       else self._host.side_in_view())
        key = oriented_key(command.shelf_key, orientation)
        rows = self.rows_at(key)
        items = self.items_of(rows)
        if not items:
            self._host.say("🎤 nothing there to play")
            return
        self.open(items, rows=rows, location=key, side=command.side,
                  **self._order(command.shelf_key == _RECENTS_KEY))

    def toggle_favorites_filter(self, side) -> None:
        """The spoken "favorites": the show's own F-mode switch, flipped.

        The same thing its HUD button does and the same thing the word does on
        a player, so the readout — the lit button and the status line — says so
        without anything here having to draw it."""
        show = self.surface_for(side)
        if show is None:
            self._host.say("🎤 F-mode needs a show to narrow")
            return
        show.toggle_favorites_filter()
        self._host.say("🎤 F-mode on" if show.hud_favorites_filter else "🎤 F-mode off")

    def filter_enhanced(self, enhanced_only: bool, side: str | None = None):
        """Narrow the show in front of the speaker to its enhanced pictures, or
        put them all back — the switch beside F-mode on its HUD, spoken.

        The show's own switch, like the spoken "favorites": a word that set
        some other filter would leave the HUD's button dark over a narrowed
        show. Hosted, a named side takes that region's show, since two run at
        once and neither is the active window. With no show up there is nothing
        for the word to narrow, and it says so rather than arming something.

        Answered with what is left rather than with the switch's name: a speaker
        who has just narrowed a show wants to know there is still something in
        it, and "nothing here is enhanced" is the one answer worth hearing at
        once. Said even when the switch was already that way — a word that did
        nothing and said nothing reads as a mic that missed it.

        Turning it off takes F-mode and the act filter with it: said to a
        show, "clear filter" is the way out of ALL of the narrowing.
        """
        show = self.surface_for(side)
        if show is None:
            self._host.say("🎤 the filter needs a show to narrow")
            return
        if not enhanced_only:
            show.clear_modes()
            show.note_voice_command("🎤 showing all of them")
            return
        if show.set_enhanced_mode(True) or show.hud_enhanced_mode:
            show.note_voice_command(
                f"🎤 enhanced only — {show.pass_size()} to play")
        else:
            show.note_voice_command("🎤 nothing here is enhanced", kind=WARNING)

    def run_on_slide(self, command: AppCommand) -> None:
        """A word about the slide filling the screen: step off it either way,
        take it away, lock it, or bookmark it.

        The words are Fun Time's, and so is what they do — "weird" condemns what
        is on screen, a lock holds it — because the two rooms are one room to
        whoever is speaking, and a word that means one thing there and another
        here is a word nobody can use.
        """
        show = self._slideshow
        kind = NOTICE
        if command is AppCommand.BACK:
            show.step(-1)
            said = "🎤 back"
        elif command is AppCommand.FORWARD:
            show.step(1)
            said = "🎤 next"
        elif command is AppCommand.CULL:
            show.cull()
            said = "🎤 gone"
        elif command is AppCommand.FAVORITE:
            said, kind = (("🎤 favorited", FAVORITE) if show.favorite()
                          else ("🎤 nothing here to favorite", WARNING))
        elif command is AppCommand.LOCK:
            said, kind = (("🎤 locked this one", NOTICE) if show.set_locked(True)
                          else ("🎤 already locked", WARNING))
        else:  # UNLOCK
            said, kind = (("🎤 let go", NOTICE) if show.set_locked(False)
                          else ("🎤 nothing was locked", WARNING))
        self.answer(said, kind=kind)

    # --- what the HUD's two switches judge items by -------------------------

    def _favorite_prompt_ids(self) -> set[str]:
        """Which generations are favorites, for the shows' HUD: the star readout
        on the current item, and the favorites narrowing — the same concepts the
        players' HUD wears, over the same collection the Favorites shelf lists.

        That collection, and not merely the marked rows: a folder bookmarked
        there stands for everything under it, so a show narrowed to the
        favorites keeps what the shelf would have shown.
        """
        marked = {row["prompt_id"] for row in self._db.list_generations()
                  if row.get("starred")}
        for side in _ORIENTATIONS:
            key = oriented_key(_FAVORITES_KEY, side)
            marked.update(row["prompt_id"]
                          for row in (self._browser.rows_for_shelf(key) or ()))
        return marked

    def _enhanced_ids_of(self, rows) -> set[str]:
        """Which of *rows* carry an enhancement, for the switch beside F-mode
        on a show's HUD — the question the thumbnails' yellow plus answers."""
        return {row["prompt_id"] for row in rows if gallery.is_enhanced_row(row)}
