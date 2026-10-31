"""The gallery's browser pane — the middle column showing a folder's contents.

Renders whatever the selected tree row calls for: a branch folder's child tiles, a
settings leaf's thumbnail grid (with its re-roll tile), or the Latest / Favorites /
Enhanced / Experiments / Trash collection overviews. Owns the thumbnail multi-selection
and the live in-flight tiles.

One thing it renders comes from no tree row at all: the gallery search's results,
which take the pane over while a query is running and hand it back when it clears.
That is the whole point of searching here rather than in the tree — the answer to
"where is the one with the two of them on the couch" is a wall of thumbnails you
recognize, not a list of folder names you have to open one by one.

It stands alone: everything it works with arrives at construction — its scroll
area, the database, the re-roll and auto-generate controllers, and two narrow
records of what it may ask the gallery around it (:class:`TreeNavigation`,
:class:`PaneHost`). Every gesture made on a tile leaves as a signal; the view
connects them and answers — the info pane on a click, the tree on a drill, the
delete on a menu.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import NamedTuple

from PyQt6 import sip
from PyQt6.QtCore import QObject, QPoint, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QLabel,
    QMenu,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from shared_ui.spacing import GAP_DIALOG, GAP_MEDIUM, MARGIN_DIALOG

from origenerator import gallery, search
from origenerator.gallery.collection import (
    COLLECTION_LABELS,
    ENHANCED_KEY,
    EXPERIMENTS_KEY,
    FAVORITES_KEY,
    LATEST_KEY,
    TRASH_KEY,
    FolderCollection,
    folder_collection,
)
from origenerator.gallery.placement import Placement
from origenerator.gui import icons
from origenerator.gui.collapsible_section import FOLD, FoldHeader
from origenerator.gui.corner_controls import enhance_state
from origenerator.gui.deferred import defer
from origenerator.gui.flow_layout import FlowLayout
from origenerator.gui.folder_tile import FolderTile
from origenerator.gui.inflight import (
    CANCEL_TEXT,
    InFlightItem,
    cancel_tooltip,
    stop_auto_generate_text,
    stop_auto_generate_tooltip,
)
from origenerator.gui.inflight_items import InFlightItems
from origenerator.gui.inflight_tile import InFlightTile
from origenerator.gui.item_tile import CornerAction, ItemTile
from origenerator.gui.pane_place import (
    PanePlace,
    bring_into_view,
    place_of,
    show_the_tiles_qt_queued_to_show,
    stand_at,
)
from origenerator.gui.picking import Picking
from origenerator.media import MediaType
from origenerator.orientation import base_of, filter_rows, key_holds, split_key

REROLL_VIDEO = "video"
REROLL_IMAGE = "image"

_TILE_SPACING = GAP_MEDIUM   # gap between tiles in the flowing main view
_PREVIEW_COUNT = 4  # thumbnails a folder tile shows as a preview
# A pane draws its tiles a page at a time and adds the next once scrolled within
# _REACH pixels of the end — far enough ahead (three tile rows) that the next page
# is there before the user arrives at it, rather than after a visible stop.
_PAGE = 50
_NEIGHBORS_PAST_A_REVEAL = 12  # three rows at the pane's widest, six at its narrowest
_REACH = 600
# Room above a search section's heading, so the headings read as the dividers
# they are rather than as captions stuck to the row of tiles above them.
_SECTION_SPACING = GAP_DIALOG
# The most result tiles a search draws at once. A one-word query over a full
# library can match most of it, and building thousands of thumbnails in a single
# pass locks the window for seconds — the folders page for the same reason.
# Search doesn't page: it is a narrowing tool, so the useful answer to
# "too many to draw" is another word, and the count label says exactly that
# rather than quietly showing a slice.
SEARCH_DRAW_LIMIT = 200


def play_once_made(pane: BrowserPane, prompt_id: str, movie_path: str) -> None:
    tile = pane._thumb_widgets.get(prompt_id)
    if tile is not None:
        tile.play_moving_preview(movie_path)


class BrowserScrollArea(QScrollArea):
    """The middle pane's scroll area, which says when a click landed on nothing.

    Every tile in here answers its own press and keeps it, so a press that
    arrives at this widget travelled the whole pane without meeting one: the
    background between the tiles, or the room under the last row. That is the
    gesture every file browser answers by putting the selection down, and this
    pane needs it for more than tidiness — Favorite, Enhance and Delete all aim at
    the picked thumbnails when there are any and at the folder on screen when
    there are none, so "Enhance every image in this folder" is out of reach
    while a single tile stays picked, with nothing on screen saying why.
    """

    background_clicked = pyqtSignal()

    def mousePressEvent(self, event):
        # Left only: a right-click opens a context menu, and losing the
        # selection out from under one would aim it at nothing.
        if event.button() == Qt.MouseButton.LeftButton:
            self.background_clicked.emit()
            event.accept()  # nothing above wants it — end the walk up here
            return
        super().mousePressEvent(event)


def _unique_rows(rows) -> list[dict]:
    """``rows`` in order with later repeats of a generation dropped."""
    seen = set()
    unique = []
    for row in rows:
        if row["prompt_id"] not in seen:
            seen.add(row["prompt_id"])
            unique.append(row)
    return unique


def _search_empty_hint(outcome, query: str, scope: str) -> str:
    """What an empty search says. Naming the words that reached nothing is the
    whole of it: a search needs every word satisfied, so with four words typed
    and no results the one thing worth knowing is which word to drop — and
    "nothing matched" alone leaves the user re-typing the query at random.

    ``scope`` is the folder being searched, named in both messages: a query that
    would answer elsewhere in the gallery looks identical to one that answers
    nowhere, and the fix for the first is to pick a wider folder rather than to
    change a single word.
    """
    if outcome.unmatched:
        missing = ", ".join(f"“{word}”" for word in outcome.unmatched)
        return (f"Nothing in {scope} matches {missing}.\n\nEvery word has to be "
                "found somewhere in a generation, so dropping that one — or "
                "searching a wider folder — widens the search.")
    return (f"No generation in {scope} matches all of “{query}”.\n\nEach of "
            "those words is in there somewhere, but no single item has them "
            "all — try fewer of them.")


def _thumbnails_of(rows) -> list[str]:
    paths = []
    for row in rows:
        thumb = row.get("thumbnail_path")
        if thumb and Path(thumb).exists():
            paths.append(thumb)
            if len(paths) >= _PREVIEW_COUNT:
                break
    return paths


class _Listing:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self._dealt: dict[str | None, list[dict]] = {}

    def on(self, side: str | None) -> list[dict]:
        if side not in self._dealt:
            self._dealt[side] = filter_rows(self.rows, side)
        return self._dealt[side]


class _KeptTiles:
    def __init__(self, tiles=None, wiring=None):
        self._tiles = dict(tiles or {})
        self._wiring = dict(wiring or {})

    def take(self, prompt_id: str, look: tuple, wiring: str):
        tile = self._tiles.pop(prompt_id, None)
        if (tile is None or sip.isdeleted(tile) or tile.look != look
                or self._wiring.get(prompt_id) != wiring):
            return None
        return tile


class _Entry(NamedTuple):
    draw: Callable[[], None]
    item: str | None = None
    folder: str | None = None


class _Pages:
    def __init__(self, listing=None, entries=(), drawn=0):
        self.listing = listing
        self._entries = list(entries)
        self.drawn = drawn

    def items(self) -> list[str]:
        return [entry.item for entry in self._entries if entry.item is not None]

    def folders(self) -> list[str]:
        return [entry.folder for entry in self._entries if entry.folder is not None]

    def more(self) -> bool:
        return self.drawn < len(self._entries)

    def draw(self, count: int) -> None:
        for entry in self._entries[self.drawn:self.drawn + count]:
            entry.draw()
            self.drawn += 1

    def draw_past(self, shows, neighbors: int = 0) -> None:
        at = self._index(shows)
        if at is not None:
            self.draw(at + 1 + neighbors - self.drawn)

    def catch_up(self, earlier: _Pages) -> None:
        last = earlier._entries[earlier.drawn - 1] if earlier.drawn else None
        at = self._index(lambda entry: _same_tile(entry, last))
        self.draw((earlier.drawn if at is None else at + 1) - self.drawn)

    def ended(self) -> _Pages:
        return _Pages(self.listing, self._entries[:self.drawn], self.drawn)

    def _index(self, shows) -> int | None:
        return next((n for n, entry in enumerate(self._entries) if shows(entry)), None)


def _same_tile(entry: _Entry, other: _Entry | None) -> bool:
    return (other is not None and (other.item or other.folder) is not None
            and (entry.item, entry.folder) == (other.item, other.folder))


def _drawn_height(drawn: QWidget, width: int) -> int:
    height = drawn.heightForWidth(width)
    return height if height >= 0 else drawn.sizeHint().height()


def _play_only_what_is_in_sight(drawn: QWidget, tiles, top: int, foot: int) -> None:
    for tile in tiles:
        at = tile.mapTo(drawn, QPoint(0, 0)).y()
        tile.set_in_sight(at < foot and at + tile.height() > top)


_COLLECTION_TILE = "collection"
_REVIEW_TILE = "collection with a verdict"
_FOLDER_TILE = "folder"
_SEEDS_TILE = "folder with re-rolls"
_TRASH_TILE = "trash"

OLD_VERSION = "Old version"


def _back_of_the_line_first(items, keys) -> list:
    return [item for item in reversed(items) if item.key in keys]


def _inflight_signature(items) -> tuple:
    """The in-flight runs in the order drawn, so a frame-only change refreshes
    tiles in place while a run added, taken away or moved forces a re-render."""
    return tuple(it.key for it in items)


def _time_heading(text: str) -> QLabel:
    heading = QLabel(text)
    heading.setObjectName("tileGroupHeading")
    return heading


_NOW_HEADING = "Now"
_NO_FAVORITES = ("No bookmarks yet.\n\nStar an image or video from its right-click menu, "
                 "or favorite a folder from the list, to collect them here.")
_NO_ENHANCED = ("No enhanced images yet.\n\nEnhance one from its right-click menu or the plus "
                "in its corner to see it here.")


def _open_sections(flow, headings, *, opens_now=False, draw_leading=lambda: None):
    if opens_now:
        flow.add_full_row(_time_heading(_NOW_HEADING))
        draw_leading()
    if headings and headings[0]:
        flow.add_full_row(_time_heading(headings[0]))
    if not opens_now:
        draw_leading()


def _between_headings(flow, rows, headings, draw) -> list[_Entry]:
    def entry(index, row):
        def draw_it():
            if index and headings[index]:
                flow.add_full_row(_time_heading(headings[index]))
            draw(row)
        return _Entry(draw_it, item=row["prompt_id"])
    return [entry(index, row) for index, row in enumerate(rows)]


@dataclass(frozen=True)
class LeadTiles:
    reroll: QWidget | None = None
    modify: QWidget | None = None
    generating: QWidget | None = None


@dataclass(frozen=True)
class PaneHost:
    """The questions the pane may ask the gallery it fills, bound to the view's
    answers at construction.

    Callables rather than pushed values so each is read at the moment a tile is
    built: the enhance settings and the in-flight runs both move between
    renders, and several tiles are built mid-rebuild, where a value captured
    earlier would already be the old one.
    """

    # Every image row of the current model — what places an untracked run.
    image_rows: Callable[[], list]
    # The looping-preview path for a video row, or None (the tile shows its still).
    animated_preview: Callable[[dict], str | None]
    # The standalone enhance being made of this image right now, or None.
    enhancing_run: Callable[[dict], object]
    # What every enhance runs at, app-wide — the Enhance subpanel's value.
    enhance_settings: Callable[[], object]
    # Whether the background experimenter is on (the empty collection teaches off it).
    experiments_enabled: Callable[[], bool]
    # A settings folder's own tiles from the view — the re-roll tile, its request
    # mirror and the run in front of its line, each None where the folder has
    # none — for the pane to place.
    lead_tiles: Callable[[object], LeadTiles]
    # What an item is called wherever it is named, by its prompt_id.
    item_name: Callable[[str], str]


@dataclass(frozen=True)
class TreeNavigation:
    """The whole of what the pane may ask about the folder tree, as three
    questions bound to the view's own answers at construction.

    A record of callables rather than a back-reference: the pane used to walk
    ``view._tree_view`` and ``view._tree_item_for`` for these, which put the
    tree's item model and the view's cross-side key resolution inside the
    pane's reach. Three named questions are the actual dependency — and a test
    can stand the pane up by answering them alone.
    """

    # The tree key of the selected row (a folder's, or a collection's), or ``None``.
    selected_folder_key: Callable[[], str | None]
    # Where folder ``key`` lives — the breadcrumb of its parent, "" at the top.
    # What a tile drawn far from the tree is captioned with, so identically
    # named folders from opposite corners stay tellable apart.
    folder_context: Callable[[str], str]
    # The folder ``key`` names, as the side being browsed holds it, or ``None``.
    group_for_key: Callable[[str], object]


@dataclass(frozen=True)
class PaneCollection:
    """One collection: what it gathers, and how it draws that.

    Five collections were five parallel places each -- a branch in the renderer's
    dispatch, a branch in the row gatherer, and a method apiece. Both branches
    read this instead, so a sixth collection is one entry rather than an edit in two
    chains, and neither chain can answer for a collection the other does not.
    """

    rows: Callable[[str | None, str], list[dict]]
    render: Callable[[], None]


class BrowserPane(QObject):
    """Fills the middle scroll area (folder tiles / thumbnail grid / collections) and
    owns the thumbnail multi-selection and in-flight tiles. Held by the GalleryView,
    which connects the signals below to its own handlers — a gesture on a tile is
    the pane's to notice and the view's to answer."""

    thumbnail_activated = pyqtSignal(str)   # a tile was clicked: preview this item
    tab_pin_requested = pyqtSignal()        # an "I'm staying" gesture: keep the tab
    item_jump_requested = pyqtSignal(str)   # go to this item, in its own folder
    folder_open_requested = pyqtSignal(str)  # a folder tile was clicked: open it
    reveal_reroll_requested = pyqtSignal(str)  # open this re-roll's folder + tile
    folder_menu_requested = pyqtSignal(str, QPoint)  # right-click on a folder tile
    menu_requested = pyqtSignal(list, QPoint)  # right-click: the generation menu
    trash_menu_requested = pyqtSignal(QPoint)  # right-click on a deleted tile
    item_action_triggered = pyqtSignal(str, str)   # a tile's corner control
    seed_reroll_requested = pyqtSignal(str, str)   # an i2v tile's seed corner
    experiment_verdict = pyqtSignal(str, str)      # a review tile's keep/reject
    trash_action_triggered = pyqtSignal(str, str)  # a deleted tile's restore/purge
    cancel_requested = pyqtSignal(str)      # an in-flight row's ✕: drop that run
    selection_changed = pyqtSignal()        # the multi-selection moved or cleared
    pane_reset = pyqtSignal()  # the outgoing pane's state is being dropped

    def __init__(self, scroll, db, jobs, auto, tree: TreeNavigation,
                 host: PaneHost):
        super().__init__()
        self._scroll = scroll  # the pane's canvas: the middle scroll area it fills
        self._db = db          # the generations the tiles and corners re-read
        self._jobs = jobs  # the live jobs and the queue's own line
        self._auto = auto      # whether a folder is auto-generating (its tile says)
        self._tree = tree      # the three questions the pane may ask the tree
        self._host = host      # the rest of what it asks the gallery (see PaneHost)
        # The queue's tiles are a join over four sources and no rendering at all,
        # so they are built outside the pane and handed the same collaborators.
        self._queue_model = InFlightItems(
            db=db, jobs=jobs, auto=auto, tree=tree,
            image_rows=host.image_rows,
            image_index=lambda: self._image_index,
            on_cancel=self.cancel_requested.emit,
            on_reveal=self.reveal_reroll_requested.emit,
            on_go_to_item=self.item_jump_requested.emit,
            on_shield=jobs.shield,
        )
        # What each collection gathers and how it draws that, bound rather than
        # named: a renamed renderer is an AttributeError at construction instead
        # of a collection that quietly draws nothing.
        self._collections = {
            LATEST_KEY: PaneCollection(
                rows=lambda side, folder: self._in_folder(self._recent_rows, side, folder),
                render=self._render_latest),
            FAVORITES_KEY: PaneCollection(
                rows=self._combined_favorite_rows,
                render=lambda: self._show_gathered(
                    self._favorite_items(self._collection_side, self._collection_folder),
                    self._favorite_folders(self._collection_side, self._collection_folder),
                    show_favorites=False, empty=_NO_FAVORITES)),
            ENHANCED_KEY: PaneCollection(
                rows=lambda side, folder: self._in_folder(self._enhanced_rows, side, folder),
                render=lambda: self._show_gathered(
                    self._open_collection_rows(ENHANCED_KEY), (),
                    show_favorites=False, empty=_NO_ENHANCED)),
            EXPERIMENTS_KEY: PaneCollection(
                rows=lambda side, folder: self._in_folder(self._experiment_rows, side, folder),
                render=self._render_experiments),
            TRASH_KEY: PaneCollection(
                rows=lambda side, folder: self._in_folder(self._trash_rows, side, folder),
                render=self._render_trash),
        }
        # Which tiles are picked, the anchor a Shift-click measures its run
        # from, and what it lists in the order shown
        # (:mod:`origenerator.gui.picking`).
        self._selection = Picking()
        self._listed_folders: list[str] = []  # the folders it lists, as tiles
        self._thumb_widgets: dict[str, ItemTile] = {}
        self._wired: dict[str, str] = {}      # how each drawn tile is wired
        self._kept = _KeptTiles()             # the last pane's tiles, while a new one draws
        self._inflight_tiles: dict[str, InFlightTile] = {}   # live in-flight tiles, by job key
        self._inflight_by_key: dict[str, InFlightItem] = {}  # their items, for click routing
        self._inflight_signature: tuple = ()  # the in-flight set now drawn in the collection
        self._recent_rows = _Listing()      # every generated row, newest first
        self._pages = _Pages()              # the open pane's tiles, drawn a page at a time
        self._listed = _Listing()
        self._enhanced_rows = _Listing()    # every enhanced image, newest first
        self._experiment_rows = _Listing()  # unreviewed experiments, newest first
        self._trash_rows = _Listing()       # trashed items, newest first
        self._search_rows: list[dict] = []  # the open search's hits, in shown order
        self._showing_search = False        # a query owns the pane, whatever the tree says
        self._collection_side: str | None = None
        self._collection_folder = gallery.ALL_KEY
        self._placements: dict[str | None, Placement] = {}
        self._image_index: dict = {}
        self._models_taken = 0
        scroll.verticalScrollBar().valueChanged.connect(self.follow_the_scroll)
        scroll.verticalScrollBar().rangeChanged.connect(self.follow_the_scroll)

    def model_stamp(self) -> int:
        return self._models_taken

    def set_model(self, recent_rows, side_trees, listed_rows, experiment_rows,
                  trash_rows, image_index=None):
        """Take the newly rebuilt gallery model the collections render from.

        ``side_trees`` is per side (``{side: [folders]}``): a folder is
        drawn on whichever sides hold rows of that shape, so each Favorites collection
        collects the copies of the favorites its own side has.
        """
        self._models_taken += 1
        self._recent_rows = _Listing(recent_rows)
        self._listed = _Listing(listed_rows)
        self._enhanced_rows = _Listing(gallery.enhanced_generations(listed_rows))
        self._experiment_rows = _Listing(experiment_rows)
        self._trash_rows = _Listing(trash_rows)
        self._image_index = image_index or {}
        self._placements = {side: Placement(gallery.all_group(tree), self._image_index)
                            for side, tree in side_trees.items()}

    def _open_collection_rows(self, collection: str) -> list[dict]:
        return self._collections[collection].rows(self._collection_side,
                                                  self._collection_folder)

    def _in_folder(self, listing: _Listing, side: str | None, folder: str) -> list[dict]:
        """What *folder* holds of *listing* on *side* -- under Images or Videos,
        that kind alone."""
        return self._placement(side).held_by(folder, listing.on(side))

    def _placement(self, side: str | None) -> Placement:
        placement = self._placements.get(side)
        if placement is None:
            placement = Placement(gallery.all_group([]), self._image_index)
        return placement

    def show_enhancing(self, runs: dict):
        """Hand every visible tile the enhancement being made of its image.

        ``runs`` is ``{prompt_id: RunReading}`` for the enhances in flight
        right now — the latest frame, how far along the run is, and how long it
        has been going. A tile not named there is handed ``None`` and goes back
        to resting. The tile keeps its own thumbnail until a frame arrives — the
        base render is out and worth looking at, which is the point of
        generating it first — and gets it back when the run ends.
        """
        for prompt_id, tile in self._thumb_widgets.items():
            tile.set_enhancing(runs.get(prompt_id))

    # --- folder-tile overview ----------------------------------------------

    def show_widget(self, widget: QWidget):
        self._kept = _KeptTiles()  # what the new pane did not take goes with the old
        self._pages = self._pages.ended()  # nothing more is drawn into what goes
        self._scroll.setWidget(widget)  # replaces & deletes the previous widget

    def _show_paged(self, container: QWidget, entries) -> None:
        pages = _Pages(self._tree.selected_folder_key(), entries)
        for item in pages.items():
            self._selection.note_shown(item)
        self._listed_folders = pages.folders()
        pages.draw(_PAGE)
        if pages.listing == self._pages.listing:
            pages.catch_up(self._pages)
        self.show_widget(container)
        self._pages = pages
        self.follow_the_scroll()
        defer(self._scroll, self.follow_the_scroll)  # again, the pages it drew laid out

    def show_empty(self):
        """Clear the pane to nothing on screen — no folder selected."""
        self._reset_pane_state()
        self.show_widget(QWidget())

    def _reset_pane_state(self):
        """Forget what the outgoing pane held, before the incoming one fills it.

        Every renderer here starts by calling this (through :meth:`_fresh_tile_pane`
        or directly), so no renderer has to remember to clear the state of the one
        it is replacing — which is how a stale selection or a stale search flag
        would otherwise outlive the tiles it referred to.
        """
        self.clear_selection()
        self.pane_reset.emit()  # the view drops its generating tile with the old pane
        self._inflight_tiles = {}    # ...as are the live tiles, by whichever pane draws them
        self._inflight_by_key = {}
        self._selection.forget_what_was_shown()
        self._listed_folders = []
        self._search_rows = []
        self._showing_search = False

    def _fresh_tile_pane(self):
        """A fresh container whose tiles flow to fill the pane's width."""
        container = QWidget()
        flow = FlowLayout(container, spacing=_TILE_SPACING)
        self._kept = _KeptTiles(self._thumb_widgets, self._wired)
        self._reset_pane_state()
        return container, flow

    def _add_folder_tile(self, flow, group, *, favorite, context=""):
        """Build one folder tile and wire its click/context signals."""
        tile = FolderTile(
            group.key, group.label, self._preview_paths(group),
            len(gallery.rows_under(group)), favorite=favorite, context=context,
            badge=icons.folder_badge(group),
        )
        tile.clicked.connect(self._drill_into)
        tile.context_requested.connect(self.folder_menu_requested)
        flow.addWidget(tile)

    def reveal_folder(self, folder_key: str) -> bool:
        """Mark the drawn square that holds this folder and scroll it into view."""
        self._pages.draw_past(lambda entry: entry.folder is not None
                              and key_holds(entry.folder, folder_key))
        drawn = self._scroll.widget()
        if drawn is None:
            return False  # a pane with nothing in it: a slideshow closing as the app does
        for tile in drawn.findChildren(FolderTile):
            if key_holds(tile.key, folder_key):
                self._mark_only_this_folder(drawn, tile)
                bring_into_view(self._scroll, tile)
                return True
        return False

    def _mark_only_this_folder(self, drawn, picked) -> None:
        for tile in drawn.findChildren(FolderTile):
            tile.set_selected(tile is picked)

    def mark_folder_favorite(self, folder_key: str, favorite: bool) -> None:
        for tile in self._scroll.widget().findChildren(FolderTile):
            if tile.key == folder_key:
                tile.set_favorite(favorite)

    def show_folder_tiles(self, groups, collections=()):
        container, flow = self._fresh_tile_pane()
        for key in collections:
            self._add_collection_tile(flow, key)
        if collections and groups:
            flow.add_full_row(_time_heading(" "))
        self._show_paged(container, [
            _Entry(partial(self._add_folder_tile, flow, group, favorite=group.favorite),
                   folder=group.key)
            for group in groups])

    def _add_collection_tile(self, flow, key: str):
        rows = self.rows_for_collection(key)
        collection = folder_collection(base_of(key))
        tile = FolderTile(key, COLLECTION_LABELS[collection.which], _thumbnails_of(rows), len(rows),
                          badge=icons.collection_badge(collection.which))
        tile.clicked.connect(self._drill_into)
        flow.addWidget(tile)

    # --- a folder the user composed: what it gathers, wherever that lives ---

    def show_custom_folder(self, group):
        """Render a custom folder (saved, or the live multi-selection) the way
        Favorites shows what it gathers."""
        self._show_gathered(group.rows, gallery.child_groups(group), show_favorites=True,
                            empty=f"“{group.label}” is empty.\n\nDrag folders from the list, "
                                  "or items, onto it, or pick several folders with "
                                  "Shift/Ctrl and group them.")

    def _show_gathered(self, rows, groups, *, show_favorites: bool, empty: str):
        """Items as thumbnails, then a tile per folder, each captioned with its
        breadcrumb.

        The breadcrumb is what makes this readable at all — a grouping can hold two
        folders that are both called "30 steps" from opposite corners of the tree,
        so the bare label the hierarchy relies on isn't enough here.
        """
        container, flow = self._fresh_tile_pane()
        if not (rows or groups):
            self.show_widget(self._empty_state(empty))
            return

        def folder(group):
            return lambda: self._add_folder_tile(
                flow, group, favorite=show_favorites and group.favorite,
                context=self._tree.folder_context(group.key))

        self._show_paged(container, [
            *(_Entry(partial(self._add_collection_thumbnail, flow, row), item=row["prompt_id"])
              for row in rows),
            *(_Entry(folder(group), folder=group.key) for group in groups)])

    # --- the search results: whatever the query reached, wherever it lives ---

    def show_search_results(self, tiles, *, sort_mode: str, query: str, outcome,
                            scope: str = "", collapsed=(), on_section_toggled=None,
                            still_searching: bool = False):
        """Fill the pane with ``tiles`` — the whole point of searching here rather
        than in the tree, since a thumbnail is recognizable and a folder name is
        not.

        Two orders, because a search answers two different questions. Newest-first
        is "where is the one I made recently"; Model / LoRA is "which model and LoRA
        was that", and there the tiles are cut into a labelled band per
        combination rather than interleaved, so the answer is the heading you
        stopped scrolling at. Those bands fold shut on their headers — with a
        dozen combinations under a broad query, being able to shut the ones you
        are not asking about is what makes the sort usable rather than merely
        sorted. ``collapsed`` is the set of headings to open shut, and
        ``on_section_toggled(heading, collapsed)`` reports each click so the view
        can remember it across a redraw. ``scope`` names the folder that was
        searched, for an empty result to be honest about.

        Either way the tiles behave exactly as they do elsewhere in the gallery: a
        folder drills in on a click, and an item previews here, opens its own
        folder on a double-click, drags to a combine slot and right-clicks for
        star / enhance / delete — a result is the same thing wherever it was found.

        At most :data:`SEARCH_DRAW_LIMIT` tiles are drawn, newest first; the
        header's count names the whole number so a capped search reads as one.
        """
        self._reset_pane_state()
        if not tiles:
            self.show_widget(self._empty_state(
                "" if still_searching else _search_empty_hint(outcome, query, scope)))
            self._showing_search = True
            return
        drawn = list(tiles)[:SEARCH_DRAW_LIMIT]
        container = self._sectioned_results(drawn, collapsed, on_section_toggled) \
            if sort_mode == search.SORT_MODEL_LORA else self._flat_results(drawn)
        self.show_widget(container)
        self._showing_search = True

    def _flat_results(self, tiles) -> QWidget:
        """Every tile in one flow, newest first."""
        container = QWidget()
        flow = FlowLayout(container, spacing=_TILE_SPACING)
        for tile in tiles:
            self._add_search_tile(flow, tile)
        return container

    def _sectioned_results(self, tiles, collapsed, on_toggled) -> QWidget:
        """The tiles under one foldable heading per model + LoRA combination.

        A column of flows rather than one flow with headings in it, because the
        column is what makes folding cheap: a band is one widget to hide rather
        than a run of tiles to pick out of a shared layout.
        """
        container = QWidget()
        column = QVBoxLayout(container)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(_SECTION_SPACING)
        for heading, section in search.group_by_model_lora(tiles):
            band = QWidget()
            band_flow = FlowLayout(band, spacing=_TILE_SPACING)
            shut = heading in collapsed
            column.addWidget(
                self._section_header(heading, len(section), band, shut, on_toggled))
            # A shut band's tiles are still built and still counted: they are the
            # results, and folding is about what you are looking at, not what the
            # search found — so unfolding is instant and the shown order (which
            # Shift-select and the slideshow read) stays the order on screen.
            for tile in section:
                self._add_search_tile(band_flow, tile)
            band.setVisible(not shut)
            column.addWidget(band)
        column.addStretch(1)  # sections stay their own height; slack falls to the end
        return container

    @staticmethod
    def _section_header(heading: str, count: int, band: QWidget, shut: bool,
                        on_toggled) -> FoldHeader:
        """The band's foldable header: the family's chevron, the model and LoRA, and how
        many are in it.

        A flat, full-width button rather than a label — the whole strip is the
        target, which is what a fold control has to be when the bands are tall
        enough that you are aiming at it after a scroll.
        """
        button = FoldHeader(warns=False)
        button.setObjectName("tileGroupHeading")
        button.setFlat(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setText(f"{heading}   ({count})")

        def paint(collapsed: bool):
            button.set_fold(FOLD[collapsed])

        # The fold state is carried here rather than read back off the band: a
        # widget whose window hasn't been shown yet reports isVisible() false
        # however it was set, so asking it would make the first click on a
        # freshly drawn pane a no-op.
        state = {"shut": shut}

        def toggle():
            state["shut"] = not state["shut"]
            band.setVisible(not state["shut"])
            paint(state["shut"])
            if on_toggled is not None:
                on_toggled(heading, state["shut"])

        button.clicked.connect(toggle)
        paint(shut)
        return button

    def _add_search_tile(self, flow, tile: search.SearchTile):
        """Draw one result — a folder tile or a single item — and record its place.

        The shown order matters beyond the drawing: Shift-select and the slideshow
        both read it, so it has to be the order the bands were laid out in rather
        than the order the search scored them.
        """
        if tile.group is not None:
            self._add_folder_tile(flow, tile.group, favorite=tile.group.favorite,
                                  context=self._tree.folder_context(tile.group.key))
            self._listed_folders.append(tile.group.key)
        else:
            self._add_collection_thumbnail(flow, tile.row)
            self._selection.note_shown(tile.row["prompt_id"])
        self._search_rows.extend(tile.rows or [tile.row])

    def showing_search(self) -> bool:
        """Whether a query owns the pane. Unlike the collections this is not a tree
        row, so it is answered by what was last drawn rather than by what is
        selected: the tree keeps whatever folder it had while a search runs."""
        return self._showing_search

    # --- the collections: Latest / Favorites / Enhanced / Experiments / Trash ---

    def show_collection(self, key: str, side: str | None = None):
        collection = folder_collection(key)
        if collection is None:
            return
        self._collection_side = side
        self._collection_folder = collection.folder
        self._collections[collection.which].render()

    def _render_latest(self):
        """The Latest collection: a tile for every in-flight generation (queued or
        running, from a Generate tab or a gallery re-roll) atop the recently
        finished items. Clicking an in-flight tile reveals where its job runs; a
        finished one previews in the info pane, right here in the collection, the way
        a thumbnail does inside a folder — and double-clicking it jumps to its
        own folder.

        In-flight tiles first (the newest work, still in flight), then the
        finished thumbnails; a hint when there is neither.
        """
        container, flow = self._fresh_tile_pane()
        rows = self._open_collection_rows(LATEST_KEY)
        items = self._latest_inflight_items()
        self._inflight_signature = _inflight_signature(items)
        self._inflight_tiles = {}
        self._inflight_by_key = {}

        def draw_leading():
            for item in items:
                self._add_inflight_tile(flow, item)

        headings = gallery.section_headings(rows)
        _open_sections(flow, headings,
                       opens_now=bool(items) and gallery.new_work_opens_a_section(rows),
                       draw_leading=draw_leading)
        # An empty collection teaches how to fill it rather than showing a blank pane.
        if not (items or rows):
            self.show_widget(self._empty_state(self._latest_empty_hint()))
            return
        self._show_paged(container, _between_headings(
            flow, rows, headings, lambda row: self._add_collection_thumbnail(flow, row)))

    def follow_the_scroll(self, *_):
        """Draw on a page at a time until the tiles reach _REACH past the foot of
        what is seen — what makes a pane keep going instead of stopping at a fixed
        count, and fills a pane taller than a page — and play only the looping
        videos within _REACH of it.

        Measured off the tiles drawn rather than off the scroll bar, whose range
        trails the drawing until the pane is laid out again. Wired to the bar's
        value for the scrolling itself, and to its range for a pane that changed
        size under the reader.
        """
        drawn, seen = self._scroll.widget(), self._scroll.viewport()
        if drawn is None:
            return  # between one pane and the next
        top = self._scroll_bar().value()
        while self._pages.more() and (_drawn_height(drawn, seen.width())
                                      - top - seen.height() < _REACH):
            self._pages.draw(_PAGE)
            show_the_tiles_qt_queued_to_show(drawn)  # or the page measures as nothing
        _play_only_what_is_in_sight(drawn, self._thumb_widgets.values(),
                                    top - _REACH, top + seen.height() + _REACH)

    def _scroll_bar(self):
        """The browser pane's vertical scroll bar: what a pane grows off, and what a
        redraw puts back where the user was reading."""
        return self._scroll.verticalScrollBar()

    def _add_collection_thumbnail(self, flow, row, corner_actions=None):
        """Build one finished-item tile for a collection (Latest/Favorites/Experiments):
        preview it here on a click, open its own folder on a double-click, drag it
        to a combine slot, and right-click it for the same star / enhance / delete
        menu a tile inside a folder offers; ``corner_actions`` become the tile's
        hover controls (a review's keep/reject, wired to the verdict)."""
        def wire(tw):
            tw.pressed.connect(self.apply_selection)
            tw.clicked.connect(self.thumbnail_activated)  # preview it here, in the collection
            tw.double_clicked.connect(self._collection_double_clicked)  # or open its folder
            # Every collection gets the folder menu — an item is no less actionable for
            # being listed by when it was made or by its favorite rather than by its
            # settings.
            tw.context_requested.connect(self._thumbnail_context_menu)
            tw.control_triggered.connect(self._on_tile_control)
            if corner_actions:
                tw.corner_action_triggered.connect(self.experiment_verdict)

        return self._draw_tile(
            flow, row, _REVIEW_TILE if corner_actions else _COLLECTION_TILE, wire,
            media_type=gallery.media_type_of_row(row),  # a corner badge: image or video
            movie_path=self._host.animated_preview(row),  # videos loop; images stay still
            favorite=bool(row.get("starred")),
            enhance=self._enhance_state(row),           # the plus in the thumbnail's corner
            enhancing=self._host.enhancing_run(row),       # scrim + bar while one cooks
            corner_actions=corner_actions,
        )

    def _draw_tile(self, flow, row, wiring: str, wire, *, caption: str | None = None,
                   **appearance) -> ItemTile:
        """The last pane's tile for *row*, when it would be built again the same and
        wired the same way, else a new one *wire* connects."""
        prompt_id = row["prompt_id"]
        thumb_path = row.get("thumbnail_path")
        if caption is None:
            caption = self._host.item_name(prompt_id)
        tile = self._kept.take(
            prompt_id, ItemTile.look_of(prompt_id, thumb_path, caption, **appearance),
            wiring)
        if tile is None:
            tile = ItemTile(prompt_id, thumb_path, caption, **appearance)
            wire(tile)
        else:
            tile.set_favorite(appearance.get("favorite", False))
            tile.set_enhance(appearance.get("enhance"))
            tile.set_enhancing(appearance.get("enhancing"))
        flow.addWidget(tile)
        tile.set_selected(self._selection.holds(prompt_id))
        self._thumb_widgets[prompt_id] = tile
        self._wired[prompt_id] = wiring
        return tile

    def _tile_items(self, rows=None, requests=None) -> list[InFlightItem]:
        """The runs in flight that get a tile: all but the enhancements, each of
        which shows on the tile of the image it upgrades instead."""
        return [item for item in self.inflight_items(rows, requests)
                if item.job_kind != gallery.JobKind.ENHANCE]

    def _latest_inflight_items(self, rows=None, requests=None) -> list[InFlightItem]:
        """The open Latest's tiles: the runs it will list once they land, held to
        its side and its folder exactly as its finished items are."""
        if rows is None:
            rows = self._db.list_generations()
        held = {row["prompt_id"] for row in self._in_folder(
            _Listing(row for row in rows if gallery.is_in_progress(row)),
            self._collection_side, self._collection_folder)}
        return _back_of_the_line_first(self._tile_items(rows, requests), held)

    def _latest_empty_hint(self) -> str:
        """The teaching hint for an empty collection, worded for the kind its
        folder holds."""
        noun = next((label.lower() for kind, label in gallery.MEDIA_LABELS.items()
                     if key_holds(kind, self._collection_folder)), "generations")
        return (f"No recent {noun} yet.\n\nItems you make — from a Generate tab or a "
                "gallery re-roll — collect here, newest first.")

    def showing_latest(self) -> bool:
        return base_of(self._tree.selected_folder_key()) == LATEST_KEY

    def refresh_inflight(self, rows=None, requests=None):
        """Between rebuilds, keep the in-flight tiles live: push each tracked
        re-roll's latest frame into its tile. The poll passes the listing it
        already read (``rows``/``requests``); left off, they are read here.

        Whichever pane drew them — the Latest collection, or a settings folder with
        a batch in flight. Only the collection re-renders on a change to the
        *set* of jobs (a defensive guard — a started or finished re-roll
        normally moves the DB fingerprint and forces a full rebuild anyway); a
        folder is rebuilt by that same fingerprint and must not be redrawn as
        the collection. A pane holding no tiles asks the database nothing.
        """
        if not self._inflight_tiles and not self.showing_latest():
            return
        items = (self._latest_inflight_items(rows, requests) if self.showing_latest()
                 else self._tile_items(rows, requests))
        if (self.showing_latest()
                and _inflight_signature(items) != self._inflight_signature):
            place = self.place()
            self._render_latest()
            self.return_to(place)
            return
        for item in items:
            self._inflight_by_key[item.key] = item  # keep the reveal current
            tile = self._inflight_tiles.get(item.key)
            if tile is not None:
                tile.update_item(item)

    def inflight_items(self, rows=None, requests=None) -> list:
        """Every queued/running generation as a tile model, in the order the
        queue will work through them
        (:class:`~origenerator.gui.inflight_items.InFlightItems`)."""
        return self._queue_model.build(rows=rows, requests=requests)

    def _on_inflight_clicked(self, key: str):
        item = self._inflight_by_key.get(key)
        if item is not None:
            item.reveal()

    def _inflight_context_menu(self, key: str, global_pos):
        """Right-click a tile of work still being made: throw that run away.

        The one act a queued or running tile has, and until now the one act it
        offered nowhere: a finished tile answers a right-click with its own menu,
        and a tile answered with nothing, so stopping a run meant finding it again
        among the Job Queue's rows. The wording is the Job Queue's Cancel, which
        while the folder is auto-generating starts another seed rather than
        stopping anything.

        Which is exactly why an auto-generating folder's tile gets a second entry
        (:func:`inflight.stop_auto_generate_text`): a menu, unlike the one button those
        surfaces have room for, can carry both the discard and a real stop, so a
        run made while Auto-Generate is on can be ended without going to the header
        for the Auto switch. Auto-Generate goes off first — a discard while it is still on is
        the cue for the next seed, so canceling first would start one.

        No menu at all for a running row this session holds no job for — one a
        restart hasn't re-adopted: there is nothing here to cancel it with, and
        a menu saying so would be a menu that cannot act.
        """
        item = self._inflight_by_key.get(key)
        if item is None or item.cancel is None:
            return
        menu = QMenu(self._scroll)
        discard = menu.addAction(CANCEL_TEXT)
        discard.setToolTip(cancel_tooltip(item.auto_generating))
        stop = None
        if item.auto_generating and item.stop_auto is not None:
            stop = menu.addAction(stop_auto_generate_text())
            stop.setToolTip(stop_auto_generate_tooltip())
        chosen = menu.exec(global_pos)
        if chosen is discard:
            item.cancel()
        elif stop is not None and chosen is stop:
            item.stop_auto()
            item.cancel()

    def _collection_double_clicked(self, prompt_id: str):
        """A collection tile's double-click: go to the item's own folder, and keep the
        tab that lands there — its tile picked, highlighted and scrolled to, as
        if you'd navigated in and clicked it (:meth:`GalleryView.follow_link`
        answers the jump).

        Double-click means the same thing everywhere in the pane — this tab is
        one I'm staying on — whether it opens a folder on the way or not."""
        self.item_jump_requested.emit(prompt_id)
        self.tab_pin_requested.emit()

    # --- the Experiments collection: unreviewed background experiments -------

    def _render_experiments(self):
        """The Experiments collection: what the background experimenter has come up
        with since the user last looked, newest first, each tile wearing
        keep/reject hover controls. A kept item just leaves the queue — it has
        been in its own folder since it ran; a rejected one is trashed and
        teaches the policy what to avoid. Clicking previews the item right here
        and double-clicking opens its folder, like the other collections."""
        container, flow = self._fresh_tile_pane()
        actions = [
            CornerAction("keep", icons.experiment_verdict_icon("up"),
                         "Keep — add it to the gallery"),
            CornerAction("reject", icons.experiment_verdict_icon("down"),
                         "Reject — trash it and steer future experiments away"),
        ]
        rows = self._open_collection_rows(EXPERIMENTS_KEY)
        if not rows:
            self.show_widget(self._empty_state(self._experiments_empty_hint()))
            return

        def draw(row):
            self._add_collection_thumbnail(flow, row, corner_actions=list(actions))

        headings = gallery.section_headings(rows)
        _open_sections(flow, headings)
        self._show_paged(container, _between_headings(flow, rows, headings, draw))


    def _experiments_empty_hint(self) -> str:
        if self._host.experiments_enabled():
            return ("Nothing to review yet.\n\nEach time you close the app, "
                    "variations of your own generations are queued up and run "
                    "while you're away; they collect here for your verdict.")
        return ("Background experiments are off.\n\nTurn them on above and the "
                "time the app is closed will be spent trying variations of your "
                "work — new prompts on proven settings, nudged parameters, other "
                "models. Results collect here; your keep/reject verdicts steer "
                "what gets tried next.")

    # --- the Trash collection: deleted items, still in the Trash --------------

    def _render_trash(self):
        """The Trash collection: every deleted item the Trash is still
        holding, newest first, each tile wearing restore / delete-permanently
        hover controls and captioned with how long it has left. A restored item
        returns to its own folder, files and all; a purged one is gone for good,
        which is what the whole collection exists to make deliberate rather than
        automatic."""
        container, flow = self._fresh_tile_pane()
        actions = [
            CornerAction("restore", icons.trash_action_icon("restore"),
                         "Restore — put it and its files back where they were"),
            CornerAction("purge", icons.trash_action_icon("purge"),
                         "Delete permanently — remove it and its files for good"),
        ]
        rows = self._open_collection_rows(TRASH_KEY)
        if not rows:
            self.show_widget(self._empty_state(self._trash_empty_hint()))
            return
        self._show_paged(container, [
            _Entry(partial(self._add_trash_thumbnail, flow, row, list(actions)),
                   item=row["prompt_id"])
            for row in rows])

    def _add_trash_thumbnail(self, flow, row, corner_actions):
        """One deleted item's tile — a collection tile like any other, wired to
        everything a deleted item can still do.

        Its files are all in the trash rather than gone, and the Trash kept its row
        whole, so it previews on a click, loops if it's a video, opens full size,
        plays in the collection's slideshow and fills a config tab with the settings
        that made it — the whole point of a Trash being that you can look before you
        decide. Double-clicking opens it as a Generate tab (the gesture a folder's
        tiles carry) rather than jumping to its folder, which is the one thing a
        deleted item hasn't got.

        What it doesn't get is the ordinary tile's right-click menu or its corner
        controls — star, enhance, delete all want a row in the gallery — and no
        drag to a combine slot, whose graphs read files out of ComfyUI's output
        folder, not ours. In their place the corners and the menu offer the two
        actions that do apply: restore, or end it for good.
        """
        def wire(tile):
            tile.pressed.connect(self.apply_selection)
            tile.clicked.connect(self.thumbnail_activated)          # preview it here
            tile.double_clicked.connect(self._thumbnail_double_clicked)  # or reuse its settings
            tile.context_requested.connect(self._trash_context_menu)
            tile.corner_action_triggered.connect(self.trash_action_triggered)

        name = self._host.item_name(row["prompt_id"])
        return self._draw_tile(
            flow, row, _TRASH_TILE, wire,
            caption=f"{OLD_VERSION} · {name}" if row.get("old_version_of") else name,
            media_type=gallery.media_type_of_row(row),  # a corner badge: image or video
            movie_path=self._host.animated_preview(row),  # videos loop; images stay still
            favorite=bool(row.get("starred")),
            controls=False,       # its two acts are restore and purge, in the corners
            corner_actions=corner_actions,
        )

    def _trash_context_menu(self, prompt_id: str, global_pos):
        """Right-click a deleted tile: restore or permanently delete the picked
        items — the same two actions its hover corners carry, reachable for a
        whole selection at once. Right-clicking a tile outside the selection
        first narrows to it, as the gallery's own tile menu does. The menu
        itself is the view's (:meth:`GalleryView._trash_menu`), which owns both
        acts."""
        if not self._selection.holds(prompt_id):
            self.apply_selection(prompt_id, Qt.KeyboardModifier.NoModifier)
        self.trash_menu_requested.emit(global_pos)

    def _trash_empty_hint(self) -> str:
        return ("Nothing deleted.\n\nItems you delete wait here for as long as "
                "you leave them — nothing here is removed on its own. Restore one, "
                "or delete it permanently when you're sure.")

    def showing_trash(self) -> bool:
        return base_of(self._tree.selected_folder_key()) == TRASH_KEY

    # --- the Favorites collection: every favorite — items and folders — in one place ---

    def _favorite_items(self, side: str | None, folder: str) -> list[dict]:
        return self._placement(side).held_by(folder, gallery.favorite_generations(
            self._listed.on(side)))

    def _favorite_folders(self, side: str | None, folder: str) -> list:
        group = self._placement(side).folder(folder)
        return gallery.favorite_folders(gallery.child_groups(group)) if group else []

    def _combined_favorite_rows(self, side: str | None, folder: str) -> list[dict]:
        return _unique_rows(self._favorite_items(side, folder) + [
            row for group in self._favorite_folders(side, folder)
            for row in gallery.rows_under(group)
        ])

    @staticmethod
    def _empty_state(text: str) -> QWidget:
        """A centered hint filling an otherwise-blank collection pane."""
        label = QLabel(text)
        label.setObjectName("estimateLabel")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        label.setContentsMargins(MARGIN_DIALOG, MARGIN_DIALOG, MARGIN_DIALOG, MARGIN_DIALOG)
        return label

    # --- what the open collection gathers (the slideshow plays it) ----------

    def collection_rows(self) -> list[dict] | None:
        """Every generation the open collection gathers, in collection order — or ``None``
        outside the collections, where a folder is what's on screen instead.

        The slideshow plays these, so they have to match the tiles: Latest is its
        listed items, Favorites is its favorited items plus everything under each
        favorited folder, since a folder tile there stands for its whole folder,
        Enhanced is its enhanced images, Experiments is its unreviewed queue, and
        Trash is what is held there — deleted is not unwatchable, and items you
        are deciding whether to keep are ones to sit and look through.
        A favorited item inside a favorited folder is one item, so repeats drop out.
        A running search gathers too — its hits are gathered exactly as a
        collection's are, and sitting through what a search turned up is
        one of the better reasons to have run it.
        """
        if self.showing_search():
            return list(self._search_rows)
        return self.selected_collection_rows()

    def collection_counts(self, side: str) -> dict[str, int]:
        placement = self._placement(side)
        tallies = {collection: placement.tally(
                       self._collections[collection].rows(side, gallery.ALL_KEY))
                   for collection in (ENHANCED_KEY, EXPERIMENTS_KEY, TRASH_KEY)}
        tallies[FAVORITES_KEY] = placement.tally_favorites(self._listed.on(side))
        return {FolderCollection(collection, folder).key: count
                for collection, tally in tallies.items() for folder, count in tally.items()}

    def selected_collection_rows(self) -> list[dict] | None:
        """What the *selected* collection gathers, whatever is currently drawn.

        The same answer as :meth:`collection_rows` off a search, and the one that
        matters during one: a search standing in a collection is scoped to that
        collection's items, and the results now on screen are no use for working out
        what those are.

        Asked of the selected row's own key, which is the same key the collection was
        rendered for. Written out again here, it was the five answers below a
        second time over, once against the side the key names and once against
        the side the render remembered.
        """
        return self.rows_for_collection(self._tree.selected_folder_key())

    def rows_for_collection(self, key: str | None) -> list[dict] | None:
        """What the collection *key* gathers right now — :meth:`collection_rows` for a
        collection that is not the one on screen.

        Named rather than "what is showing" because a hosted slideshow outlives the
        selection that opened it: inside Fun Time the slideshows run on the satellite
        regions while the browser goes on being used elsewhere, so keeping a
        running slideshow fed — and answering a spoken "landscape favorites" — both
        need a collection's rows asked for by name.
        """
        base, side = split_key(key)
        collection = folder_collection(base)
        if collection is None:
            return None
        return self._collections[collection.which].rows(side, collection.folder)

    # --- the thumbnail grid: a settings leaf's generations ------------------

    def show_thumbnails(self, group):
        container, flow = self._fresh_tile_pane()
        # An i2v folder's items carry per-seed re-roll hover controls; its rows
        # all share the one workflow, so the kind is decided once. Media-gated
        # because the enhancer is image-conditioned too, but its items have no
        # video seed to offer.
        i2v = bool(group.rows) \
            and gallery.is_image_conditioned(group.rows[0].get("workflow_name")) \
            and gallery.media_type_of_row(group.rows[0]) == MediaType.VIDEO
        def wire(tw):
            tw.pressed.connect(self.apply_selection)
            tw.clicked.connect(self.thumbnail_activated)
            tw.double_clicked.connect(self._thumbnail_double_clicked)
            tw.context_requested.connect(self._thumbnail_context_menu)
            tw.control_triggered.connect(self._on_tile_control)
            if i2v:
                tw.corner_action_triggered.connect(self.seed_reroll_requested)

        def draw(row):
            self._draw_tile(
                flow, row, _SEEDS_TILE if i2v else _FOLDER_TILE, wire,
                movie_path=self._host.animated_preview(row),  # videos loop; images stay still
                favorite=bool(row.get("starred")),
                enhance=self._enhance_state(row),           # the plus in the thumbnail's corner
                enhancing=self._host.enhancing_run(row),       # scrim + bar while one cooks
                corner_actions=self._seed_reroll_actions(row) if i2v else None,
            )

        # The + leads, and the run in front of this folder's line stands last,
        # where its tile will land; the runs waiting after it stand before it.
        # Rows still in flight stay out of the grid below rather than standing in
        # it as broken, output-less thumbnails.
        finished = [row for row in group.rows if gallery.produced_output(row)]
        headings = gallery.section_headings(finished)
        lead = self._host.lead_tiles(group)
        tiles = self._folder_inflight_items(group)
        opens_now = ((lead.reroll is not None or bool(tiles))
                     and gallery.new_work_opens_a_section(finished))
        sections = opens_now + sum(1 for heading in headings if heading)
        modify_above = lead.modify is not None and sections > 1
        if modify_above:
            flow.addWidget(lead.modify)

        def draw_leading():
            for tile in (lead.reroll, None if modify_above else lead.modify):
                if tile is not None:
                    flow.addWidget(tile)
            for item in tiles:
                self._add_inflight_tile(flow, item)
            if lead.generating is not None:
                flow.addWidget(lead.generating)

        _open_sections(flow, headings, opens_now=opens_now, draw_leading=draw_leading)
        self._show_paged(container, _between_headings(flow, finished, headings, draw))

    def _folder_inflight_items(self, group) -> list[InFlightItem]:
        """Every other run of this folder still in flight, for a tile each.

        The generating tile shows the one in front, and used to be the whole of
        what a folder said about work in flight — so a request over a folder,
        which queues a run per image at once, showed up as a single tile the
        images then arrived through one at a time. They are all being made;
        the folder shows them all, each on the image it was asked of
        (:mod:`origenerator.gui.blurred`), and each turns into its own
        thumbnail where it stands.
        """
        leading = self._jobs.job_for(group.key)
        in_front = leading.prompt_id if leading is not None else None
        waiting = {row["prompt_id"] for row in group.rows
                   if not gallery.produced_output(row) and row["prompt_id"] != in_front}
        return _back_of_the_line_first(self._tile_items(), waiting) if waiting else []

    def _add_inflight_tile(self, flow, item):
        tile = InFlightTile(item)
        tile.clicked.connect(self._on_inflight_clicked)
        tile.context_requested.connect(self._inflight_context_menu)
        flow.addWidget(tile)
        self._inflight_tiles[item.key] = tile
        self._inflight_by_key[item.key] = item

    def _seed_reroll_actions(self, row) -> list:
        if not gallery.rerollable(row):
            return []
        actions = [CornerAction(REROLL_VIDEO, icons.reroll_seed_icon(MediaType.VIDEO),
                                "Randomize video seed")]
        if gallery.rebuildable_source_image_id_in(row, self._image_index) is not None:
            actions.append(CornerAction(REROLL_IMAGE, icons.reroll_seed_icon(MediaType.IMAGE),
                                        "Randomize image seed"))
        return actions

    @staticmethod
    def _preview_paths(group) -> list[str]:
        return _thumbnails_of(gallery.rows_under(group))

    def _drill_into(self, key: str):
        """Open a folder tile's folder — the view answers by selecting its tree
        row (:meth:`GalleryView._go_to_folder`)."""
        self.folder_open_requested.emit(key)

    def listed_prompt_ids(self) -> list[str]:
        return self._selection.shown

    # --- multi-selection ---------------------------------------------------

    def _thumbnail_double_clicked(self, prompt_id: str):
        """Open a thumbnail as a Generate tab and keep that tab.

        The first click has already loaded it into the pane's preview tab; the
        second says to stay there, so the tab stops being the one the next click
        replaces. Browsing costs one tab however far you go; deciding to work on
        something costs the double-click that keeps it."""
        self.thumbnail_activated.emit(prompt_id)  # make it the selected generation
        self.tab_pin_requested.emit()

    def apply_selection(self, prompt_id: str, modifiers):
        """Update the multi-select set the way the held modifiers dictate.

        Ctrl toggles one tile; Shift extends a contiguous run from the anchor;
        a plain click resets to just this tile. Mirrors a typical file browser.
        """
        self._selection.apply(
            prompt_id,
            ctrl=bool(modifiers & Qt.KeyboardModifier.ControlModifier),
            shift=bool(modifiers & Qt.KeyboardModifier.ShiftModifier),
        )
        self._refresh_selection_highlights()

    def reveal_tile(self, prompt_id: str) -> bool:
        """Land on a tile the way arriving from elsewhere should: picked, and
        scrolled to if it sits outside the visible part of the pane. What a
        followed link needs — a folder of dozens otherwise leaves you looking at
        its newest items with the one you asked for highlighted off-screen.

        False where this pane has no tile of its own for it."""
        self._pages.draw_past(lambda entry: entry.item == prompt_id, _NEIGHBORS_PAST_A_REVEAL)
        widget = self._thumb_widgets.get(prompt_id)
        if widget is None:
            return False  # nothing drawn for it here: an in-flight row, or a folder
        self.apply_selection(prompt_id, Qt.KeyboardModifier.NoModifier)
        self._scroll_to(widget)
        # The pane it was just drawn in hasn't been laid out yet, so that first
        # attempt had no real tile position to aim at — hence a second one once
        # this turn's layout has run (as :meth:`return_to` does).
        defer(self._scroll, lambda: self._reapply_reveal(prompt_id, widget))
        return True

    def _reapply_reveal(self, prompt_id: str, widget):
        """Scroll to a revealed tile again after layout — unless the pane has since
        been redrawn or navigated away from, in which case that tile is gone and
        the user's new view is not ours to move."""
        if self._thumb_widgets.get(prompt_id) is widget:
            self._scroll_to(widget)

    def _scroll_to(self, widget):
        bring_into_view(self._scroll, widget)

    def place(self) -> PanePlace:
        return place_of(self._scroll, self._selection, self._thumb_widgets)

    def return_to(self, place: PanePlace) -> None:
        self._selection.pick_again(place.picks)
        self._refresh_selection_highlights()
        drawn = self._scroll.widget()
        stand_at(self._scroll, self._thumb_widgets, place, drawn)
        # Again once laid out: a pane drawn this turn has no tile positions yet.
        defer(self._scroll, lambda: stand_at(self._scroll, self._thumb_widgets, place, drawn))

    def _refresh_selection_highlights(self):
        for pid, widget in self._thumb_widgets.items():
            widget.set_selected(self._selection.holds(pid))
        self.selection_changed.emit()

    def clear_selection(self):
        self._selection.clear()
        self._thumb_widgets = {}
        self._wired = {}
        self.selection_changed.emit()

    def clear_thumbnail_selection(self):
        """Drop the thumbnail multi-selection and its highlights while keeping the
        on-screen tiles (unlike a rebuild), so picking the re-roll deselects them."""
        self._selection.clear()
        self._refresh_selection_highlights()

    @property
    def selected_ids(self) -> set:
        """The picked thumbnails' prompt_ids (read-only), for the delete button."""
        return self._selection.picked

    def selected_prompt_ids(self) -> list[str]:
        return self._selection.in_shown_order()

    def _thumbnail_context_menu(self, prompt_id: str, global_pos):
        """Right-click menu for a thumbnail: go to its folder, favorite/unfavorite,
        enhance or delete the picked item(s).

        Right-clicking a tile that isn't part of the current selection first
        selects just it, so the menu always acts on something visible. The menu
        itself is the gallery's, not this pane's — the preview in a config tab
        raises the very same one over the very same generation
        (:meth:`~origenerator.gui.gallery_view.GalleryView.generation_menu`).
        """
        if not self._selection.holds(prompt_id):
            self.apply_selection(prompt_id, Qt.KeyboardModifier.NoModifier)
            self.thumbnail_activated.emit(prompt_id)
        self.menu_requested.emit(self.selected_prompt_ids(), global_pos)

    def _on_tile_control(self, prompt_id: str, action: str):
        """A tile's corner control was pressed: favorite, trash or enhance THIS one.

        One item, never the selection — the control is drawn on a particular
        thumbnail, in that thumbnail's own corner, so it has already said which item
        it is about. The menu is where a whole selection is acted on.
        """
        self.item_action_triggered.emit(prompt_id, action)

    def _enhance_state(self, row) -> str | None:
        """What the plus in this row's lower-right corner has to say, at the
        Enhance panel's current settings (:func:`corner_controls.enhance_state`)."""
        return enhance_state(row, self._host.enhance_settings())

    def refresh_corners(self):
        """Re-read every drawn tile's enhance corner, without rebuilding the pane.

        Turning a setting in the Enhance subpanel changes what every item on
        screen would get from a press — an image holding the version the panel
        described a moment ago is now one enhancement short of the new one — and
        none of those tiles were touched, so nothing else would tell them.
        """
        for prompt_id, tile in self._thumb_widgets.items():
            row = self._db.get_generation(prompt_id)
            if row is not None:
                tile.set_enhance(self._enhance_state(row))
                tile.set_favorite(bool(row.get("starred")))
