"""The fullscreen shows: opening them, placing them, feeding them, letting go.

The third of the gallery's screen concerns to come out of the view that used to
hold all of them, and the first one that owns a window. What lives here is a
show's whole life -- built once however it was asked for, put on the monitor
standalone or on one of Fun Time's satellite regions, kept up with the folder it
is playing as generations land there, frozen with the room, and let go when it
closes (which puts a satellite region back on its base state).

The seven pieces of state a show needs are here and only here: the show that is
up, every show that is up (hosted, two run at once), what each satellite region
holds, whether the session still wants its regions filled, whether the room is
frozen, where the last show left off, and which runs the open show has already
turned down as slides of their own frames.

The spoken words about a show are here too -- close it, hold it, narrow it to
the favorites or to the enhanced ones, step off the slide, play a shelf. They
are words about a show rather than words about the microphone, and a router that
carried them would only have to hand every one of them straight back.

What stays with the host is what a show is *of*: which folder or shelf the
gallery is standing in, what plays from there, and what a gesture inside a show
does back in the window. :class:`ShowHost` names each of those.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import Protocol

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QWidget

from origenerator import gallery
from origenerator.config import COMFYUI_OUTPUT_DIR
from origenerator.fun_time_mode import SHOW_TITLES, region_for_items
from origenerator.gui.gallery_tree import (
    RECENTS_KEY as _RECENTS_KEY,
)
from origenerator.gui.gallery_tree import (
    STARRED_KEY as _STARRED_KEY,
)
from origenerator.gui.orientation import (
    ORIENTATIONS as _ORIENTATIONS,
)
from origenerator.gui.orientation import (
    oriented_key,
)
from origenerator.gui.orientation import (
    split_key as _split_shelf_key,
)
from origenerator.gui.show_wiring import HudFacts, ShowActions
from origenerator.gui.slideshow_view import SlideshowView
from origenerator.slideshow import DEFAULT_IMAGE_DWELL_MS, ShowState, in_order
from origenerator.voice.app_commands import AppCommand
from origenerator.voice.show_commands import ShowCommand
from origenerator.win32 import place_window_in_device_pixels

logger = logging.getLogger(__name__)


def _shared_hud_widget():
    """The players' HUD widget, or ``None`` where player_core has not got one.

    Reached for here rather than imported at module top, and reached for at all
    rather than assumed, for the same reason: the panel lives in the newest
    player_core, while this app's other reaches into that sibling (genau's
    console, the motion) resolve against an older checkout perfectly well.  A
    session names the checkout it wants on PYTHONPATH; a plain launch walks up
    to the primary one, and that one only grows the panel when it lands.

    So a checkout without it starts, browses and generates exactly as before,
    and a show opened on it is the show that used to be: its own neighbor
    stills and position plate, no map.  Losing the panel is a bad afternoon;
    losing the fullscreen view over the panel would be a dead app.
    """
    try:
        from origenerator.gui.show_hud import ShowHud
    except ImportError:
        logger.warning(
            "This player_core carries no shared HUD, so shows wear none",
            exc_info=True)
        return None
    return ShowHud


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

    def level_playlists(self) -> dict:
        """Each visible image's versions, keyed by the file the folder shows it
        under -- the axis Shift+Left/Right steps along."""

    def folder_media(self) -> list[tuple]:
        """The visible folder's resolvable media, in the order shown."""

    def folder_media_playlist(self) -> tuple[list, int]:
        """That same media and the index of the item on screen, or ``([], 0)``
        when the item on screen is not among it."""

    def queue_now(self) -> tuple[list, int]:
        """What is in flight here, and how much of ComfyUI's queue is another
        app's -- the plate a show floats in its corner."""

    def clear_foreign_queue(self) -> None:
        """Drop another app's work off ComfyUI, as that plate's Clear does."""

    def follow_link(self, prompt_id: str) -> None:
        """Land on this generation: its folder, its tile, its config tab."""

    def trash_generation(self, prompt_id: str) -> None:
        """Condemn it, as a show's Up key does."""

    def star_generation(self, prompt_id: str) -> None:
        """Bookmark it, as a show's Down key does."""

    def enhance_from_slideshow(self, prompt_id: str) -> bool:
        """Queue a better version of it, returning whether one was launched."""

    def toggle_osr2_drive(self) -> None:
        """Flip the one app-wide device switch, as Space does anywhere."""

    def reconcile_osr2(self) -> None:
        """Re-pick what the device follows, a surface having changed."""

    def say(self, message: str) -> None:
        """Flash a line on the gallery's own caption."""


class ShowDirector:
    """Every fullscreen show this window has open, and the words about them."""

    def __init__(self, host: ShowHost, *, db, browser, reroll, pace, motion,
                 fun_time):
        self._host = host
        self._db = db
        self._browser = browser
        self._reroll = reroll
        self._pace = pace
        self._motion = motion
        self._fun_time = fun_time
        # The fullscreen slideshow window while one is open — whether it was
        # started from the toolbar (a whole folder, shuffled) or by
        # double-clicking a picture (that folder in order, held at a pace of
        # nought). One slot, because it is one view.
        self._slideshow = None
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
        # Runs the open show has already turned down as slides of their own
        # frames — another folder's work, an enhancement. Asked once and kept,
        # since every frame of such a run asks again (:meth:`_would_play`).
        self._show_refused: set[str] = set()

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
        show = self._region_shows.get(side)
        return show if show is not None and show.isVisible() else None

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
        items = self.items_of(self._host.rows_to_play())
        if not items:
            return
        location = self._host.show_location()
        # Recents is Latest, exactly as on a Fun Time player: the shelf lists
        # newest first and its slideshow plays that order, where every other
        # set shuffles — and the show's HUD status line says which.
        base, orientation = _split_shelf_key(location)
        latest = base == _RECENTS_KEY
        self.open(
            items, location=location, side=side or orientation,
            resume=self._show_state,
            shuffle=(lambda order: None) if latest else None,
            hud=HudFacts(order_label="Latest" if latest else "Shuffle",
                         starred_ids=self._starred_prompt_ids()),
        )
        logger.info("Slideshow of %s: %d items, %s",
                    self._host.slideshow_subject(), len(items),
                    "latest" if latest else "shuffled")

    def open_on_preview(self, media, frame):
        """A double-click on a tab's preview: open its folder as a slideshow held
        on the very picture that was clicked.

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
        items, index = self._host.folder_media_playlist()
        if media is None:  # following a run: it has no place among the files yet
            items, index = [], 0
        elif not items:  # the shown item isn't in the folder listing: play it alone
            items, index = [(media[0], media[1], None, None)], 0
        # Neither shuffled nor newest-first, and not a loop: this is one folder
        # in the browser's own order, held on one picture.  Said plainly rather
        # than left at the defaults, because the HUD reads them now — an order
        # slot saying "Shuffle" over a folder listed in its own order would be
        # the panel making something up.
        return self.open(items, start=index, frame=frame,
                         image_dwell_ms=0, shuffle=in_order,
                         folder_items=self._host.folder_media(),
                         hud=HudFacts(
                             order_label="", looping=False,
                             starred_ids=self._starred_prompt_ids()))

    def open(self, items, *, folder_items=None, location=None,
             side=None, resume=None, **kwargs):
        """Build, wire and show a fullscreen slideshow of ``items``.

        The one place a show is made, however it was asked for, so the toolbar's
        and a double-click's differ only in the order and the pace they pass.
        ``folder_items`` is what to arm a show that opened over a running
        generation with, since that one has no items of its own yet, and
        ``resume`` where a closed show left off, for one picking that back up
        rather than naming its own opening slide.

        ``location`` is the shelf or folder key the set came from, kept so the
        show can be fed what lands there while it runs (:meth:`note_finished`) —
        a running show has to keep up with the folder it is playing, and the
        browser will have moved on by then.  ``side`` names the satellite region
        to land it on inside Fun Time, for a show asked for by side rather than
        routed by its own shape.
        """
        self._show_refused = set()  # a new show, a new set to be judged against
        self._slideshow = SlideshowView(
            items,
            actions=ShowActions(
                delete=self._host.trash_generation,
                enhance=self._host.enhance_from_slideshow,
                star=self._host.star_generation,
                # Two of the six are a session's: a lock opens the held item as
                # a generate tab, and a reset means the REGION's base state.
                lock=(self._open_generate_tab_for
                      if self._fun_time is not None else None),
                reset=(self.reset_region if self._fun_time is not None else None),
                # Space reaches the one OSR2 switch, like every other surface's.
                drive_toggle=self._host.toggle_osr2_drive,
            ),
            pace=self._pace, motion=self._motion,
            # Which of its items carry an enhancement, for the switch beside
            # F-mode on its HUD -- over the set it plays and the folder a live
            # show is armed with, since either is what the switch narrows.
            hud=replace(kwargs.pop("hud", HudFacts()),
                        enhanced_ids=self._enhanced_prompt_ids(
                            [*items, *(folder_items or [])])),
            **kwargs)
        self._live_shows.append((self._slideshow, location))
        if folder_items and self._slideshow.is_live():
            # Watching something render is no reason to lose the folder it is
            # being made in: the first arrow leaves the live frames for it.
            self._slideshow.set_playlist(folder_items, 0)
        # Shift+Left/Right gets its own axis: the versions of whichever image is
        # on screen, so a level can be compared against the one below it at full
        # size rather than in a thumbnail.
        self._slideshow.set_levels(self._host.level_playlists())
        if resume is not None:
            # After the levels: the version a slide was left showing is only a
            # version once they are armed.
            self._slideshow.resume(resume)
        self._slideshow.open_requested.connect(self._open_from_slideshow)
        show = self._slideshow
        show.closed.connect(lambda s=show: self._on_closed(s))
        self._slideshow.media_changed.connect(self._host.reconcile_osr2)
        # Standalone that is a monitor to take over; hosted, it is one of the
        # satellite regions — the side asked for, else the one this set's own
        # shape belongs on.
        self._present_surface(self._slideshow, side or region_for_items(items))
        self._host.reconcile_osr2()
        # However the show was asked for, it now owns the card it is drawn with: a
        # video generation would saturate that card, and a show is exactly the
        # stretch when nobody is waiting on a video. The queue holds them until it
        # closes and keeps making images.
        self._reroll.hold_videos(True)
        # The queue it floats in its corner is the same widget as the lower
        # strip and asks for the same things, so it goes to the same handlers:
        # a row dragged there re-lines the queue, and its Clear drops another
        # app's work off ComfyUI.
        self._slideshow.queue().reorder_requested.connect(self._reroll.reorder)
        self._slideshow.queue().clear_queue_requested.connect(
            self._host.clear_foreign_queue)
        # And fill it at once rather than a poll later: the hold on videos is
        # this opening's own doing, so the corner comes up already saying what
        # is waiting on it rather than blank for a second and a half.
        self._slideshow.set_queue(*self._host.queue_now())
        return self._slideshow

    def items_of(self, rows) -> list:
        """(path, media_type, prompt_id, thumbnail) for each of ``rows``, in the
        order given — the slideshow's playlist. The thumbnail is what the view
        draws for the item while it's a neighbor rather than the one on screen (a
        video has no other still).

        A row with no file is left out, whether it never got one or is still
        being made: a slide with nothing to look at is a gap between pictures,
        and one still cooking joins the running show the moment it lands (see
        :meth:`note_finished`)."""
        items = []
        for row in rows:
            resolved = gallery.resolve_preview(row, COMFYUI_OUTPUT_DIR)
            if resolved is None:
                continue  # nothing to look at yet, or ever
            items.append((resolved[0], resolved[1], row["prompt_id"],
                          row.get("thumbnail_path")))
        return items

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
            return rows
        group = self._host.group_for_key(location)
        return gallery.rows_under(group) if group is not None else []

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
            self._wear_the_hud(view, side)
            return
        occupant = self._region_shows.get(side)
        if occupant is not None and occupant.isVisible():
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
            view.set_session_paused(True)
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

        A player_core with no shared HUD in it leaves the show as it was, with
        its own stills and plate still on — see :func:`_shared_hud_widget`.
        """
        hud = _shared_hud_widget()
        if hud is None:
            return
        # The view is handed the panel itself rather than only told one is on:
        # its console seats itself under the panel and follows it as it resizes.
        view.adopt_hud(hud(view, side=side,
                           dashboard_cmd_file=(None if self._fun_time is None
                                               else self._fun_time.dashboard_cmd_file),
                           label_for=self._item_label))

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
        folder = gallery.config_folder_name(
            row.get("workflow") or "",
            gallery.settings_signature(row.get("workflow"), row.get("params"),
                                       self._host.image_config_index()),
            self._db.folder_meta_map(),
        )
        return " / ".join(part for part in (folder, item) if part)

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
            self._reroll.hold_videos(False)
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
        """A lock on a hosted show: go to the held item, in the browser and in
        the tabs — the way the RFB answers a lock by opening the video's tab.

        The item itself, not one of its siblings.  Asking the pane to reveal a
        config brings forward whichever tab is already on that SETTINGS folder,
        and every seed of one recipe shares that folder — so the tab that came
        up was a sibling of the held picture rather than the picture, which is
        the "wrong item, a similar one" this used to open.  So the browser is
        navigated to the item itself (its own folder, its own tile picked), and
        that navigation loads the row into a tab the way a click on it would.
        """
        if self._host.row_for(prompt_id) is None:
            return
        self._host.follow_link(prompt_id)  # its folder, its tile, its tab

    # --- the satellite regions ----------------------------------------------

    def region_base_location(self, side: str) -> str:
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
            key = self.region_base_location(side)
            items = self.items_of(self.rows_at(key))
            if not items:
                # Not a dead end: the tree this reads is built by the first
                # refresh, and the session's OPEN_SHOWS can arrive before it
                # (the launch races the boot).  A region owed its base state
                # gets it on the next refresh -- see ``GalleryView.refresh`` --
                # because a black rectangle is what this mode's base state
                # exists to not be.
                logger.info("Nothing of %s shape to open on the %s region yet",
                            side, side)
                continue
            logger.info("The %s region opens on the library of its shape: %d items",
                        side, len(items))
            self.open(items, location=key, side=side,
                      hud=HudFacts(
                          looping=False,
                          starred_ids=self._starred_prompt_ids()))

    def _refill_region(self, side: str) -> None:
        """Put *side* back on its base state, if the mode still wants it there.

        What a region does when the show covering it ends -- the loop button
        pressed off, an Escape, a set culled empty.  In origenerator mode the
        player underneath is blacked for the whole mode, so a region left empty
        is a black rectangle rather than a fallback.
        """
        if not self._regions_wanted or self.region_show(side) is not None:
            return
        key = self.region_base_location(side)
        items = self.items_of(self.rows_at(key))
        if not items:
            return
        self.open(items, location=key, side=side,
                  hud=HudFacts(
                      looping=False,
                      starred_ids=self._starred_prompt_ids()))

    def _side_of(self, show) -> str | None:
        """Which satellite region *show* is holding, if it holds one."""
        return next((side for side, held in self._region_shows.items()
                     if held is show), None)

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
        key = self.region_base_location(side)
        items = self.items_of(self.rows_at(key))
        if not items:
            show.reset_in_place()
            return
        # The show is being re-pointed, so what feeds it has to move with it:
        # a generation landing in the library must reach a reset region.
        self._live_shows = [(held, key if held is show else where)
                            for held, where in self._live_shows]
        show.retune(items, enhanced_ids=self._enhanced_prompt_ids(items))

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
                show.set_session_paused(paused)
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
                # starred, and whether it carries an enhancement.
                show.note_added(*item, starred=bool(row.get("starred")),
                                enhanced=gallery.is_enhanced_row(row))

    def note_generating(self, prompt_id: str, frame: bytes):
        """A run streamed a frame: an open show playing its folder takes it in as
        a slide of that frame, right now, and keeps it current from there.

        Waiting for the file is waiting minutes for the one thing the show is
        being watched for. The first iterations are already worth looking at, so
        the run joins on its first frame and swaps for the file when it lands.

        Whether it belongs is asked once per run, either way: a run the show
        holds answers itself, and one it turned down is remembered as turned down
        (:attr:`_show_refused`). A frame arrives every second or so, and the
        question costs a row lookup and a walk of what is on screen.
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
        (starred, requested, condemned) that nothing joins by being made, and a
        search's hits are a set that was already asked for.

        An enhancement is nobody's slide, wherever it is running. It is a better
        version of a picture the show may already be playing, and it says so in
        that picture's own corner note — a second slide of it half-rendered
        would be the same image twice, one of them worse.

        A no is kept for the life of the show, since it is asked again of every
        frame of a run in some other folder — and the set under a show doesn't
        move while one is up, the gallery being covered by it.
        """
        if prompt_id in self._show_refused:
            return False
        row = self._db.get_generation(prompt_id)
        plays = bool(
            row is not None
            and row.get("workflow_name") != gallery.ENHANCE_WORKFLOW
            and (any(r["prompt_id"] == prompt_id for r in self._host.rows_to_play())
                 # Recents by its own rule, having no list of its own to consult.
                 or (self._browser.showing_recents()
                     and not self._browser.showing_search()
                     and (row.get("source") or "generated") == "generated"
                     and gallery.media_type_of_row(row) in self._host.media_types()))
        )
        if not plays:
            self._show_refused.add(prompt_id)
        return plays

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
        for item in items:
            if item.frame is not None and (show.holds(item.key)
                                           or self._would_play(item.key)):
                show.note_generating(item.key, item.frame)
        show.note_in_flight({item.key for item in items})

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
        for surface in self.surfaces():
            surface.note_enhanced(row["prompt_id"], preview[0], preview[1],
                                  still=row.get("thumbnail_path"))

    def note_enhancing(self, statuses: dict) -> None:
        """Tell an open show how the enhancements in flight are going.

        A show is where a batch of them gets asked for — every held slide is a
        run — so it is the surface most likely to be looking at a picture whose
        turn has not come. The show cannot tell on its own: a hold hears only
        that a run started, not where in the line it landed.
        """
        if self._slideshow is None:
            return
        self._slideshow.note_enhancing(statuses)

    def note_queue(self, items, foreign_total: int) -> None:
        """Redraw the queue plate a show floats in its corner — the same widget
        as the window's lower strip, saying the same thing."""
        if self._slideshow is not None:
            self._slideshow.set_queue(items, foreign_total)

    def note_voice_command(self, message: str) -> None:
        """Put a spoken line in the show's own corner, if a show is up."""
        if self._slideshow is not None:
            self._slideshow.note_voice_command(message)

    def note_voice_run(self, prompt_id: str | None, message: str) -> None:
        """Put a line about a launched run in the show's own corner."""
        if self._slideshow is not None:
            self._slideshow.note_voice_run(prompt_id, message)

    def drive_target(self):
        """The funscript the show on screen is playing, or ``None`` — what the
        one device switch follows in preference to a tab's video."""
        if self._slideshow is None:
            return None
        return self._slideshow.osr2_drive_target()

    def release_media(self, paths) -> None:
        """Drop every surface's hold on ``paths`` — the files a delete is about
        to move. Windows won't move a file while a handle on it is open."""
        for surface in self.surfaces():
            surface.release_media(paths)

    # --- the spoken words about a show --------------------------------------

    def answer(self, message: str) -> None:
        """Say what a spoken command did, where the speaker is looking — the
        show's own corner while one is up, since the window under it is covered
        by the very thing being talked to, and the gallery's caption otherwise."""
        show = self._slideshow
        if show is not None:
            show.note_voice_command(message)
        else:
            self._host.say(message)

    def run_show_command(self, command: ShowCommand, side: str | None):
        """Get the show going, hold it, or close it — on *side*'s region when
        the utterance named one, else on the show that is up.

        Pausing is a pace of nought and starting is that pace back at the
        standard number, because a show that never moves on is exactly what a
        held picture is here — there is no separate paused state to keep.

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
        if command.shelf_key == _STARRED_KEY:
            self.toggle_f_mode(command.side)
            return
        orientation = (command.side if command.side and self._fun_time is not None
                       else self._host.side_in_view())
        key = oriented_key(command.shelf_key, orientation)
        rows = self._browser.rows_for_shelf(key) or []
        items = self.items_of(rows)
        if not items:
            self._host.say("🎤 nothing there to play")
            return
        latest = command.shelf_key == _RECENTS_KEY
        self.open(
            items, location=key, side=command.side,
            shuffle=(lambda order: None) if latest else None,
            hud=HudFacts(order_label="Latest" if latest else "Shuffle",
                         starred_ids=self._starred_prompt_ids()),
        )

    def toggle_f_mode(self, side) -> None:
        """The spoken "favorites": the show's own F-mode switch, flipped.

        The same thing its HUD button does and the same thing the word does on
        a player, so the readout — the lit button and the status line — says so
        without anything here having to draw it."""
        show = self.surface_for(side)
        if show is None:
            self._host.say("🎤 F-mode needs a show to narrow")
            return
        show.toggle_f_mode()
        self._host.say("🎤 F-mode on" if show.hud_f_mode else "🎤 F-mode off")

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

        Turning it off takes F-mode with it: "clear filter" is the way out of
        ALL of the narrowing, which is what the same phrase means on every
        satellite in this family.
        """
        show = self.surface_for(side)
        if show is None or not hasattr(show, "set_enhanced_mode"):
            self._host.say("🎤 the filter needs a show to narrow")
            return
        if not enhanced_only:
            show.clear_modes()
            show.note_voice_command("🎤 showing all of them")
            return
        if show.set_enhanced_mode(True) or show.hud_enhanced_mode:
            show.note_voice_command(
                f"🎤 enhanced only — {len(show.hud_items()[0])} to play")
        else:
            show.note_voice_command("🎤 nothing here is enhanced")

    def run_on_slide(self, command: AppCommand) -> None:
        """A word about the slide filling the screen: step off it either way,
        take it away, hold it, or bookmark it.

        The words are Fun Time's, and so is what they do — "weird" condemns what
        is on screen, a lock holds it — because the two rooms are one room to
        whoever is speaking, and a word that means one thing there and another
        here is a word nobody can use.
        """
        show = self._slideshow
        if command is AppCommand.BACK:
            show.step(-1)
            said = "🎤 back"
        elif command is AppCommand.FORWARD:
            show.step(1)
            said = "🎤 next"
        elif command is AppCommand.CULL:
            show.cull()
            said = "🎤 gone"
        elif command is AppCommand.STAR:
            said = "🎤 starred" if show.star() else "🎤 nothing here to star"
        elif command is AppCommand.LOCK:
            said = "🎤 holding this one" if show.set_held(True) else "🎤 already holding it"
        else:  # UNLOCK
            said = "🎤 let go" if show.set_held(False) else "🎤 nothing was held"
        self.answer(said)

    # --- what the HUD's two switches judge items by -------------------------

    def _starred_prompt_ids(self) -> set[str]:
        """Which generations are favorites (starred), for the shows' HUD: the
        star readout on the current item, and the F-mode narrowing — the same
        concepts the players' HUD wears, over the same collection the
        Favorites shelf lists."""
        return {row["prompt_id"] for row in self._db.list_generations()
                if row.get("starred")}

    def _enhanced_prompt_ids(self, items) -> set[str]:
        """Which of *items* carry an enhancement, for the switch beside F-mode
        on a show's HUD — the question the thumbnails' yellow plus answers,
        asked of the set a show plays.

        Of that set rather than of the whole library: reading whether a row is
        enhanced means parsing its params, and a library of thousands would
        pay that on every show opened for the sake of rows the show never
        plays.  What lands mid-show is judged as it arrives
        (:meth:`note_finished`).
        """
        wanted = {item[2] for item in items if len(item) > 2 and item[2] is not None}
        if not wanted:
            return set()
        return {row["prompt_id"] for row in self._db.list_generations()
                if row["prompt_id"] in wanted and gallery.is_enhanced_row(row)}
