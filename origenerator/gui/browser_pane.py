"""The gallery's browser pane — the middle column showing a folder's contents.

Renders whatever the selected tree row calls for: a branch folder's child tiles, a
settings leaf's thumbnail grid (with its re-roll tile), or the Recents / Starred
shelf overviews. Owns the thumbnail multi-selection and the live in-flight cards.

It drives the surrounding pieces it doesn't own — the info pane on a click, the
tree on a drill, the re-roll tile, the delete action — so it holds a reference to
the GalleryView and calls back into it rather than standing alone. The view keeps
thin delegates so the pane's rendering and selection are one concern in one place.
"""

import logging
from pathlib import Path

from PyQt6.QtWidgets import QWidget, QLabel, QMenu, QApplication
from PyQt6.QtCore import Qt, QTimer

from origenerator import gallery, timing
from origenerator.branch_session import is_branch_session
from origenerator.gui import icons
from origenerator.gui.flow_layout import FlowLayout
from origenerator.gui.folder_tile import FolderTile
from origenerator.gui.thumbnail_widget import ThumbnailWidget
from origenerator.gui.inflight_card import InFlightCard, InFlightItem
from origenerator.gui.gallery_tree import (
    EXPERIMENTS_KEY, EXPERIMENTS_LABEL,
    RECENTS_KEY, RECENTS_LABEL, STARRED_KEY, STARRED_LABEL,
)

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


def _inflight_signature(items) -> tuple:
    """The identity of the in-flight set — its job keys — so a frame-only change
    refreshes cards in place while an added or removed job forces a re-render."""
    return tuple(sorted(it.key for it in items))


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

    def set_model(self, recent_rows, starred_groups, starred_rows, experiment_rows):
        """Take the newly rebuilt gallery model the shelves render from."""
        self._recent_rows = recent_rows
        self._starred_groups = starred_groups
        self._starred_rows = starred_rows
        self._experiment_rows = experiment_rows

    def set_recent_rows(self, recent_rows):
        """Replace just the finished-items list the Recents shelf lists and, if that
        shelf is open, redraw it — the media-type filter changing between rebuilds.

        A new filter is a new listing, so the shelf reopens on its first page at the
        top rather than holding the pages and offset the old listing was read at."""
        self._recent_rows = recent_rows
        if self.showing_recents():
            self._recents_flow = None  # a fresh listing, not a redraw to be preserved
            self._recents_drawn = 0
            self._render_recents()

    # --- folder-tile overview ----------------------------------------------

    def show_widget(self, widget: QWidget):
        self._v._scroll.setWidget(widget)  # replaces & deletes the previous widget

    def show_empty(self):
        """Clear the pane to nothing on screen — no folder selected."""
        self._visible_ids = []
        self._visible_keys = []
        self._forget_recents_paging()
        self.show_widget(QWidget())

    def _new_tile_pane(self):
        """A fresh container whose tiles flow to fill the pane's width."""
        container = QWidget()
        flow = FlowLayout(container, spacing=_TILE_SPACING)
        self.clear_selection()
        self._v._reroll_tile = None  # re-created below only when this folder re-rolls
        self._visible_ids = []
        self._visible_keys = []
        self._forget_recents_paging()
        return container, flow

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
            level=gallery.folder_level(group),
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
        self._v._sync_delete_button()
        self._v._record_location(RECENTS_KEY)  # so Back can return to the shelf

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
            enhanced=gallery.is_enhanced_row(row),      # the green-plus corner badge
            enhancing=self._v.is_enhancing(row),        # a scrim while one cooks
            corner_actions=corner_actions,
        )
        tw.clicked.connect(self._thumbnail_clicked)  # preview it here, on the shelf
        tw.double_clicked.connect(self.open_in_containing_folder)  # or open its folder
        # Every shelf gets the folder menu — an item is no less actionable for being
        # listed by when it was made or by its bookmark rather than by its settings.
        tw.context_requested.connect(self._thumbnail_context_menu)
        self._wire_drag(tw)
        flow.addWidget(tw)
        self._visible_ids.append(row["prompt_id"])
        self._thumb_widgets[row["prompt_id"]] = tw
        return tw

    def _visible_inflight_items(self) -> list:
        """The in-flight items the shelf's media-type filter keeps on screen. The
        full set still decides whether the shelf exists at all (so its filter stays
        reachable); this narrows only what the shelf draws."""
        media_types = self._v._recents_media_types()
        return [it for it in self._inflight_items() if it.media_type in media_types]

    def _recents_empty_hint(self) -> str:
        """The teaching hint for an empty shelf, worded for the current filter —
        which media types (if any) it's looking for."""
        media_types = self._v._recents_media_types()
        if not media_types:
            return ("No media types selected.\n\nCheck Images or Videos above to "
                    "list your recent generations.")
        noun = "generations" if len(media_types) == 2 else (
            "images" if "image" in media_types else "videos")
        return (f"No recent {noun} yet.\n\nItems you make — from a Generate tab or a "
                "gallery re-roll — collect here, newest first.")

    def showing_recents(self) -> bool:
        return (self._v._recents_item is not None
                and self._v._tree.currentItem() is self._v._recents_item)

    def refresh_inflight(self):
        """Between rebuilds, keep the in-flight cards live: push each tracked
        re-roll's latest frame into its card, and re-render only when the *set* of
        in-flight jobs changes (a defensive guard — a started or finished re-roll
        normally moves the DB fingerprint and forces a full rebuild anyway)."""
        items = self._visible_inflight_items()
        if _inflight_signature(items) != self._inflight_signature:
            self._render_recents()
            return
        for item in items:
            self._inflight_by_key[item.key] = item  # keep the reveal current
            card = self._inflight_cards.get(item.key)
            if card is not None:
                card.update_item(item)

    def _inflight_items(self) -> list:
        """Every queued/running generation as a card model, running ones first.

        The database's running/pending rows are the source of truth for what's in
        flight — every generation is a gallery re-roll (a tab's Generate launches
        one too) — so a card shows even when no live job object is tracking a row
        (after a restart that hasn't re-adopted it, say). A re-roll tracked this
        session grafts on its live frame, progress, cancel and start time from its
        :class:`GenerationJob`; an untracked running row shows a plain card.
        """
        reroll_by_pid = {job.prompt_id: (key, job)
                         for key, job in self._v._reroll.jobs.items()}
        image_index = None  # built lazily, only to place an untracked row's folder
        typical: dict[str, float | None] = {}  # workflow -> its usual run time
        items = []
        for row in self._v._db.list_generations():
            if row.get("status") not in ("running", "pending"):
                continue
            pid = row["prompt_id"]
            tracked = reroll_by_pid.get(pid)
            if tracked is not None:
                folder_key, job = tracked
                frame, progress = job.last_preview, job.last_progress
                foreign = job.foreign_ahead  # another app's jobs in front of it, if any
                started = job.started_at  # None until ComfyUI actually starts it
                cancel = lambda k=folder_key: self._v._cancel_reroll(k)
            else:  # a running row no live job holds — no live frame, progress, or cancel
                if image_index is None:
                    image_index = gallery.build_image_config_index(self._v._image_rows)
                folder_key = gallery.settings_folder_key(row, image_index)
                frame, progress, cancel, foreign, started = None, None, None, None, None
            workflow_name = row.get("workflow_name") or ""
            items.append(InFlightItem(
                key=pid,
                caption=gallery.config_tab_title(
                    workflow_name, gallery.parse_params(row.get("params_json"))
                ),
                status="running" if row.get("status") == "running" else "queued",
                frame=frame,
                reveal=lambda k=folder_key: self._reveal_reroll(k),
                media_type=gallery.media_type_of_row(row),  # image/video corner badge
                progress=progress,
                cancel=cancel,
                foreign_ahead=foreign,
                started_at=started,
                typical_seconds=self._typical_seconds(workflow_name, typical),
            ))
        items.sort(key=lambda it: it.status != "running")  # stable: running first
        return items

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
        self._v._sync_delete_button()
        self._v._record_location(EXPERIMENTS_KEY)  # so Back can return to the shelf

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
        self._v._sync_delete_button()
        self._v._record_location(STARRED_KEY)  # so Back can return to the shelf

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
        """A centered hint filling an otherwise-blank shelf pane (Recents/Starred)."""
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
        tile there stands for its whole folder, and Experiments is its unreviewed
        queue. A starred item inside a starred folder is one item, so repeats drop
        out.
        """
        if self.showing_recents():
            return list(self._recent_rows)
        if self.showing_starred():
            return _unique_rows(self._starred_rows + [
                row for group in self._starred_groups for row in gallery.rows_under(group)
            ])
        if self.showing_experiments():
            return list(self._experiment_rows)
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
        for row in group.rows:
            if not gallery.produced_output(row):
                continue  # still in flight — represented by the RerollTile, not a tile
            tw = ThumbnailWidget(
                row["prompt_id"], row.get("thumbnail_path"), self._thumbnail_caption(row),
                movie_path=self._v._animated_preview(row),  # videos loop; images stay still
                starred=bool(row.get("starred")),
                enhanced=gallery.is_enhanced_row(row),      # the green-plus corner badge
                enhancing=self._v.is_enhancing(row),        # a scrim while one cooks
                corner_actions=self._seed_reroll_actions(row) if i2v else None,
            )
            tw.clicked.connect(self._thumbnail_clicked)
            tw.double_clicked.connect(self._thumbnail_double_clicked)
            tw.context_requested.connect(self._thumbnail_context_menu)
            if i2v:
                tw.corner_action_triggered.connect(self._v._reroll_item_seed)
            self._wire_drag(tw)
            flow.addWidget(tw)
            self._visible_ids.append(row["prompt_id"])
            self._thumb_widgets[row["prompt_id"]] = tw
        self.show_widget(container)

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
        item = self._v._item_by_key.get(key)
        if item is not None:
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
        """Open a thumbnail as a Generate tab — the same "reuse parameters"
        gesture as picking it and clicking the button. Inert for a workflow the
        app can't rebuild, matching the button's greyed-out state."""
        self._v._on_thumbnail_clicked(prompt_id)  # make it the selected generation
        self._v._on_reuse()

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
        self._v._sync_delete_button()

    def clear_selection(self):
        self._selected_ids = set()
        self._selection_anchor = None
        self._thumb_widgets = {}
        self._v._sync_delete_button()

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
        """Right-click menu for a thumbnail: star/unstar or delete the picked item(s).

        Right-clicking a tile that isn't part of the current selection first
        selects just it, so the menu always acts on something visible. The star
        entry reads Unstar only when every picked item is already starred, and
        toggles the whole selection to the opposite state.
        """
        if prompt_id not in self._selected_ids:
            self.apply_selection(prompt_id, Qt.KeyboardModifier.NoModifier)
            self._v._on_thumbnail_clicked(prompt_id)
        ids = self.selected_prompt_ids()
        count = len(ids)
        suffix = f" {count} item{'s' if count != 1 else ''}"
        all_starred = all(self._is_starred(pid) for pid in ids)
        # Enhance is offered when any picked item is a finished image — the
        # handler skips the rest — and enhances deliberately, badge or not.
        enhanceable = [pid for pid in ids if self._is_enhanceable(pid)]
        menu = QMenu(self._v)
        star_action = menu.addAction(("Unstar" if all_starred else "Star") + suffix)
        enhance_action = None
        if enhanceable:
            n = len(enhanceable)
            enhance_action = menu.addAction(
                f"Enhance {n} image{'s' if n != 1 else ''}"
            )
        delete_action = menu.addAction("Delete" + suffix)
        chosen = menu.exec(global_pos)
        if chosen is delete_action:
            self._v._delete_selection()
        elif chosen is star_action:
            self._v.set_items_starred(ids, not all_starred)
        elif enhance_action is not None and chosen is enhance_action:
            self._v.enhance_items(enhanceable)

    def _is_enhanceable(self, prompt_id: str) -> bool:
        row = self._v._db.get_generation(prompt_id)
        return bool(row and gallery.is_enhanceable_row(row))

    def _is_starred(self, prompt_id: str) -> bool:
        row = self._v._db.get_generation(prompt_id)
        return bool(row and row.get("starred"))
