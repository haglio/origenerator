"""The gallery's browser pane — the middle column showing a folder's contents.

Renders whatever the selected tree row calls for: a branch folder's child tiles, a
settings leaf's thumbnail grid (with its re-roll tile), or the Recents / Starred /
Experiments / Requests / Trash shelf overviews. Owns the thumbnail multi-selection
and the live in-flight cards.

One thing it renders comes from no tree row at all: the gallery search's results,
which take the pane over while a query is running and hand it back when it clears.
That is the whole point of searching here rather than in the tree — the answer to
"where is the one with the two of them on the couch" is a wall of thumbnails you
recognize, not a list of folder names you have to open one by one.

It drives the surrounding pieces it doesn't own — the info pane on a click, the
tree on a drill, the re-roll tile, the delete action — so it holds a reference to
the GalleryView and calls back into it rather than standing alone. The view keeps
thin delegates so the pane's rendering and selection are one concern in one place.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QLabel, QMenu, QApplication, QPushButton, QVBoxLayout,
)
from PyQt6.QtCore import Qt, QTimer

from origenerator import gallery, search, timing
from origenerator.gui.collapsible_section import _ARROW_OPEN, _ARROW_SHUT
from origenerator.gui.corner_controls import enhance_state
from origenerator.branch_session import is_branch_session
from origenerator.gui import icons
from origenerator.gui.flow_layout import FlowLayout
from origenerator.gui.folder_tile import FolderTile
from origenerator.gui.thumbnail_widget import ThumbnailWidget
from origenerator.gui.inflight import InFlightItem
from origenerator.gui.inflight_card import InFlightCard
from origenerator.gui.queue_thumbs import FOLDER_CELLS
from origenerator.gui.gallery_tree import (
    EXPERIMENTS_LABEL, RECENTS_LABEL, REQUESTS_LABEL, STARRED_LABEL, TRASH_LABEL,
)
from origenerator.recovery import RETENTION_DAYS
from origenerator.workflows.derived_size import resolve_input_image_path

logger = logging.getLogger(__name__)

_TILE_SPACING = 8   # gap between tiles in the flowing main view
_PREVIEW_COUNT = 4  # thumbnails a folder tile shows as a preview
_STARRED_TITLE = "★ " + STARRED_LABEL  # the browser-pane heading for the shelf
# The Recents shelf lists every generation ever made, so it draws a page of tiles
# at a time and adds the next once scrolled within _RECENTS_REACH pixels of the
# end — far enough ahead (three tile rows) that the next page is there before the
# user arrives at it, rather than after a visible stop.
_RECENTS_PAGE = 50
_RECENTS_REACH = 600
# Room above a search section's heading, so the headings read as the dividers
# they are rather than as captions stuck to the row of tiles above them.
_SECTION_SPACING = 14
# The most result tiles a search draws at once. A one-word query over a full
# library can match most of it, and building thousands of thumbnails in a single
# pass locks the window for seconds — the Recents shelf pages for the same
# reason. Search doesn't page: it is a narrowing tool, so the useful answer to
# "too many to draw" is another word, and the count label says exactly that
# rather than quietly showing a slice.
SEARCH_DRAW_LIMIT = 200


@dataclass(frozen=True)
class SearchTile:
    """One thing a search draws: a folder, or a single generation.

    Several hits in one settings folder are one answer, not eight — they share a
    prompt and settings and differ only by seed, so drawing each of them fills
    the pane with near-copies of the same picture and buries the other places
    the query reached. So the view collapses them onto their folder (``group``
    set, ``rows`` the hits it stands for), and leaves a folder's lone hit as
    itself (``group`` ``None``).

    ``row`` is the newest hit either way: the tile's picture when it stands
    alone, and what decides the model + LoRA band it lands in when sorted that
    way — every row in a settings folder ran the same recipe, so any of them
    answers that.
    """

    row: dict
    group: object | None = None
    rows: list = field(default_factory=list)
# Vertical breathing room left around a tile a link scrolls to, so it lands with
# its neighbors in view rather than flush against an edge of the pane.
_REVEAL_MARGIN = 40


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


def _inflight_signature(items) -> tuple:
    """The identity of the in-flight set — its job keys — so a frame-only change
    refreshes cards in place while an added or removed job forces a re-render."""
    return tuple(sorted(it.key for it in items))


# The job kinds whose queue row shows what they are made from rather than what
# their folder holds (:func:`gallery.job_kind_label`).
SOURCE_FRAME_KINDS = ("I2V", "Enhance")

# What that same function calls a standalone enhance — the kind the Recents shelf
# draws no card for. Asked of the function rather than spelled "Enhance" here, so
# the shelf keeps agreeing with the queue if the queue ever renames the kind.
ENHANCE_KIND = gallery.job_kind_label(gallery.ENHANCE_WORKFLOW)


class BrowserPane:
    """Fills the middle scroll area (folder tiles / thumbnail grid / shelves) and
    owns the thumbnail multi-selection and in-flight cards. Held by the GalleryView,
    which it calls back into for the info pane, tree, re-roll tile, and delete."""

    def __init__(self, view):
        self._v = view
        self._selected_ids: set[str] = set()
        self._selection_anchor: str | None = None
        self._visible_ids: list[str] = []   # generations on screen, in shown order
        self._visible_keys: list[str] = []  # folders on screen (tile overview)
        self._thumb_widgets: dict[str, ThumbnailWidget] = {}
        self._inflight_cards: dict[str, InFlightCard] = {}   # live in-flight cards, by job key
        self._inflight_by_key: dict[str, InFlightItem] = {}  # their items, for click routing
        self._inflight_signature: tuple = ()  # the in-flight set now drawn on the shelf
        self._recent_rows: list[dict] = []  # every generated row, newest first
        self._recents_flow = None           # the open shelf's layout, to grow into
        self._recents_drawn = 0             # finished items it has drawn so far
        self._starred_groups: list = []     # folders the Starred shelf collects
        self._starred_rows: list[dict] = [] # starred items the Starred shelf collects
        self._experiment_rows: list[dict] = []  # unreviewed experiments, newest first
        self._trash_rows: list[dict] = []   # held deletions, newest first
        self._search_rows: list[dict] = []  # the open search's hits, in shown order
        self._showing_search = False        # a query owns the pane, whatever the tree says
        self._request_items: list[dict] = []  # spoken requests + what they made

    def set_model(self, recent_rows, starred_groups, starred_rows, experiment_rows,
                  trash_rows, request_items=()):
        """Take the newly rebuilt gallery model the shelves render from."""
        self._recent_rows = recent_rows
        self._starred_groups = starred_groups
        self._starred_rows = starred_rows
        self._experiment_rows = experiment_rows
        self._trash_rows = trash_rows
        self._request_items = list(request_items)

    def show_enhancing(self, runs: dict):
        """Hand every visible tile the enhancement being made of its image.

        ``runs`` is ``{prompt_id: EnhancingRun}`` for the enhances in flight
        right now — the latest frame, how far along the run is, and how long it
        has been going. A tile not named there is handed ``None`` and goes back
        to resting. The tile keeps its own picture until a frame arrives — the
        base render is out and worth looking at, which is the point of
        generating it first — and gets it back when the run ends.
        """
        for prompt_id, tile in self._thumb_widgets.items():
            tile.set_enhancing(runs.get(prompt_id))

    # --- folder-tile overview ----------------------------------------------

    def show_widget(self, widget: QWidget):
        self._v._scroll.setWidget(widget)  # replaces & deletes the previous widget

    def show_empty(self):
        """Clear the pane to nothing on screen — no folder selected."""
        self._visible_ids = []
        self._visible_keys = []
        self._forget_recents_paging()
        self.show_widget(QWidget())

    def _reset_pane_state(self):
        """Forget what the outgoing pane held, before the incoming one fills it.

        Every renderer here starts by calling this (through :meth:`_new_tile_pane`
        or directly), so no renderer has to remember to clear the state of the one
        it is replacing — which is how a stale selection or a stale search flag
        would otherwise outlive the tiles it referred to.
        """
        self.clear_selection()
        self._v._reroll_tile = None  # re-created below only when this folder re-rolls
        self._inflight_cards = {}    # ...as are the live cards, by whichever pane draws them
        self._inflight_by_key = {}
        self._visible_ids = []
        self._visible_keys = []
        self._search_rows = []
        self._showing_search = False
        self._forget_recents_paging()

    def _new_tile_pane(self):
        """A fresh container whose tiles flow to fill the pane's width."""
        container = QWidget()
        flow = FlowLayout(container, spacing=_TILE_SPACING)
        self._reset_pane_state()
        return container, flow

    def restart_recents_listing(self):
        """Drop the pages the Recents shelf has drawn so its next render starts
        over at the newest item — what a change of the gallery's media filter
        deserves, being a new listing rather than a redraw of the old one at the
        offset the old one was read at."""
        self._forget_recents_paging()

    def _forget_recents_paging(self):
        """Drop the Recents shelf's paging state, because the pane it was drawn in
        is being replaced. :meth:`_render_recents` re-establishes it for the new
        one; anything else leaves it cleared, so a scroll of some *other* pane
        can't grow tiles into a layout that is no longer on screen."""
        self._recents_flow = None
        self._recents_drawn = 0

    def _add_folder_tile(self, flow, group, *, starred, context=""):
        """Build one folder tile, wire its click/context signals, and track it."""
        tile = FolderTile(
            group.key, group.label, self._preview_paths(group),
            len(gallery.rows_under(group)), starred=starred, context=context,
            level=gallery.folder_level(group), detail=gallery.folder_detail(group),
        )
        tile.clicked.connect(self._drill_into)
        tile.context_requested.connect(self._v._folder_context_menu)
        flow.addWidget(tile)
        self._visible_keys.append(group.key)

    def show_folder_tiles(self, groups):
        container, flow = self._new_tile_pane()
        for group in groups:
            self._add_folder_tile(flow, group, starred=group.starred)
        self.show_widget(container)

    # --- a folder the user composed: its gathered folders, wherever they live ---

    def show_custom_folder(self, group):
        """Render a custom folder (saved, or the live multi-selection): a tile per
        gathered folder, each captioned with its breadcrumb.

        The breadcrumb is what makes this readable at all — a grouping can hold two
        folders that are both called "30 steps" from opposite corners of the tree,
        so the bare label the hierarchy relies on isn't enough here (the Starred
        shelf shows its folders the same way, for the same reason).
        """
        members = gallery.child_groups(group)
        container, flow = self._new_tile_pane()
        for member in members:
            item = self._v._item_by_key.get(member.key)
            context = (self._v._tree_view.breadcrumb(item.parent())
                       if item is not None and item.parent() is not None else "")
            self._add_folder_tile(flow, member, starred=member.starred, context=context)
        self.show_widget(container if members else self._empty_state(
            f"“{group.label}” is empty.\n\nDrag folders from the list onto it, or "
            "pick several folders with Shift/Ctrl and group them."
        ))

    # --- the search results: whatever the query reached, wherever it lives ---

    def show_search_results(self, tiles, *, sort_mode: str, query: str, outcome,
                            scope: str = "", collapsed=(), on_section_toggled=None):
        """Fill the pane with ``tiles`` — the whole point of searching here rather
        than in the tree, since a thumbnail is recognizable and a folder name is
        not.

        Two orders, because a search answers two different questions. Newest-first
        is "where is the one I made recently"; by recipe is "which model and LoRA
        was that", and there the tiles are cut into a labelled band per
        combination rather than interleaved, so the answer is the heading you
        stopped scrolling at. Those bands fold shut on their headers — with a
        dozen combinations behind a broad query, being able to shut the ones you
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
            self.show_widget(
                self._empty_state(_search_empty_hint(outcome, query, scope)))
            self._showing_search = True
            return
        drawn = list(tiles)[:SEARCH_DRAW_LIMIT]
        container = self._sectioned_results(drawn, collapsed, on_section_toggled) \
            if sort_mode == search.SORT_RECIPE else self._flat_results(drawn)
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

        A column of flows rather than one flow with headings in it: a heading has
        to take the pane's whole width to read as a divider, and a FlowLayout has
        no notion of a row break — an item that happens to fit would sit beside it.
        The column is also what makes folding cheap, since a band is one widget to
        hide rather than a run of tiles to pick out of a shared layout.
        """
        container = QWidget()
        column = QVBoxLayout(container)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(_SECTION_SPACING)
        for heading, section in search.group_by_recipe(tiles):
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
                        on_toggled) -> QPushButton:
        """The band's foldable header: an arrow, the recipe, and how many are in it.

        A flat, full-width button rather than a label — the whole strip is the
        target, which is what a fold control has to be when the bands are tall
        enough that you are aiming at it after a scroll.
        """
        button = QPushButton()
        button.setObjectName("sectionHeading")
        button.setFlat(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        # Doubled "&" so Qt renders it literally instead of swallowing it as a
        # keyboard-accelerator marker, as CollapsibleSection's header does.
        title = f"{heading}   ({count})".replace("&", "&&")

        def paint(collapsed: bool):
            button.setText(f"{_ARROW_SHUT if collapsed else _ARROW_OPEN}  {title}")

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

    def _add_search_tile(self, flow, tile: SearchTile):
        """Draw one result — a folder tile or a single item — and record its place.

        The shown order matters beyond the drawing: Shift-select and the slideshow
        both read it, so it has to be the order the bands were laid out in rather
        than the order the search scored them.
        """
        if tile.group is not None:
            item = self._v._item_by_key.get(tile.group.key)
            context = (self._v._tree_view.breadcrumb(item.parent())
                       if item is not None and item.parent() is not None else "")
            self._add_folder_tile(flow, tile.group, starred=tile.group.starred,
                                  context=context)
        else:
            self._add_shelf_thumbnail(flow, tile.row)
        self._search_rows.extend(tile.rows or [tile.row])

    def showing_search(self) -> bool:
        """Whether a query owns the pane. Unlike the shelves this is not a tree
        row, so it is answered by what was last drawn rather than by what is
        selected: the tree keeps whatever folder it had while a search runs."""
        return self._showing_search

    # --- the Recents shelf: in-flight work, then recently finished items ----

    def show_recents_overview(self):
        """Render the Recents shelf: a card for every in-flight generation (queued
        or running, from a Generate tab or a gallery re-roll) atop the recently
        finished items. Clicking an in-flight card reveals where its job runs; a
        finished one previews in the info pane, right here on the shelf, the way a
        thumbnail does inside a folder — and double-clicking it jumps to its own
        folder. Opens with the info pane cleared, so it shows nothing until an
        item is picked."""
        self._v._title.set_display(RECENTS_LABEL)
        self._v._avg_label.setText("")
        self._v._clear_metadata()
        self._render_recents()
        self._v._sync_action_buttons()
        self._v._record_location()  # so Back can return to the shelf

    def _render_recents(self):
        """Draw the shelf: in-flight cards first (the newest, still-cooking work),
        then the finished thumbnails a page at a time; a hint when the media-type
        filter leaves neither. Both the cards and the thumbnails obey that filter.

        The shelf has no end — it lists every generation ever made — so it opens on
        one page and grows as it's scrolled into (:meth:`grow_recents`). A redraw of
        a shelf already on screen (a landing generation rebuilds the gallery under
        it) keeps the pages that were open, at the offset they were being read at,
        rather than snapping the user back up to the newest item.
        """
        drawn = self._recents_drawn
        offset = self._scroll_bar().value() if self._recents_flow is not None else 0
        container, flow = self._new_tile_pane()  # which clears both of those
        items = self._visible_inflight_items()
        self._inflight_signature = _inflight_signature(items)
        self._inflight_cards = {}
        self._inflight_by_key = {}
        for item in items:
            card = InFlightCard(item)
            card.clicked.connect(self._on_inflight_clicked)
            flow.addWidget(card)
            self._inflight_cards[item.key] = card
            self._inflight_by_key[item.key] = item
        # An empty shelf teaches how to fill it rather than showing a blank pane.
        if not (items or self._recent_rows):
            self.show_widget(self._empty_state(self._recents_empty_hint()))
            return
        self._recents_flow = flow
        self._draw_recents_page(max(_RECENTS_PAGE, drawn))
        self.show_widget(container)
        self._restore_scroll(offset)  # a no-op at 0: a shelf opened fresh starts on top

    def _draw_recents_page(self, count: int):
        """Add up to ``count`` more finished items to the open shelf, picking up
        where the last page left off. Short (or empty) at the end of the list."""
        page = self._recent_rows[self._recents_drawn:self._recents_drawn + count]
        for row in page:
            self._add_shelf_thumbnail(self._recents_flow, row)
        self._recents_drawn += len(page)

    def grow_recents(self, *_):
        """Draw the next page once the shelf is scrolled near its end — what makes
        Recents keep going instead of stopping at a fixed count.

        Wired to the browser scroll bar's value *and* its range: the value for the
        scrolling itself, the range because a pane only gets its real one once the
        page just drawn has been laid out, which is when a shelf redrawn back at
        the offset it was being read at finds itself already near the end. A range
        of zero is that not-yet-laid-out pane rather than a shelf scrolled to its
        bottom, so it waits rather than drawing pages nobody has scrolled to.
        """
        if self._recents_flow is None or self._recents_drawn >= len(self._recent_rows):
            return
        bar = self._scroll_bar()
        if bar.maximum() and bar.value() >= bar.maximum() - _RECENTS_REACH:
            self._draw_recents_page(_RECENTS_PAGE)

    def _scroll_bar(self):
        """The browser pane's vertical scroll bar: what the shelf grows off, and
        what a redraw puts back where the user was reading."""
        return self._v._scroll.verticalScrollBar()

    def _restore_scroll(self, offset: int):
        """Scroll the freshly drawn shelf back to ``offset``. The new pane hasn't
        been laid out yet, so the bar may have no range to move within — hence the
        second attempt once this turn's layout has run."""
        if not offset:
            return
        self._scroll_bar().setValue(offset)
        if self._scroll_bar().value() != offset:
            QTimer.singleShot(0, lambda: self._reapply_scroll(offset))

    def _reapply_scroll(self, offset: int):
        if self.showing_recents():  # unless the user has since navigated off it
            self._scroll_bar().setValue(offset)

    def _add_shelf_thumbnail(self, flow, row, corner_actions=None):
        """Build one finished-item tile for a shelf (Recents/Starred/Experiments):
        preview it here on a click, open its own folder on a double-click, drag it
        to a combine slot, and right-click it for the same star / enhance / delete
        menu a tile inside a folder offers. Returns the tile so a caller can add a
        shelf-specific action; ``corner_actions`` become the tile's hover controls
        (a review's keep/reject)."""
        tw = ThumbnailWidget(
            row["prompt_id"], row.get("thumbnail_path"), self._thumbnail_caption(row),
            media_type=gallery.media_type_of_row(row),  # a corner badge: image or video
            movie_path=self._v._animated_preview(row),  # videos loop; images stay still
            starred=bool(row.get("starred")),
            enhance=self._enhance_state(row),           # the plus in the picture's corner
            enhancing=self._v.enhancing_run(row),       # scrim + bar while one cooks
            corner_actions=corner_actions,
        )
        tw.clicked.connect(self._thumbnail_clicked)  # preview it here, on the shelf
        tw.double_clicked.connect(self._shelf_double_clicked)  # or open its folder
        # Every shelf gets the folder menu — an item is no less actionable for being
        # listed by when it was made or by its bookmark rather than by its settings.
        tw.context_requested.connect(self._thumbnail_context_menu)
        tw.control_triggered.connect(self._on_tile_control)
        self._wire_drag(tw)
        flow.addWidget(tw)
        self._visible_ids.append(row["prompt_id"])
        self._thumb_widgets[row["prompt_id"]] = tw
        return tw

    def _visible_inflight_items(self) -> list:
        """The in-flight items the shelf draws: what the gallery's media-type
        filter keeps, less the enhancements. The full set still decides whether the
        shelf exists at all; this narrows only what is drawn.

        A standalone enhance never earns a card of its own here, for the reason it
        never earns a folder in the tree: it is not a result, it is an upgrade of
        one, and the image it upgrades is already on this shelf wearing the
        "Enhancing…" scrim and streaming the run's frames. A card beside that tile
        says a second thing is being made, and clicking it goes nowhere — the
        folder it would open is the one the tree declines to grow. The bottom
        strip's queue still lists the job, which is where a run that has the GPU
        belongs.
        """
        media_types = self._v._media_types()
        return [it for it in self._inflight_items()
                if it.media_type in media_types and it.job_kind != ENHANCE_KIND]

    def _recents_empty_hint(self) -> str:
        """The teaching hint for an empty shelf, worded for the current filter —
        which media types (if any) it's looking for."""
        media_types = self._v._media_types()
        if not media_types:
            return ("No media types selected.\n\nCheck Images or Videos over the "
                    "folder list to bring your recent generations back.")
        noun = "generations" if len(media_types) == 2 else (
            "images" if "image" in media_types else "videos")
        return (f"No recent {noun} yet.\n\nItems you make — from a Generate tab or a "
                "gallery re-roll — collect here, newest first.")

    def showing_recents(self) -> bool:
        return (self._v._recents_item is not None
                and self._v._tree.currentItem() is self._v._recents_item)

    def refresh_inflight(self):
        """Between rebuilds, keep the in-flight cards live: push each tracked
        re-roll's latest frame into its card.

        Whichever pane drew them — the Recents shelf, or a settings folder with
        a batch cooking in it. Only the shelf re-renders on a change to the
        *set* of jobs (a defensive guard — a started or finished re-roll
        normally moves the DB fingerprint and forces a full rebuild anyway); a
        folder is rebuilt by that same fingerprint and must not be redrawn as
        the shelf. A pane holding no cards asks the database nothing.
        """
        if not self._inflight_cards and not self.showing_recents():
            return
        items = self._visible_inflight_items()
        if (self.showing_recents()
                and _inflight_signature(items) != self._inflight_signature):
            self._render_recents()
            return
        for item in items:
            self._inflight_by_key[item.key] = item  # keep the reveal current
            card = self._inflight_cards.get(item.key)
            if card is not None:
                card.update_item(item)

    def _inflight_items(self) -> list:
        """Every queued/running generation as a card model, in the order the queue
        will work through them.

        The database's running/pending rows are the source of truth for what's in
        flight — every generation is a gallery re-roll (a tab's Generate launches
        one too) — so a card shows even when no live job object is tracking a row
        (after a restart that hasn't re-adopted it, say). A re-roll tracked this
        session grafts on its live frame, progress, cancel and start time from its
        :class:`GenerationJob`; an untracked running row shows a plain card.

        The queue's own line orders them (:attr:`RerollController.queue_order`):
        nothing a row records says whether an image jumped ahead of a video, or
        whether a drag moved one. A row the line holds no job for — one a restart
        hasn't re-adopted — sorts to the back rather than jumping the queue on
        screen.

        The strip's rows carry more than the shelf's cards do — a price, a kind, a
        picture of what the job is made from or of the folder it will land in —
        and all of it is read off the row and the tree already in hand, so a poll
        costs one listing whatever the queue is showing.
        """
        reroll_by_pid = {job.prompt_id: (key, job)
                         for key, jobs in self._v._reroll.jobs_by_folder.items()
                         for job in jobs}
        # The jobs the queue is holding back rather than waiting on the GPU for,
        # so a row can say why the line isn't moving.
        held = {job.prompt_id for job in self._v._reroll.held_jobs()}
        # Which of these were asked for, and of what. One listing rather than a
        # lookup per job: the table is small and the queue rarely is.
        requested = {r["prompt_id"]: r["source_prompt_id"]
                     for r in self._v._db.list_requests()}
        image_index = None  # built lazily, only to place an untracked row's folder
        typical: dict[str, float | None] = {}  # workflow -> its usual run time
        stablemates: dict[str, tuple] = {}  # folder key -> thumbnails already in it
        rows = self._v._db.list_generations()
        # Every row's thumbnail, so a combine's run can show the video its
        # settings came from. Off the listing already in hand rather than a query
        # per job: the recipe video is an ordinary finished row somewhere in it.
        thumb_by_id = {r.get("prompt_id"): r.get("thumbnail_path") for r in rows}
        items = []
        for row in rows:
            if row.get("status") not in ("running", "pending"):
                continue
            pid = row["prompt_id"]
            tracked = reroll_by_pid.get(pid)
            if tracked is not None:
                folder_key, job = tracked
                frame, progress = job.last_preview, job.last_progress
                foreign = job.foreign_ahead  # another app's jobs in front of it, if any
                started = job.started_at  # None until ComfyUI actually starts it
                cancel = lambda p=pid: self._v._cancel_job(p)
            else:  # a running row no live job holds — no live frame, progress, or cancel
                if image_index is None:
                    image_index = gallery.build_image_config_index(self._v._image_rows)
                folder_key = gallery.settings_folder_key(row, image_index)
                frame, progress, cancel, foreign, started = None, None, None, None, None
            workflow_name = row.get("workflow_name") or ""
            params = gallery.parse_params(row.get("params_json"))
            kind = gallery.job_kind_label(workflow_name)
            items.append(InFlightItem(
                key=pid,
                caption=gallery.config_tab_title(workflow_name, params),
                status="running" if row.get("status") == "running" else "queued",
                frame=frame,
                reveal=lambda k=folder_key: self._reveal_reroll(k),
                media_type=gallery.media_type_of_row(row),  # image/video corner badge
                progress=progress,
                cancel=cancel,
                # Its folder auto-looping makes that button "Next seed": the press
                # discards this run and the loop launches another.
                auto_generating=self._v._auto.is_active(folder_key),
                foreign_ahead=foreign,
                held=pid in held,
                started_at=started,
                typical_seconds=self._typical_seconds(workflow_name, typical),
                job_kind=kind,
                requested=pid in requested,
                # Only where the start frame is what the run is *of*: a video
                # animating a picture, and an enhancement of one. An image
                # workflow that happens to take an input (the pose transfer's
                # structure image) is still an image being made, and its row is
                # placed the way every other image's is — by the folder it joins.
                source_image=(params.get("input_image")
                              if kind in SOURCE_FRAME_KINDS else None),
                # What to stand behind the wait: the image this run was
                # requested of, else the frame it animates or enhances.
                source_picture=self._source_picture(
                    requested.get(pid), thumb_by_id, params, kind),
                # What the Combine panel was asked for, when this run came from
                # it: the act off its dropdown, else the video whose settings the
                # run follows — shown gray beside the frame, being the recipe
                # rather than the result. Never both. An act names what the video
                # will do, which is the whole of what was chosen; the clip its
                # recipe was mined out of is an answer to a question the user
                # never asked, and a picture of a video they did not pick reads
                # as a job that is that video. A dropped video *is* the choice,
                # so there the picture is the only thing saying which.
                recipe_category=row.get("recipe_category") or "",
                recipe_thumbnail=(None if row.get("recipe_category")
                                  else thumb_by_id.get(row.get("recipe_video_id"))),
                folder_thumbnails=self._folder_thumbnails(folder_key, stablemates),
            ))
        place = {pid: i for i, pid in enumerate(self._v._reroll.queue_order)}
        items.sort(key=lambda it: (place.get(it.key, len(place)),
                                   it.status != "running"))
        return items

    @staticmethod
    def _source_picture(requested_of, thumb_by_id: dict, params: dict,
                        kind: str) -> str | None:
        """A file showing what a queued run came from, or ``None``.

        The image a request was made of comes first: a folder-wide request
        queues a run per image and every one of them animates nothing, so the
        thing it was asked about is the only picture it has. Failing that, the
        start frame an i2v or an enhance is built on.
        """
        asked_of = thumb_by_id.get(requested_of) if requested_of else None
        if asked_of:
            return asked_of
        if kind not in SOURCE_FRAME_KINDS:
            return None
        frame = resolve_input_image_path(params.get("input_image"))
        return str(frame) if frame is not None else None

    def _folder_thumbnails(self, folder_key: str, cache: dict) -> tuple:
        """A few thumbnails already in the folder a queued job is headed for.

        What a queued job with no picture of its own can be recognized by: its
        output doesn't exist yet, but the folder it will join is full of what the
        same settings made last time. Newest first, since ``list_generations``
        hands them back that way and the newest are what the user was just looking
        at.

        Read off the folder tree the gallery already built rather than by keying
        every row again — the tree is rebuilt when the rows change, and this runs
        on every poll. A folder with nothing in it yet (the first run of a new
        recipe, or an enhancement, whose product folds into the row it enhanced
        rather than landing anywhere) has no node in the tree at all and answers
        with nothing, which the row draws as no block rather than an empty grid.
        ``cache`` memoizes for the length of one pass, since an auto-generate loop
        fills the line with jobs from a single folder.
        """
        if folder_key not in cache:
            group = self._v._group_for_key(folder_key)
            rows = gallery.rows_under(group) if group is not None else []
            # Only what is finished and has a picture — the job asking, and
            # every other row still in the line, is exactly what has none.
            cache[folder_key] = tuple(
                row["thumbnail_path"] for row in rows if row.get("thumbnail_path")
            )[:FOLDER_CELLS]
        return cache[folder_key]

    def _typical_seconds(self, workflow_name: str, cache: dict):
        """What a whole run of ``workflow_name`` usually takes, for the running
        bar's countdown — memoized into ``cache`` for the length of one pass,
        since this list is rebuilt on every poll."""
        if workflow_name not in cache:
            cache[workflow_name] = timing.estimate_seconds(
                self._v._db.recent_durations(workflow_name)
            )
        return cache[workflow_name]

    def _reveal_reroll(self, key: str):
        """Open the folder a re-roll runs in and select its live tile."""
        item = self._v._item_by_key.get(key)
        if item is not None:
            self._v._tree.setCurrentItem(item)  # shows the folder and its re-roll tile
            self._v._select_reroll(key)

    def _on_inflight_clicked(self, key: str):
        item = self._inflight_by_key.get(key)
        if item is not None:
            item.reveal()

    def open_in_containing_folder(self, prompt_id: str):
        """Jump the browser pane to ``prompt_id``'s own folder and land on the item
        itself — its tile picked, highlighted and scrolled to, as if you'd navigated
        in and clicked it, not just auto-previewing the folder's first item. The
        double-click gesture on every shelf tile, and the info pane's "Go to
        folder"; a followed link (:meth:`GalleryView._on_source_link`) lands the
        same way."""
        self._v._on_source_link(prompt_id)

    def _shelf_double_clicked(self, prompt_id: str):
        """A shelf tile's double-click: go to the item's own folder, and keep the
        tab that lands there.

        Double-click means the same thing everywhere in the pane — this tab is
        one I'm staying on — whether it opens a folder on the way or not."""
        self.open_in_containing_folder(prompt_id)
        self._v.pin_config_tab()

    # --- the Experiments shelf: unreviewed background experiments ------------

    def show_experiments_overview(self):
        """Render the Experiments shelf: what the background experimenter has come
        up with since the user last looked, newest first, each tile wearing
        keep/reject hover controls. A kept item just leaves the queue — it has been
        in its own folder since it ran; a rejected one is trashed and teaches the
        policy what to avoid. Clicking previews the item right here and
        double-clicking opens its folder, like the other shelves."""
        self._v._title.set_display(EXPERIMENTS_LABEL)
        self._v._avg_label.setText("")
        self._v._clear_metadata()
        self._render_experiments()
        self._v._sync_action_buttons()
        self._v._record_location()  # so Back can return to the shelf

    def _render_experiments(self):
        container, flow = self._new_tile_pane()
        actions = [
            ("keep", icons.experiment_verdict_icon("up"),
             "Keep — add it to the gallery"),
            ("reject", icons.experiment_verdict_icon("down"),
             "Reject — trash it and steer future experiments away"),
        ]
        for row in self._experiment_rows:
            tw = self._add_shelf_thumbnail(flow, row, corner_actions=list(actions))
            tw.corner_action_triggered.connect(self._v._on_experiment_verdict)
        self.show_widget(container if self._experiment_rows
                         else self._empty_state(self._experiments_empty_hint()))

    def showing_experiments(self) -> bool:
        return (self._v._experiments_item is not None
                and self._v._tree.currentItem() is self._v._experiments_item)

    def _experiments_empty_hint(self) -> str:
        if is_branch_session():
            return ("Reviewing experiments is the live app's.\n\nA preview's "
                    "database is a copy, so a verdict recorded here would never "
                    "reach the live app — and rejecting would delete files its "
                    "own gallery still shows. The results are waiting there.")
        if self._v.experiments_enabled():
            return ("Nothing to review yet.\n\nEach time you close the app, "
                    "variations of your own generations are queued up and run "
                    "while you're away; they collect here for your verdict.")
        return ("Background experiments are off.\n\nTurn them on above and the "
                "time the app is closed will be spent trying variations of your "
                "work — new prompts on proven settings, nudged parameters, other "
                "models. Results collect here; your keep/reject verdicts steer "
                "what gets tried next.")

    # --- the Requests shelf: what you asked for out loud ---------------------

    def show_requests_overview(self):
        """Render the Requests shelf: what your spoken requests made, newest
        first — ordinary tiles, since what a request produced is an ordinary
        generation that happens to have been asked for out loud. What was heard
        and what it changed in the prompt show where the prompt does, in the
        config tab a click loads.

        One still generating shows as the live card the Recents shelf gives
        in-flight work, so a request you have just spoken is visibly under way
        rather than absent until it lands."""
        self._v._title.set_display(REQUESTS_LABEL)
        self._v._avg_label.setText("")
        self._v._clear_metadata()
        self._render_requests()
        self._v._sync_delete_button()
        self._v._record_location()  # so Back can return to the shelf

    def _render_requests(self):
        container, flow = self._new_tile_pane()
        cooking = {item.key: item for item in self._inflight_items()}
        for item in self._request_items:
            row = item["row"]
            live = cooking.get(row["prompt_id"])
            if live is not None:
                card = InFlightCard(live)
                card.clicked.connect(self._on_inflight_clicked)
                flow.addWidget(card)
                self._inflight_cards[live.key] = card
                self._inflight_by_key[live.key] = live
            elif gallery.produced_output(row):
                self._add_shelf_thumbnail(flow, row)
        self.show_widget(container if self._request_items
                         else self._empty_state(self._requests_empty_hint()))

    def showing_requests(self) -> bool:
        return (self._v._requests_item is not None
                and self._v._tree.currentItem() is self._v._requests_item)

    @staticmethod
    def _requests_empty_hint() -> str:
        return ("Nothing requested yet.\n\nWith a picture on screen, say "
                "“Request”, then what you want changed, then “over” — "
                "“Request… no hat… over”. The revision is queued straight away "
                "and lands here; open one and its prompt shows what moved.\n\n"
                "A folder's Request card lands here too — it asks the same "
                "thing of every image in that folder at once, typed rather "
                "than spoken.")

    # --- the Trash shelf: deleted items, still recoverable -------------------

    def show_trash_overview(self):
        """Render the Trash shelf: every deleted item the recovery bin is still
        holding, newest first, each tile wearing restore / delete-permanently
        hover controls and captioned with how long it has left. A restored item
        returns to its own folder, files and all; a purged one is gone for good,
        which is what the whole shelf exists to make deliberate rather than
        automatic."""
        self._v._title.set_display(TRASH_LABEL)
        self._v._avg_label.setText(self._trash_note())
        self._v._clear_metadata()
        self._render_trash()
        self._v._sync_action_buttons()
        self._v._record_location()  # so Back can return to the shelf

    def _render_trash(self):
        container, flow = self._new_tile_pane()
        actions = [
            ("restore", icons.recovery_action_icon("restore"),
             "Restore — put it and its files back where they were"),
            ("purge", icons.recovery_action_icon("purge"),
             "Delete permanently — end it now, without waiting out its window"),
        ]
        for row in self._trash_rows:
            tile = self._add_trash_thumbnail(flow, row, list(actions))
            tile.corner_action_triggered.connect(self._v._on_trash_action)
        self.show_widget(container if self._trash_rows
                         else self._empty_state(self._trash_empty_hint()))

    def _add_trash_thumbnail(self, flow, row, corner_actions):
        """One deleted item's tile — a shelf tile like any other, wired to
        everything a deleted item can still do.

        Its files are all in the trash rather than gone, and the bin kept its row
        whole, so it previews on a click, loops if it's a video, opens full size,
        plays in the shelf's slideshow and fills a config tab with the settings
        that made it — the whole point of a bin being that you can look before you
        decide. Double-clicking opens it as a Generate tab (the gesture a folder's
        tiles carry) rather than jumping to its folder, which is the one thing a
        deleted item hasn't got.

        What it doesn't get is the ordinary tile's right-click menu or its corner
        controls — star, enhance, delete all want a row in the gallery — and no
        drag to a combine slot, whose graphs read files out of ComfyUI's output
        folder, not ours. In their place the corners and the menu offer the two
        actions that do apply: restore, or end it now.
        """
        tile = ThumbnailWidget(
            row["prompt_id"], row.get("thumbnail_path"), self._trash_caption(row),
            media_type=gallery.media_type_of_row(row),  # a corner badge: image or video
            movie_path=self._v._animated_preview(row),  # videos loop; images stay still
            starred=bool(row.get("starred")),
            controls=False,       # its two acts are restore and purge, in the corners
            corner_actions=corner_actions,
        )
        tile.clicked.connect(self._thumbnail_clicked)          # preview it here
        tile.double_clicked.connect(self._thumbnail_double_clicked)  # or reuse its settings
        tile.context_requested.connect(self._trash_context_menu)
        flow.addWidget(tile)
        self._visible_ids.append(row["prompt_id"])
        self._thumb_widgets[row["prompt_id"]] = tile
        return tile

    def _trash_context_menu(self, prompt_id: str, global_pos):
        """Right-click a deleted tile: restore or permanently delete the picked
        items — the same two actions its hover corners carry, reachable for a
        whole selection at once. Right-clicking a tile outside the selection
        first narrows to it, as the gallery's own tile menu does."""
        if prompt_id not in self._selected_ids:
            self.apply_selection(prompt_id, Qt.KeyboardModifier.NoModifier)
        ids = self.selected_prompt_ids()
        suffix = f" {len(ids)} item{'s' if len(ids) != 1 else ''}"
        menu = QMenu(self._v)
        restore_action = menu.addAction("Restore" + suffix)
        purge_action = menu.addAction("Delete" + suffix + " permanently")
        chosen = menu.exec(global_pos)
        if chosen is restore_action:
            self._v.restore_from_trash(ids)
        elif chosen is purge_action:
            self._v.purge_from_trash(ids)

    @staticmethod
    def _trash_caption(row) -> str:
        """A deleted tile's caption: what the item was, then how long it has left.

        The remaining time is the one fact a gallery caption can't carry and this
        shelf can't do without — an item is only recoverable until it isn't.
        """
        days = row.get("days_left")
        return f"{BrowserPane._thumbnail_caption(row)} · {days}d left" if days \
            else f"{BrowserPane._thumbnail_caption(row)} · expiring"

    def _trash_note(self) -> str:
        """The line under the header stating the retention promise — shown only
        with something on the shelf, since the empty state already says it."""
        if not self._trash_rows:
            return ""
        return (f"Deleted items are held here for {RETENTION_DAYS} days, then "
                "removed for good.")

    def _trash_empty_hint(self) -> str:
        if is_branch_session():
            return ("Nothing deleted in this preview.\n\nDelete something and it "
                    "waits here to be restored, the way it would in the live app. "
                    "What the live app is holding stays out of reach: those files "
                    "sit in its trash, and a preview reaching in would move them "
                    "out from under the rows it is still showing.")
        return (f"Nothing deleted.\n\nItems you delete wait here for "
                f"{RETENTION_DAYS} days — restore one, or end it early — before "
                "they're removed for good.")

    def showing_trash(self) -> bool:
        return (self._v._trash_item is not None
                and self._v._tree.currentItem() is self._v._trash_item)

    # --- the Starred shelf: every bookmark — items and folders — in one place ---

    def show_starred_overview(self):
        """Render the Starred shelf: the individual starred images and videos as
        thumbnails, then one tile per bookmarked folder (each captioned with its
        breadcrumb so identically-named folders stay tellable apart). A starred
        item previews here on click and opens its own folder on double-click; a
        folder tile lists its sub-folders."""
        self._v._title.set_display(_STARRED_TITLE)
        self._v._avg_label.setText("")
        self._v._clear_metadata()
        self._show_starred(self._starred_groups, self._starred_rows)
        self._v._sync_action_buttons()
        self._v._record_location()  # so Back can return to the shelf

    def _show_starred(self, groups, rows):
        container, flow = self._new_tile_pane()
        for row in rows:
            self._add_shelf_thumbnail(flow, row)
        for group in groups:
            item = self._v._item_by_key.get(group.key)
            context = self._v._tree_view.breadcrumb(item.parent()) if item and item.parent() else ""
            self._add_folder_tile(flow, group, starred=False, context=context)
        # An empty shelf teaches how to fill it rather than showing a blank pane.
        self.show_widget(container if (rows or groups) else self._empty_state(
            "No bookmarks yet.\n\nStar an image or video from its right-click menu, "
            "or star a folder from the list, to collect them here."
        ))

    def showing_starred(self) -> bool:
        return (self._v._starred_item is not None
                and self._v._tree.currentItem() is self._v._starred_item)

    @staticmethod
    def _empty_state(text: str) -> QWidget:
        """A centered hint filling an otherwise-blank shelf pane."""
        label = QLabel(text)
        label.setObjectName("estimateLabel")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        label.setContentsMargins(16, 24, 16, 16)
        return label

    @staticmethod
    def _thumbnail_caption(row) -> str:
        """A thumbnail's caption: its seed, else a snippet of its prompt."""
        seed = row.get("seed")
        if seed is not None:
            return f"seed {seed}"
        return (row.get("positive_prompt") or "")[:40] or "(no prompt)"

    # --- what the open shelf collects (the slideshow plays it) --------------

    def shelf_rows(self) -> list[dict] | None:
        """Every generation the open shelf collects, in shelf order — or ``None``
        off the shelves, where a folder is what's on screen instead.

        The slideshow plays these, so they have to match the tiles: Recents is its
        listed items (the media-type filter already applied), Starred is its
        starred items plus everything under each bookmarked folder, since a folder
        tile there stands for its whole folder, Experiments is its unreviewed
        queue, Requests is what your spoken requests made, and Trash is what the
        bin is holding — deleted is not unwatchable, and a shelf of items you are
        deciding whether to keep is exactly one you want to sit and look through.
        A starred item inside a starred folder is one item, so repeats drop out.
        A running search collects too — its hits are a gathered collection
        exactly as a shelf's are, and sitting through what a search turned up is
        one of the better reasons to have run it.
        """
        if self.showing_search():
            return list(self._search_rows)
        return self.selected_shelf_rows()

    def selected_shelf_rows(self) -> list[dict] | None:
        """What the *selected* shelf collects, whatever is currently drawn.

        The same answer as :meth:`shelf_rows` off a search, and the one that
        matters during one: a search standing on a shelf is scoped to that
        shelf's items, and the results now on screen are no use for working out
        what those are.
        """
        if self.showing_recents():
            return list(self._recent_rows)
        if self.showing_starred():
            return _unique_rows(self._starred_rows + [
                row for group in self._starred_groups for row in gallery.rows_under(group)
            ])
        if self.showing_experiments():
            return list(self._experiment_rows)
        if self.showing_requests():
            return [item["row"] for item in self._request_items]
        if self.showing_trash():
            return list(self._trash_rows)
        return None

    # --- the thumbnail grid: a settings leaf's generations ------------------

    def show_thumbnails(self, group):
        container, flow = self._new_tile_pane()
        # An i2v folder's items carry per-seed re-roll hover controls; its rows
        # all share the one workflow, so the kind is decided once. Media-gated
        # because the enhancer is image-conditioned too, but its items have no
        # video seed to offer.
        i2v = bool(group.rows) \
            and gallery.is_image_conditioned(group.rows[0].get("workflow_name")) \
            and gallery.media_type_of_row(group.rows[0]) == "video"
        # The re-roll tile leads the flow so it sits beside the newest item
        # (thumbnails are sorted newest-first). A generation running in this folder —
        # a re-roll, which is also what a tab's Generate now is — is this tile: it
        # shows the live frame, so the running row is left out of the static grid
        # below rather than drawn as a broken, output-less thumbnail.
        if self._v._can_reroll(group):
            self._v._add_reroll_tile(flow, group)
        # ...and beside it its mirror: the same seeds again, said differently.
        if self._v._can_request_changes(group):
            self._v._add_folder_request_tile(flow, group)
        self._add_folder_inflight_cards(flow, group)
        for row in group.rows:
            if not gallery.produced_output(row):
                continue  # still in flight — represented by the RerollTile, not a tile
            tw = ThumbnailWidget(
                row["prompt_id"], row.get("thumbnail_path"), self._thumbnail_caption(row),
                movie_path=self._v._animated_preview(row),  # videos loop; images stay still
                starred=bool(row.get("starred")),
                enhance=self._enhance_state(row),           # the plus in the picture's corner
                enhancing=self._v.enhancing_run(row),       # scrim + bar while one cooks
                corner_actions=self._seed_reroll_actions(row) if i2v else None,
            )
            tw.clicked.connect(self._thumbnail_clicked)
            tw.double_clicked.connect(self._thumbnail_double_clicked)
            tw.context_requested.connect(self._thumbnail_context_menu)
            tw.control_triggered.connect(self._on_tile_control)
            if i2v:
                tw.corner_action_triggered.connect(self._v._reroll_item_seed)
            self._wire_drag(tw)
            flow.addWidget(tw)
            self._visible_ids.append(row["prompt_id"])
            self._thumb_widgets[row["prompt_id"]] = tw
        self.show_widget(container)

    def _add_folder_inflight_cards(self, flow, group):
        """A card for every other run still cooking in this folder.

        The re-roll tile shows the one in front, and used to be the whole of
        what a folder said about work in flight — so a request over a folder,
        which queues a run per image at once, showed up as a single card the
        images then arrived through one at a time. They are all being made;
        the folder shows them all, each on the image it was asked of
        (:mod:`origenerator.gui.blurred`), and each turns into its own
        thumbnail where it stands.

        Newest first, like everything else in the grid: an in-flight row is
        the newest thing in the folder, so the cards lead the finished
        pictures. Costs nothing in a folder with nothing cooking, which is
        almost all of them — the listing behind the cards is only built once
        there is a card to build.
        """
        leading = self._v._reroll.job_for(group.key)
        in_front = leading.prompt_id if leading is not None else None
        waiting = [row["prompt_id"] for row in group.rows
                   if not gallery.produced_output(row)
                   and row["prompt_id"] != in_front]
        if not waiting:
            return
        items = {item.key: item for item in self._visible_inflight_items()}
        for pid in waiting:
            item = items.get(pid)
            if item is None:
                continue  # a row no longer in flight by the time this drew
            card = InFlightCard(item)
            card.clicked.connect(self._on_inflight_clicked)
            flow.addWidget(card)
            self._inflight_cards[item.key] = card
            self._inflight_by_key[item.key] = item

    def _seed_reroll_actions(self, row) -> list:
        """The per-seed re-roll hover controls for an i2v item: always the video
        seed (new motion of the same frame), plus the image seed (a new frame)
        when the item's start frame is itself a re-buildable generation."""
        actions = [("video", icons.reroll_seed_icon("video"), "Randomize video seed")]
        if gallery.find_source_image_id(row, self._v._image_rows) is not None:
            actions.append(("image", icons.reroll_seed_icon("image"), "Randomize image seed"))
        return actions

    @staticmethod
    def _preview_paths(group) -> list[str]:
        paths = []
        for row in gallery.rows_under(group):
            thumb = row.get("thumbnail_path")
            if thumb and Path(thumb).exists():
                paths.append(thumb)
                if len(paths) >= _PREVIEW_COUNT:
                    break
        return paths

    def _wire_drag(self, tw: ThumbnailWidget):
        """Light the combine slot a tile fits while it's being dragged out."""
        tw.drag_started.connect(self._v._on_generation_drag_started)
        tw.drag_ended.connect(self._v._on_generation_drag_ended)

    def _drill_into(self, key: str):
        """Open a folder tile's folder. Clicking one is a decision to go there, so
        it puts a running search away first — a search's results are folder tiles
        too, and this is how they open; without it the box would still be full
        while the pane shows the folder it drilled into."""
        item = self._v._item_by_key.get(key)
        if item is not None:
            self._v._leave_search()
            self._v._tree.setCurrentItem(item)

    def visible_prompt_ids(self) -> list[str]:
        return list(self._visible_ids)

    def visible_folder_keys(self) -> list[str]:
        return list(self._visible_keys)

    # --- multi-selection ---------------------------------------------------

    def _thumbnail_clicked(self, prompt_id: str):
        self.apply_selection(prompt_id, QApplication.keyboardModifiers())
        self._v._on_thumbnail_clicked(prompt_id)  # records the visit itself

    def _thumbnail_double_clicked(self, prompt_id: str):
        """Open a thumbnail as a Generate tab and keep that tab.

        The first click has already loaded it into the pane's preview tab; the
        second says to stay there, so the tab stops being the one the next click
        replaces. Browsing costs one tab however far you go; deciding to work on
        something costs the double-click that keeps it."""
        self._v._on_thumbnail_clicked(prompt_id)  # make it the selected generation
        self._v.pin_config_tab()

    def apply_selection(self, prompt_id: str, modifiers):
        """Update the multi-select set the way the held modifiers dictate.

        Ctrl toggles one tile; Shift extends a contiguous run from the anchor;
        a plain click resets to just this tile. Mirrors a typical file browser.
        """
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        if ctrl:
            self._selected_ids ^= {prompt_id}
            self._selection_anchor = prompt_id
        elif shift and self._selection_anchor in self._visible_ids \
                and prompt_id in self._visible_ids:
            a = self._visible_ids.index(self._selection_anchor)
            b = self._visible_ids.index(prompt_id)
            lo, hi = sorted((a, b))
            self._selected_ids = set(self._visible_ids[lo:hi + 1])
        else:
            self._selected_ids = {prompt_id}
            self._selection_anchor = prompt_id
        self._refresh_selection_highlights()

    def reveal_tile(self, prompt_id: str):
        """Land on a tile the way arriving from elsewhere should: picked, and
        scrolled to if it sits outside the visible part of the pane. What a
        followed link needs — a folder of dozens otherwise leaves you looking at
        its newest items with the one you asked for highlighted off-screen."""
        self.apply_selection(prompt_id, Qt.KeyboardModifier.NoModifier)
        widget = self._thumb_widgets.get(prompt_id)
        if widget is None:
            return  # nothing drawn for it here (an in-flight row, a shelf page away)
        self._scroll_to(widget)
        # The pane it was just drawn in hasn't been laid out yet, so that first
        # attempt had no real tile position to aim at — hence a second one once
        # this turn's layout has run (as :meth:`_restore_scroll` does).
        QTimer.singleShot(0, lambda: self._reapply_reveal(prompt_id, widget))

    def _reapply_reveal(self, prompt_id: str, widget):
        """Scroll to a revealed tile again after layout — unless the pane has since
        been redrawn or navigated away from, in which case that tile is gone and
        the user's new view is not ours to move."""
        if self._thumb_widgets.get(prompt_id) is widget:
            self._scroll_to(widget)

    def _scroll_to(self, widget):
        self._v._scroll.ensureWidgetVisible(widget, 0, _REVEAL_MARGIN)

    def _refresh_selection_highlights(self):
        for pid, widget in self._thumb_widgets.items():
            widget.set_selected(pid in self._selected_ids)
        self._v._sync_action_buttons()

    def clear_selection(self):
        self._selected_ids = set()
        self._selection_anchor = None
        self._thumb_widgets = {}
        self._v._sync_action_buttons()

    def clear_thumbnail_selection(self):
        """Drop the thumbnail multi-selection and its highlights while keeping the
        on-screen tiles (unlike a rebuild), so picking the re-roll deselects them."""
        self._selected_ids = set()
        self._selection_anchor = None
        self._refresh_selection_highlights()

    @property
    def selected_ids(self) -> set:
        """The picked thumbnails' prompt_ids (read-only), for the delete button."""
        return self._selected_ids

    def selected_prompt_ids(self) -> list[str]:
        return [pid for pid in self._visible_ids if pid in self._selected_ids]

    def _thumbnail_context_menu(self, prompt_id: str, global_pos):
        """Right-click menu for a thumbnail: go to its folder, star/unstar,
        enhance or delete the picked item(s).

        Right-clicking a tile that isn't part of the current selection first
        selects just it, so the menu always acts on something visible. The menu
        itself is the gallery's, not this pane's — the preview in a config tab
        raises the very same one over the very same generation
        (:meth:`~origenerator.gui.gallery_view.GalleryView.generation_menu`).
        """
        if prompt_id not in self._selected_ids:
            self.apply_selection(prompt_id, Qt.KeyboardModifier.NoModifier)
            self._v._on_thumbnail_clicked(prompt_id)
        self._v.generation_menu(self.selected_prompt_ids(), global_pos)

    def _on_tile_control(self, prompt_id: str, action: str):
        """A tile's corner control was pressed: bookmark, bin or enhance THIS one.

        One item, never the selection — the control is drawn on a particular
        picture, in that picture's own corner, so it has already said which item
        it is about. The menu is where a whole selection is acted on.
        """
        self._v.run_item_action(prompt_id, action)

    def _enhance_state(self, row) -> str | None:
        """What the plus in this row's bottom-right corner has to say, at the
        Enhance panel's current settings (:func:`corner_controls.enhance_state`)."""
        return enhance_state(row, self._v._enhance_settings)

    def refresh_enhance_corners(self):
        """Re-read every drawn tile's enhance corner, without rebuilding the pane.

        Turning a knob in the Enhance subpanel changes what every picture on
        screen would get from a press — an image holding the version the panel
        described a moment ago is now one enhancement short of the new one — and
        none of those tiles were touched, so nothing else would tell them.
        """
        for prompt_id, tile in self._thumb_widgets.items():
            row = self._v._db.get_generation(prompt_id)
            if row is not None:
                tile.set_enhance(self._enhance_state(row))
