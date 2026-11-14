from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import NamedTuple

import shiboken6
from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtWidgets import (
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
from origenerator.gui import folder_icons, icons
from origenerator.gui.collapsible_section import FOLD, FoldHeader
from origenerator.gui.corner_buttons import enhance_state
from origenerator.gui.deferred import defer
from origenerator.gui.flow_layout import FlowLayout
from origenerator.gui.folder_tile import FolderMarks, FolderTile
from origenerator.gui.inflight import (
    CANCEL_TEXT,
    InFlightItem,
    cancel_tooltip,
    stop_populate_text,
    stop_populate_tooltip,
)
from origenerator.gui.inflight_items import (
    InFlightCallbacks,
    InFlightItems,
    InFlightSources,
)
from origenerator.gui.inflight_tile import InFlightTile
from origenerator.gui.item_tile import (
    CornerButton,
    ItemTile,
    TileAppearance,
    restore_offer_of,
)
from origenerator.gui.pane_place import (
    PanePlace,
    bring_into_view,
    place_of,
    show_the_tiles_qt_queued_to_show,
    stand_at,
)
from origenerator.gui.picking import Picking
from origenerator.item_shape import base_of, filter_rows, key_holds, split_key
from origenerator.library_views import LibrarySnapshot
from origenerator.media import MediaType

REROLL_VIDEO = "video"
REROLL_IMAGE = "image"

_TILE_SPACING = GAP_MEDIUM
_PREVIEW_COUNT = 4
_PAGE = 50
_ROWS_PAST_A_REVEAL = 3
_MOST_TILES_ACROSS = 4
_NEIGHBORS_PAST_A_REVEAL = _ROWS_PAST_A_REVEAL * _MOST_TILES_ACROSS
_REACH = 600
_ROOM_ABOVE_A_SECTIONS_HEADING = GAP_DIALOG
SEARCH_DRAW_LIMIT = 200


class GalleryPaneScrollArea(QScrollArea):
    background_clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.background_clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


def _search_empty_hint(outcome, query: str, scope: str) -> str:
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


class _KeptTiles:
    def __init__(self, tiles=None, wiring=None):
        self._tiles = dict(tiles or {})
        self._wiring = dict(wiring or {})

    def take(self, prompt_id: str, look: tuple, wiring: str):
        tile = self._tiles.pop(prompt_id, None)
        if (tile is None or not shiboken6.isValid(tile) or tile.look != look
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
    modify_batch: QWidget | None = None
    generating: QWidget | None = None


@dataclass(frozen=True)
class TreeNavigation:
    selected_folder_key: Callable[[], str | None]
    folder_context: Callable[[str], str]
    group_for_key: Callable[[str], object]


@dataclass(frozen=True)
class PaneHost:
    image_rows: Callable[[], list]
    animated_preview: Callable[[dict], str | None]
    enhancing: Callable[[], object]
    experiments_enabled: Callable[[], bool]
    lead_tiles: Callable[[object], LeadTiles]
    item_name: Callable[[str], str]
    tree: TreeNavigation


class GalleryPane(QObject):
    thumbnail_activated = Signal(str)
    tab_pin_requested = Signal()
    slideshow_requested = Signal(str)
    item_jump_requested = Signal(str)
    folder_open_requested = Signal(str)
    reveal_reroll_requested = Signal(str)
    folder_menu_requested = Signal(str, QPoint)
    menu_requested = Signal(list, QPoint)
    trash_menu_requested = Signal(QPoint)
    item_action_triggered = Signal(str, str)
    seed_reroll_requested = Signal(str, str)
    experiment_verdict = Signal(str, str)
    trash_action_triggered = Signal(str, str)
    cancel_requested = Signal(str)
    selection_changed = Signal()
    pane_reset = Signal()

    def __init__(self, scroll, db, jobs, populate, host: PaneHost):
        super().__init__()
        self._scroll = scroll
        self._db = db
        self._jobs = jobs
        self._tree = host.tree
        self._host = host
        self._queue_model = InFlightItems(
            InFlightSources(db=db, jobs=jobs, populate=populate, tree=self._tree),
            image_rows=host.image_rows,
            image_index=lambda: self._model.image_index,
            callbacks=InFlightCallbacks(
                cancel=self.cancel_requested.emit,
                reveal=self.reveal_reroll_requested.emit,
                go_to_item=self.item_jump_requested.emit,
                shield=jobs.shield),
        )
        self._renders = {
            LATEST_KEY: self._render_latest,
            FAVORITES_KEY: lambda: self._show_gathered(
                self._favorite_items(self._collection_shape, self._collection_folder),
                self._favorite_folders(self._collection_shape, self._collection_folder),
                show_favorites=False, empty=_NO_FAVORITES),
            ENHANCED_KEY: lambda: self._show_gathered(
                self._open_collection_rows(ENHANCED_KEY), (),
                show_favorites=False, empty=_NO_ENHANCED),
            EXPERIMENTS_KEY: self._render_experiments,
            TRASH_KEY: self._render_trash,
        }
        self._selection = Picking()
        self._listed_folders: list[str] = []
        self._thumb_widgets: dict[str, ItemTile] = {}
        self._wired: dict[str, str] = {}
        self._kept = _KeptTiles()
        self._inflight_tiles: dict[str, InFlightTile] = {}
        self._inflight_by_key: dict[str, InFlightItem] = {}
        self._inflight_signature: tuple = ()
        self._model = LibrarySnapshot([])
        self._pages = _Pages()
        self._search_rows: list[dict] = []
        self._showing_search = False
        self._collection_shape: str | None = None
        self._collection_folder = gallery.ALL_KEY
        scroll.verticalScrollBar().valueChanged.connect(self.follow_the_scroll)
        scroll.verticalScrollBar().rangeChanged.connect(self.follow_the_scroll)

    def set_model(self, model: LibrarySnapshot):
        self._model = model

    def _open_collection_rows(self, collection: str) -> list[dict]:
        return self._model.in_collection(collection, self._collection_shape,
                                         self._collection_folder)

    def show_enhancing(self, runs: dict):
        for prompt_id, tile in self._thumb_widgets.items():
            tile.set_enhancing(runs.get(prompt_id))

    def show_widget(self, widget: QWidget):
        self._kept = _KeptTiles()
        self._pages = self._pages.ended()
        self._scroll.setWidget(widget)  # Qt deletes the previous widget

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
        # Qt has not laid out a pane drawn this turn, so its tiles have no positions yet.
        defer(self._scroll, self.follow_the_scroll)

    def show_empty(self):
        self._reset_pane_state()
        self.show_widget(QWidget())

    def _reset_pane_state(self):
        self.clear_selection()
        self.pane_reset.emit()
        self._inflight_tiles = {}
        self._inflight_by_key = {}
        self._selection.forget_what_was_shown()
        self._listed_folders = []
        self._search_rows = []
        self._showing_search = False

    def _fresh_tile_pane(self):
        container = QWidget()
        flow = FlowLayout(container, spacing=_TILE_SPACING)
        self._kept = _KeptTiles(self._thumb_widgets, self._wired)
        self._reset_pane_state()
        return container, flow

    def _add_folder_tile(self, flow, group, *, favorite, context=""):
        tile = FolderTile(
            group.key, group.label, self._preview_paths(group),
            len(gallery.rows_under(group)),
            FolderMarks(favorite, context, folder_icons.folder_kind_icon(group)),
        )
        tile.clicked.connect(self._drill_into)
        tile.context_requested.connect(self.folder_menu_requested)
        flow.addWidget(tile)

    def reveal_folder(self, folder_key: str) -> bool:
        self._pages.draw_past(lambda entry: entry.folder is not None
                              and key_holds(entry.folder, folder_key))
        drawn = self._scroll.widget()
        if drawn is None:
            return False
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
            flow.add_full_row(_time_heading("\u00a0"))
        self._show_paged(container, [
            _Entry(partial(self._add_folder_tile, flow, group, favorite=group.favorite),
                   folder=group.key)
            for group in groups])

    def _add_collection_tile(self, flow, key: str):
        rows = self.rows_for_collection(key)
        collection = folder_collection(base_of(key))
        tile = FolderTile(key, COLLECTION_LABELS[collection.which], _thumbnails_of(rows), len(rows),
                          FolderMarks(kind_icon=folder_icons.collection_kind_icon(collection.which)))
        tile.clicked.connect(self._drill_into)
        flow.addWidget(tile)

    def show_custom_collection(self, group):
        self._show_gathered(group.rows, gallery.child_groups(group), show_favorites=True,
                            empty=f"“{group.label}” is empty.\n\nDrag folders from the list, "
                                  "or items, onto it, or pick several folders with "
                                  "Shift/Ctrl and group them.")

    def _show_gathered(self, rows, groups, *, show_favorites: bool, empty: str):
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

    def show_search_results(self, tiles, terms: search.SearchTerms):
        self._reset_pane_state()
        if not tiles:
            self.show_widget(self._empty_state(
                "" if terms.still_searching
                else _search_empty_hint(terms.outcome, terms.query, terms.scope)))
            self._showing_search = True
            return
        drawn = list(tiles)[:SEARCH_DRAW_LIMIT]
        container = self._sectioned_results(drawn, terms.collapsed, terms.on_section_toggled) \
            if terms.sort_mode == search.SORT_MODEL_LORA else self._flat_results(drawn)
        self.show_widget(container)
        self._showing_search = True

    def _flat_results(self, tiles) -> QWidget:
        container = QWidget()
        flow = FlowLayout(container, spacing=_TILE_SPACING)
        for tile in tiles:
            self._add_search_tile(flow, tile)
        return container

    def _sectioned_results(self, tiles, collapsed, on_toggled) -> QWidget:
        container = QWidget()
        column = QVBoxLayout(container)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(_ROOM_ABOVE_A_SECTIONS_HEADING)
        for heading, section in search.group_by_model_lora(tiles):
            section_widget = QWidget()
            section_flow = FlowLayout(section_widget, spacing=_TILE_SPACING)
            shut = heading in collapsed
            column.addWidget(
                self._section_header(heading, len(section), section_widget, shut, on_toggled))
            for tile in section:
                self._add_search_tile(section_flow, tile)
            section_widget.setVisible(not shut)
            column.addWidget(section_widget)
        column.addStretch(1)
        return container

    @staticmethod
    def _section_header(heading: str, count: int, section_widget: QWidget, shut: bool,
                        on_toggled) -> FoldHeader:
        button = FoldHeader(warns=False)
        button.setObjectName("tileGroupHeading")
        button.setFlat(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setText(f"{heading}   ({count})")

        def paint(collapsed: bool):
            button.set_fold(FOLD[collapsed])

        # Qt: isVisible() is False for any widget whose window is not yet shown, so the fold state is kept here.
        state = {"shut": shut}

        def toggle():
            state["shut"] = not state["shut"]
            section_widget.setVisible(not state["shut"])
            paint(state["shut"])
            if on_toggled is not None:
                on_toggled(heading, state["shut"])

        button.clicked.connect(toggle)
        paint(shut)
        return button

    def _add_search_tile(self, flow, tile: search.SearchTile):
        if tile.group is not None:
            self._add_folder_tile(flow, tile.group, favorite=tile.group.favorite,
                                  context=self._tree.folder_context(tile.group.key))
            self._listed_folders.append(tile.group.key)
        else:
            (self._add_trash_thumbnail if "days_in_trash" in tile.row
             else self._add_collection_thumbnail)(flow, tile.row)
            self._selection.note_shown(tile.row["prompt_id"])
        self._search_rows.extend(tile.rows if tile.group is not None else tile.rows or [tile.row])

    def showing_search(self) -> bool:
        return self._showing_search

    def show_collection(self, key: str, shape: str | None = None):
        collection = folder_collection(key)
        if collection is None:
            return
        self._collection_shape = shape
        self._collection_folder = collection.folder
        self._renders[collection.which]()

    def _render_latest(self):
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
        if not (items or rows):
            self.show_widget(self._empty_state(self._latest_empty_hint()))
            return
        self._show_paged(container, _between_headings(
            flow, rows, headings, lambda row: self._add_collection_thumbnail(flow, row)))

    def follow_the_scroll(self, *_):
        drawn, seen = self._scroll.widget(), self._scroll.viewport()
        if drawn is None:
            return
        top = self._scroll_bar().value()
        while self._pages.more() and (_drawn_height(drawn, seen.width())
                                      - top - seen.height() < _REACH):
            self._pages.draw(_PAGE)
            # Qt only queues the show of a tile added to a page on screen; until it runs the page measures as nothing.
            show_the_tiles_qt_queued_to_show(drawn)
        _play_only_what_is_in_sight(drawn, self._thumb_widgets.values(),
                                    top - _REACH, top + seen.height() + _REACH)

    def _scroll_bar(self):
        return self._scroll.verticalScrollBar()

    def _add_collection_thumbnail(self, flow, row, corner_buttons=None):
        def wire(tw):
            self._wire_picking(tw)
            tw.double_clicked.connect(self._collection_double_clicked)
            tw.context_requested.connect(self._thumbnail_context_menu)
            tw.control_triggered.connect(self._on_tile_control)
            if corner_buttons:
                tw.corner_button_triggered.connect(self.experiment_verdict)

        return self._draw_tile(
            flow, row, _REVIEW_TILE if corner_buttons else _COLLECTION_TILE, wire,
            TileAppearance(
                media_type=gallery.media_type_of_row(row),
                movie_path=self._host.animated_preview(row),
                favorite=bool(row.get("starred")),
                enhance=self._enhance_state(row),
                enhancing=self._host.enhancing().run_of(row),
                corner_buttons=corner_buttons),
        )

    def _draw_tile(self, flow, row, wiring: str, wire,
                   appearance: TileAppearance) -> ItemTile:
        prompt_id = row["prompt_id"]
        thumb_path = row.get("thumbnail_path")
        caption = self._host.item_name(prompt_id) if appearance.caption is None else appearance.caption
        tile = self._kept.take(
            prompt_id, ItemTile.look_of(prompt_id, thumb_path, caption, appearance),
            wiring)
        if tile is None:
            tile = ItemTile(prompt_id, thumb_path, caption, appearance)
            wire(tile)
        else:
            tile.set_favorite(appearance.favorite)
            tile.set_enhance(appearance.enhance)
            tile.set_enhancing(appearance.enhancing)
        flow.addWidget(tile)
        tile.set_selected(self._selection.holds(prompt_id))
        self._thumb_widgets[prompt_id] = tile
        self._wired[prompt_id] = wiring
        return tile

    def _tile_items(self, rows=None, requests=None) -> list[InFlightItem]:
        return [item for item in self.inflight_items(rows, requests)
                if item.job_kind != gallery.JobKind.ENHANCE]

    def _latest_inflight_items(self, rows=None, requests=None) -> list[InFlightItem]:
        if rows is None:
            rows = self._db.list_generations()
        in_progress = filter_rows([row for row in rows if gallery.is_in_progress(row)],
                                  self._collection_shape)
        held = {row["prompt_id"] for row in self._model.placement(self._collection_shape)
                .held_by(self._collection_folder, in_progress)}
        return _back_of_the_line_first(self._tile_items(rows, requests), held)

    def _latest_empty_hint(self) -> str:
        noun = next((label.lower() for kind, label in gallery.MEDIA_LABELS.items()
                     if key_holds(kind, self._collection_folder)), "generations")
        return (f"No recent {noun} yet.\n\nItems you make — from a Generate tab or a "
                "gallery re-roll — collect here, newest first.")

    def showing_latest(self) -> bool:
        return base_of(self._tree.selected_folder_key()) == LATEST_KEY

    def refresh_inflight(self, rows=None, requests=None):
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
            self._inflight_by_key[item.key] = item
            tile = self._inflight_tiles.get(item.key)
            if tile is not None:
                tile.update_item(item)

    def inflight_items(self, rows=None, requests=None) -> list:
        return self._queue_model.build(rows=rows, requests=requests)

    def _on_inflight_clicked(self, key: str):
        item = self._inflight_by_key.get(key)
        if item is not None:
            item.reveal()

    def _inflight_context_menu(self, key: str, global_pos):
        item = self._inflight_by_key.get(key)
        if item is None or item.cancel is None:
            return
        menu = QMenu(self._scroll)
        discard = menu.addAction(CANCEL_TEXT)
        discard.setToolTip(cancel_tooltip(item.populating))
        stop = None
        if item.populating and item.stop_populate is not None:
            stop = menu.addAction(stop_populate_text())
            stop.setToolTip(stop_populate_tooltip())
        chosen = menu.exec(global_pos)
        if chosen is discard:
            item.cancel()
        elif stop is not None and chosen is stop:
            item.stop_populate()
            item.cancel()

    def _collection_double_clicked(self, prompt_id: str):
        self.item_jump_requested.emit(prompt_id)
        self.tab_pin_requested.emit()

    def _render_experiments(self):
        container, flow = self._fresh_tile_pane()
        actions = [
            CornerButton("keep", icons.experiment_verdict_icon("up"),
                         "Keep — add it to the gallery"),
            CornerButton("reject", icons.experiment_verdict_icon("down"),
                         "Reject — trash it and steer future experiments away"),
        ]
        rows = self._open_collection_rows(EXPERIMENTS_KEY)
        if not rows:
            self.show_widget(self._empty_state(self._experiments_empty_hint()))
            return

        def draw(row):
            self._add_collection_thumbnail(flow, row, corner_buttons=list(actions))

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

    def _render_trash(self):
        container, flow = self._fresh_tile_pane()
        rows = self._open_collection_rows(TRASH_KEY)
        if not rows:
            self.show_widget(self._empty_state(self._trash_empty_hint()))
            return
        self._show_paged(container, [
            _Entry(partial(self._add_trash_thumbnail, flow, row),
                   item=row["prompt_id"])
            for row in rows])

    def _add_trash_thumbnail(self, flow, row):
        def wire(tile):
            self._wire_picking(tile)
            tile.double_clicked.connect(self._thumbnail_double_clicked)
            tile.context_requested.connect(self._trash_context_menu)
            tile.control_triggered.connect(self.trash_action_triggered)

        name = self._host.item_name(row["prompt_id"])
        return self._draw_tile(
            flow, row, _TRASH_TILE, wire,
            TileAppearance(
                caption=f"{OLD_VERSION} · {name}" if row.get("old_version_of") else name,
                media_type=gallery.media_type_of_row(row),
                movie_path=self._host.animated_preview(row),
                favorite=bool(row.get("starred")),
                restore=restore_offer_of(row)),
        )

    def _trash_context_menu(self, prompt_id: str, global_pos):
        if not self._selection.holds(prompt_id):
            self.apply_selection(prompt_id, Qt.KeyboardModifier.NoModifier)
        self.trash_menu_requested.emit(global_pos)

    def _trash_empty_hint(self) -> str:
        return ("Nothing deleted.\n\nItems you delete wait here. After a day, only "
                "their thumbnails are kept, and restoring one makes it again. Restore "
                "one, or delete it permanently when you're sure.")

    def showing_trash(self) -> bool:
        return base_of(self._tree.selected_folder_key()) == TRASH_KEY

    def _favorite_items(self, shape: str | None, folder: str) -> list[dict]:
        return self._model.placement(shape).held_by(folder, gallery.favorite_generations(
            self._model.on_shape(shape)))

    def _favorite_folders(self, shape: str | None, folder: str) -> list:
        group = self._model.placement(shape).folder(folder)
        return gallery.favorite_folders(gallery.child_groups(group)) if group else []

    @staticmethod
    def _empty_state(text: str) -> QWidget:
        label = QLabel(text)
        label.setObjectName("mutedLabel")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        label.setContentsMargins(MARGIN_DIALOG, MARGIN_DIALOG, MARGIN_DIALOG, MARGIN_DIALOG)
        return label

    def collection_rows(self) -> list[dict] | None:
        if self.showing_search():
            return list(self._search_rows)
        return self.selected_collection_rows()

    def collection_counts(self, shape: str) -> dict[str, int]:
        placement = self._model.placement(shape)
        tallies = {collection: placement.tally(
                       self._model.in_collection(collection, shape, gallery.ALL_KEY))
                   for collection in (ENHANCED_KEY, EXPERIMENTS_KEY, TRASH_KEY)}
        tallies[FAVORITES_KEY] = placement.tally_favorites(self._model.on_shape(shape))
        return {FolderCollection(collection, folder).key: count
                for collection, tally in tallies.items() for folder, count in tally.items()}

    def selected_collection_rows(self) -> list[dict] | None:
        return self.rows_for_collection(self._tree.selected_folder_key())

    def rows_for_collection(self, key: str | None) -> list[dict] | None:
        base, shape = split_key(key)
        collection = folder_collection(base)
        if collection is None:
            return None
        return self._model.in_collection(collection.which, shape, collection.folder)

    def show_thumbnails(self, group):
        container, flow = self._fresh_tile_pane()
        i2v = bool(group.rows) \
            and gallery.is_image_conditioned(group.rows[0].get("workflow_name")) \
            and gallery.media_type_of_row(group.rows[0]) == MediaType.VIDEO
        def wire(tw):
            self._wire_picking(tw)
            tw.double_clicked.connect(self._thumbnail_double_clicked)
            tw.context_requested.connect(self._thumbnail_context_menu)
            tw.control_triggered.connect(self._on_tile_control)
            if i2v:
                tw.corner_button_triggered.connect(self.seed_reroll_requested)

        def draw(row):
            self._draw_tile(
                flow, row, _SEEDS_TILE if i2v else _FOLDER_TILE, wire,
                TileAppearance(
                    movie_path=self._host.animated_preview(row),
                    favorite=bool(row.get("starred")),
                    enhance=self._enhance_state(row),
                    enhancing=self._host.enhancing().run_of(row),
                    corner_buttons=self._seed_reroll_actions(row) if i2v else None),
            )

        finished = [row for row in group.rows if gallery.produced_output(row)]
        headings = gallery.section_headings(finished)
        lead = self._host.lead_tiles(group)
        tiles = self._folder_inflight_items(group)
        opens_now = ((lead.reroll is not None or bool(tiles))
                     and gallery.new_work_opens_a_section(finished))
        sections = opens_now + sum(1 for heading in headings if heading)
        modify_batch_above = lead.modify_batch is not None and sections > 1
        if modify_batch_above:
            flow.addWidget(lead.modify_batch)

        def draw_leading():
            for tile in (lead.reroll, None if modify_batch_above else lead.modify_batch):
                if tile is not None:
                    flow.addWidget(tile)
            for item in tiles:
                self._add_inflight_tile(flow, item)
            if lead.generating is not None:
                flow.addWidget(lead.generating)

        _open_sections(flow, headings, opens_now=opens_now, draw_leading=draw_leading)
        self._show_paged(container, _between_headings(flow, finished, headings, draw))

    def _folder_inflight_items(self, group) -> list[InFlightItem]:
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
        actions = [CornerButton(REROLL_VIDEO, icons.reroll_seed_icon(MediaType.VIDEO),
                                "Randomize video seed")]
        if gallery.rebuildable_source_image_id_in(row, self._model.image_index) is not None:
            actions.append(CornerButton(REROLL_IMAGE, icons.reroll_seed_icon(MediaType.IMAGE),
                                        "Randomize image seed"))
        return actions

    @staticmethod
    def _preview_paths(group) -> list[str]:
        return _thumbnails_of(gallery.rows_under(group))

    def _drill_into(self, key: str):
        self.folder_open_requested.emit(key)

    def listed_prompt_ids(self) -> list[str]:
        return self._selection.shown

    def _thumbnail_double_clicked(self, prompt_id: str):
        self.thumbnail_activated.emit(prompt_id)
        self.tab_pin_requested.emit()
        self.slideshow_requested.emit(prompt_id)

    def _wire_picking(self, tile):
        tile.pressed.connect(self._press_tile)
        tile.clicked.connect(self.thumbnail_activated)
        tile.double_clicked.connect(self._pick_only)

    def _pick_only(self, prompt_id: str):
        self.apply_selection(prompt_id, Qt.KeyboardModifier.NoModifier)

    def _press_tile(self, prompt_id: str, modifiers):
        if modifiers == Qt.KeyboardModifier.NoModifier and self._selection.picked == {prompt_id}:
            self._selection.clear()
            self._refresh_selection_highlights()
            return
        self.apply_selection(prompt_id, modifiers)

    def apply_selection(self, prompt_id: str, modifiers):
        self._selection.apply(
            prompt_id,
            ctrl=bool(modifiers & Qt.KeyboardModifier.ControlModifier),
            shift=bool(modifiers & Qt.KeyboardModifier.ShiftModifier),
        )
        self._refresh_selection_highlights()

    def reveal_tile(self, prompt_id: str) -> bool:
        self._pages.draw_past(lambda entry: entry.item == prompt_id, _NEIGHBORS_PAST_A_REVEAL)
        widget = self._thumb_widgets.get(prompt_id)
        if widget is None:
            return False
        self.apply_selection(prompt_id, Qt.KeyboardModifier.NoModifier)
        self._scroll_to(widget)
        # Qt has not laid out a pane drawn this turn, so its tiles have no positions yet.
        defer(self._scroll, lambda: self._reapply_reveal(prompt_id, widget))
        return True

    def _reapply_reveal(self, prompt_id: str, widget):
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
        # Qt has not laid out a pane drawn this turn, so its tiles have no positions yet.
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
        self._selection.clear()
        self._refresh_selection_highlights()

    @property
    def selected_ids(self) -> set:
        return self._selection.picked

    def selected_prompt_ids(self) -> list[str]:
        return self._selection.in_shown_order()

    def _thumbnail_context_menu(self, prompt_id: str, global_pos):
        if not self._selection.holds(prompt_id):
            self.apply_selection(prompt_id, Qt.KeyboardModifier.NoModifier)
            self.thumbnail_activated.emit(prompt_id)
        self.menu_requested.emit(self.selected_prompt_ids(), global_pos)

    def _on_tile_control(self, prompt_id: str, action: str):
        self.item_action_triggered.emit(prompt_id, action)

    def _enhance_state(self, row) -> str | None:
        return enhance_state(row, self._host.enhancing().settings)

    def refresh_corners(self):
        for prompt_id, tile in self._thumb_widgets.items():
            row = self._db.get_generation(prompt_id)
            if row is not None:
                tile.set_enhance(self._enhance_state(row))
                tile.set_favorite(bool(row.get("starred")))
