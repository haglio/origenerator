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
from PyQt6.QtCore import Qt

from origenerator import gallery
from origenerator.gui import icons
from origenerator.gui.flow_layout import FlowLayout
from origenerator.gui.folder_tile import FolderTile
from origenerator.gui.thumbnail_widget import ThumbnailWidget
from origenerator.gui.inflight_card import InFlightCard, InFlightItem
from origenerator.gui.gallery_tree import RECENTS_KEY, RECENTS_LABEL, STARRED_KEY, STARRED_LABEL

logger = logging.getLogger(__name__)

_TILE_SPACING = 8   # gap between tiles in the flowing main view
_PREVIEW_COUNT = 4  # thumbnails a folder tile shows as a preview
_STARRED_TITLE = "★ " + STARRED_LABEL  # the browser-pane heading for the shelf


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
        self._recent_rows: list[dict] = []  # recently generated rows, newest first
        self._starred_groups: list = []     # folders the Starred shelf collects

    def set_model(self, recent_rows, starred_groups):
        """Take the newly rebuilt gallery model the shelves render from."""
        self._recent_rows = recent_rows
        self._starred_groups = starred_groups

    # --- folder-tile overview ----------------------------------------------

    def show_widget(self, widget: QWidget):
        self._v._scroll.setWidget(widget)  # replaces & deletes the previous widget

    def show_empty(self):
        """Clear the pane to nothing on screen — no folder selected."""
        self._visible_ids = []
        self._visible_keys = []
        self.show_widget(QWidget())

    def _new_tile_pane(self):
        """A fresh container whose tiles flow to fill the pane's width."""
        container = QWidget()
        flow = FlowLayout(container, spacing=_TILE_SPACING)
        self.clear_selection()
        self._v._reroll_tile = None  # re-created below only when this folder re-rolls
        self._visible_ids = []
        self._visible_keys = []
        return container, flow

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

    # --- the Recents shelf: in-flight work, then recently finished items ----

    def show_recents_overview(self):
        """Render the Recents shelf: a card for every in-flight generation (queued
        or running, from a Generate tab or a gallery re-roll) atop the recently
        finished items. Clicking an in-flight card reveals where its job runs; a
        finished one previews in the info pane, right here on the shelf, the way a
        thumbnail does inside a folder — and a "Go to containing folder" button
        then offers the jump to its folder. Opens with the info pane cleared, so
        it shows nothing until an item is picked."""
        self._v._title.set_display(RECENTS_LABEL)
        self._v._avg_label.setText("")
        self._v._clear_metadata()
        self._render_recents()
        self._v._sync_delete_button()
        self._v._record_location(RECENTS_KEY)  # so Back can return to the shelf

    def _render_recents(self):
        """Draw the shelf: in-flight cards first (the newest, still-cooking work),
        then the finished thumbnails; a hint when there is neither."""
        container, flow = self._new_tile_pane()
        items = self._inflight_items()
        self._inflight_signature = _inflight_signature(items)
        self._inflight_cards = {}
        self._inflight_by_key = {}
        for item in items:
            card = InFlightCard(item)
            card.clicked.connect(self._on_inflight_clicked)
            flow.addWidget(card)
            self._inflight_cards[item.key] = card
            self._inflight_by_key[item.key] = item
        for row in self._recent_rows:
            tw = ThumbnailWidget(
                row["prompt_id"], row.get("thumbnail_path"), self._thumbnail_caption(row),
                media_type=gallery.media_type_of_row(row),  # a corner badge: image or video
                movie_path=self._v._animated_preview(row),  # videos loop; images stay still
                starred=bool(row.get("starred")),
            )
            tw.clicked.connect(self._thumbnail_clicked)  # preview it here, on the shelf
            tw.double_clicked.connect(self.open_in_containing_folder)  # or open its folder
            self._wire_drag(tw)
            flow.addWidget(tw)
            self._visible_ids.append(row["prompt_id"])
            self._thumb_widgets[row["prompt_id"]] = tw
        # An empty shelf teaches how to fill it rather than showing a blank pane.
        self.show_widget(container if (items or self._recent_rows) else self._empty_state(
            "No recent generations yet.\n\nItems you make — from a Generate tab or a "
            "gallery re-roll — collect here, newest first."
        ))

    def showing_recents(self) -> bool:
        return (self._v._recents_item is not None
                and self._v._tree.currentItem() is self._v._recents_item)

    def refresh_inflight(self):
        """Between rebuilds, keep the in-flight cards live: push each tracked
        re-roll's latest frame into its card, and re-render only when the *set* of
        in-flight jobs changes (a defensive guard — a started or finished re-roll
        normally moves the DB fingerprint and forces a full rebuild anyway)."""
        items = self._inflight_items()
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
        session grafts on its live frame, progress and cancel from its
        :class:`GenerationJob`; an untracked running row shows a plain card.
        """
        reroll_by_pid = {job.prompt_id: (key, job)
                         for key, job in self._v._reroll.jobs.items()}
        image_index = None  # built lazily, only to place an untracked row's folder
        items = []
        for row in self._v._db.list_generations():
            if row.get("status") not in ("running", "pending"):
                continue
            pid = row["prompt_id"]
            tracked = reroll_by_pid.get(pid)
            if tracked is not None:
                folder_key, job = tracked
                frame, progress = job.last_preview, job.last_progress
                cancel = lambda k=folder_key: self._v._cancel_reroll(k)
            else:  # a running row no live job holds — no live frame, progress, or cancel
                if image_index is None:
                    image_index = gallery.build_image_config_index(self._v._image_rows)
                folder_key = gallery.settings_folder_key(row, image_index)
                frame, progress, cancel = None, None, None
            items.append(InFlightItem(
                key=pid,
                caption=gallery.config_tab_title(
                    row.get("workflow_name") or "", gallery.parse_params(row.get("params_json"))
                ),
                status="running" if row.get("status") == "running" else "queued",
                frame=frame,
                reveal=lambda k=folder_key: self._reveal_reroll(k),
                media_type=gallery.media_type_of_row(row),  # image/video corner badge
                progress=progress,
                cancel=cancel,
            ))
        items.sort(key=lambda it: it.status != "running")  # stable: running first
        return items

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

    def go_to_containing_folder(self):
        """The 'Go to containing folder' button's action: open the previewed Recents
        item in its own folder, selected."""
        if self._v._selected is not None:
            self.open_in_containing_folder(self._v._selected["prompt_id"])

    def open_in_containing_folder(self, prompt_id: str):
        """Jump the browser pane to ``prompt_id``'s own folder and land on the item
        itself — its tile picked and highlighted, as if you'd navigated in and
        clicked it, not just auto-previewing the folder's first item. Shared by the
        button and a double-click on a Recents tile."""
        self._v._on_source_link(prompt_id)  # open the folder, previewing the item
        # The navigation renders the folder's tiles; now pick this one so it reads
        # as the selected item rather than an unhighlighted preview.
        self.apply_selection(prompt_id, Qt.KeyboardModifier.NoModifier)

    def sync_containing_folder_button(self):
        """Offer "Go to containing folder" only while the Recents shelf is showing
        a previewed item: that's the one view whose info pane holds a generation
        from a folder other than the one on screen."""
        self._v._containing_folder_btn.setVisible(
            self.showing_recents() and self._v._selected is not None
        )

    # --- the Starred shelf: every bookmarked folder, gathered in one place ---

    def show_starred_overview(self):
        """Render the Starred shelf: one tile per bookmarked folder, each captioned
        with its breadcrumb so identically-named folders stay tellable apart. Like
        a branch folder it lists sub-folders rather than a single generation, so the
        info pane clears instead of previewing one folder's first item."""
        self._v._title.set_display(_STARRED_TITLE)
        self._v._avg_label.setText("")
        self._v._clear_metadata()
        self._show_starred_tiles(self._starred_groups)
        self._v._sync_delete_button()
        self._v._record_location(STARRED_KEY)  # so Back can return to the shelf

    def _show_starred_tiles(self, groups):
        container, flow = self._new_tile_pane()
        for group in groups:
            item = self._v._item_by_key.get(group.key)
            context = self._v._tree_view.breadcrumb(item.parent()) if item and item.parent() else ""
            self._add_folder_tile(flow, group, starred=False, context=context)
        # An empty shelf teaches how to fill it rather than showing a blank pane.
        self.show_widget(container if groups else self._empty_state(
            "No starred folders yet.\n\nHover a folder in the list and click its "
            "star, or right-click a folder and choose Star, to collect it here."
        ))

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

    # --- the thumbnail grid: a settings leaf's generations ------------------

    def show_thumbnails(self, group):
        container, flow = self._new_tile_pane()
        # An image-conditioned folder's items carry per-seed re-roll hover controls;
        # its rows all share the one workflow, so the kind is decided once.
        i2v = bool(group.rows) and gallery.is_image_conditioned(group.rows[0].get("workflow_name"))
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
        tw.drag_started.connect(self._v._on_thumbnail_drag_started)
        tw.drag_ended.connect(self._v._on_thumbnail_drag_ended)

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
        menu = QMenu(self._v)
        star_action = menu.addAction(("Unstar" if all_starred else "Star") + suffix)
        delete_action = menu.addAction("Delete" + suffix)
        chosen = menu.exec(global_pos)
        if chosen is delete_action:
            self._v._delete_selection()
        elif chosen is star_action:
            self._v.set_items_starred(ids, not all_starred)

    def _is_starred(self, prompt_id: str) -> bool:
        row = self._v._db.get_generation(prompt_id)
        return bool(row and row.get("starred"))
