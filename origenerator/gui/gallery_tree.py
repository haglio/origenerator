"""Builds and queries the gallery's folder trees — the left TOC pane.

The pane is two trees, one per shape, each under a standing label and each
scrolling on its own (:class:`~origenerator.gui.split_folder_tree.SplitFolderTree`).
Each carries the whole table of contents, built from that shape's rows alone.
Standing anywhere means standing on one shape, so a slideshow started there has
one region to go to (see :mod:`origenerator.orientation`).

A row's key in the tree is therefore its folder's own key with the side
appended, and the two maps kept here — key→item and prompt-id→item — are keyed
that way. The folder's own key is what a star, a name and a place in a custom
folder hang off, and it is untouched: ``keys_by_folder`` maps one back to
the rows drawing it, which is how a navigation that knows only a folder key
(a re-roll, a combine, a folder tile) finds a row to select.

Pure rendering and lookups over the pane the GalleryView owns and lays out; it
has no database or refresh concerns — folder rename/star/delete live in the
view, which rebuilds both halves through :meth:`populate`.

The folders the user composed by hand are drawn flat: a custom folder's items
can sit anywhere in the hierarchy, so nesting them under it would draw the same
folder twice and put two rows in ``item_by_key`` for one key. Its contents show
as tiles in the browser pane instead, exactly as a Favorites shelf shows its
bookmarked folders.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTreeWidgetItem

from origenerator import gallery
from origenerator.gallery.shelves import (
    EXPERIMENTS_KEY,
    FAVORITES_KEY,
    RECENTS_KEY,
    REQUESTS_KEY,
    SHELF_LABELS,
    SHELVES,
    TRASH_KEY,
    FolderShelf,
    folder_shelf,
)
from origenerator.gui import icons
from origenerator.gui.folder_tree import (
    BRANCH_ICON_ROLE,
    COUNT_ROLE,
    DROP_KEY_ROLE,
    RECENT_ROLE,
    TREE_KEY_ROLE,
)
from origenerator.orientation import ORIENTATION_LABELS, orientation_of, oriented_key, split_key

# A search does not narrow this tree: a narrowed list of folder names is a poor
# answer to "where is the one with the two of them on the couch", because a
# folder's name is a short code and the thing you would actually recognize is
# the picture. The search fills the browser pane with matching thumbnails
# instead (see BrowserPane.show_search_results), and the tree is left alone — so the folder
# you were standing in is still there when the search clears.

GROUP_ROLE = Qt.ItemDataRole.UserRole  # the gallery group a tree node represents

_SHELF_TIPS = {
    RECENTS_KEY: "Recently generated",
    FAVORITES_KEY: "Your favorite folders and items — drop a folder here to add it",
    EXPERIMENTS_KEY: "Background experiments awaiting your review",
    REQUESTS_KEY: "What you asked for out loud — “Request … over”",
    TRASH_KEY: "Deleted items — restorable here until you delete them for good",
}


def _shown_shelves(side) -> list[str]:
    return [shelf for shelf in SHELVES
            if (shelf != RECENTS_KEY or side.show_recents)
            and (shelf != FAVORITES_KEY or side.tree_model)]


@dataclass
class SideModel:
    """One side of the tree: everything the Portrait (or Landscape) root draws."""

    orientation: str
    tree_model: list                       # this shape's media roots
    custom_folders: list = field(default_factory=list)
    show_recents: bool = False             # anything at all to list yet
    shelf_counts: dict[str, int] = field(default_factory=dict)


def _row_tip(group) -> str:
    """A folder row's hover text: its name, and what its name doesn't say."""
    detail = gallery.folder_detail(group)
    return f"{group.label} · {detail}" if detail else group.label


class GalleryTree:
    """The folder tree: builds it from the gallery model and answers the lookups
    (key→item, prompt→item, breadcrumb, the selected folder's key) the view
    navigates by. The pane holding the two trees is owned by the view."""

    def __init__(self, tree):
        self._tree = tree
        self.item_by_key: dict[str, QTreeWidgetItem] = {}  # tree key -> its row
        self.leaf_by_id: dict[str, QTreeWidgetItem] = {}   # prompt_id -> its settings row
        # plain key -> the tree keys drawing it, in side order. Each side draws
        # its own copy of every shelf, and of every folder holding rows of its
        # shape — so a caller holding a key with no side (a re-roll's folder, a
        # saved session's, a spoken shelf name) can still find a row.
        self.keys_by_folder: dict[str, list[str]] = {}
        self._recently_worked: set[str] = set()  # tree keys wearing the mark
        self._built = False  # whether a first populate has happened (see _open_all)

    def populate(self, sides, expanded_keys, *, folder_meta=None,
                 recently_worked=()):
        """Rebuild the tree from ``sides``, restoring the folders in ``expanded_keys``.

        ``sides`` are the :class:`SideModel`s to fill the halves with, one per
        shape. ``folder_meta`` is the same label/star overlay the tree models
        were built with, so the All row each side wraps around its model can be
        renamed and favorited like any folder under it.

        ``recently_worked`` are the ``(side, folder key)`` pairs of the folders
        worked in lately (:func:`~origenerator.gallery.recently_worked_folders`),
        whose rows wear a mark. A folder stays where the row that made it put
        it, so the mark is the whole of what says where the work has been.
        """
        self._recently_worked = {oriented_key(key, side)
                                 for side, key in recently_worked}
        self._tree.blockSignals(True)
        self._tree.clear()
        self.item_by_key = {}
        self.leaf_by_id = {}
        self.keys_by_folder = {}
        for side in sides:
            self._add_side(self._tree.root_for(side.orientation), side, folder_meta)
        # Folders default to collapsed; only restore folders the user had open.
        for key in expanded_keys:
            item = self.item_by_key.get(key)
            if item is not None:
                item.setExpanded(True)
        self._open_all(expanded_keys)
        self._tree.blockSignals(False)
        self._built = True

    def _add_side(self, root, side, folder_meta) -> None:
        """One shape's whole table of contents, filling that shape's half.

        Both halves are always drawn, even for a side with nothing in it yet:
        the split is what tells a slideshow which screen it is for, so the side
        you have not generated for yet is still somewhere you can stand and
        somewhere its first generation can appear. Its label says so even while
        the rows under it are only empty shelves.
        """
        for custom in side.custom_folders:
            self._add_custom_folder(root, custom, side.orientation)
        self._add_node(gallery.all_group(side.tree_model, folder_meta), root, side)

    def _add_shelves(self, folder_item, side, folder_key: str) -> None:
        for shelf in _shown_shelves(side):
            key = FolderShelf(shelf, folder_key).key
            item = QTreeWidgetItem([SHELF_LABELS[shelf]])
            item.setData(0, COUNT_ROLE, side.shelf_counts.get(key, 0))
            item.setData(0, BRANCH_ICON_ROLE, icons.shelf_icon(shelf))
            item.setToolTip(0, _SHELF_TIPS[shelf])
            if shelf == FAVORITES_KEY:
                item.setData(0, DROP_KEY_ROLE, FAVORITES_KEY)
            self._register(item, oriented_key(key, side.orientation), folder_item,
                           folder_key=key)

    def _register(self, item, key: str, parent_item,
                  folder_key: str | None = None) -> QTreeWidgetItem:
        """Hang ``item`` under ``parent_item`` as ``key``, and index it.

        The key rides the row itself so the selected row can name its own place
        without anything having to work out which side it is on;
        ``keys_by_folder`` is the way back for a caller holding a key with no
        side on it (``folder_key`` — only a side's own root has none).

        A row of a folder lately worked in is marked here rather than at each
        tier, so every kind of row answers to the one rule; the tooltip says
        what the mark means, since a dot nothing explains is a riddle."""
        item.setData(0, TREE_KEY_ROLE, key)
        if key in self._recently_worked:
            item.setData(0, RECENT_ROLE, True)
            item.setToolTip(0, f"{item.toolTip(0)} · worked in recently")
        parent_item.addChild(item)
        self.item_by_key[key] = item
        if folder_key is not None:
            self.keys_by_folder.setdefault(folder_key, []).append(key)
        return item

    def _open_all(self, expanded_keys) -> None:
        """Open every side's All row on a gallery's first build.

        Every other folder defaults shut, but All shut is a side with nothing in
        it — the workflow folders are where the gallery starts. Only on the first
        build: after that its state is the user's, saved and restored with every
        other folder's, so collapsing it sticks.
        """
        if self._built or expanded_keys:
            return
        for key in self.keys_by_folder.get(gallery.ALL_KEY, ()):
            self.item_by_key[key].setExpanded(True)

    def _add_custom_folder(self, side_item, group, orientation) -> QTreeWidgetItem:
        """Add a row for one of the user's own folders: a shelf-shaped row carrying
        its group (so the view's folder machinery — breadcrumb, tiles, slideshow —
        treats it like any other folder), editable for an inline rename, and
        collecting the folders dropped onto it."""
        count = len(gallery.rows_under(group))
        item = QTreeWidgetItem([group.label])
        item.setData(0, BRANCH_ICON_ROLE, icons.custom_folder_icon())
        item.setToolTip(0, f"{group.label} — {count} item{'s' if count != 1 else ''} "
                           "in a folder you made; drop folders here to add them")
        item.setData(0, GROUP_ROLE, group)
        item.setData(0, COUNT_ROLE, count)
        item.setData(0, DROP_KEY_ROLE, group.key)  # the folder gathers, not the side
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)  # for inline rename
        return self._register(item, oriented_key(group.key, orientation), side_item,
                              folder_key=group.key)

    def _add_node(self, group, parent_item, side) -> QTreeWidgetItem:
        item = QTreeWidgetItem([group.label])
        if gallery.is_renamable(group):
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)  # for inline rename
        item.setData(0, GROUP_ROLE, group)
        item.setData(0, COUNT_ROLE, len(gallery.rows_under(group)))
        # A workflow / model / LoRA / source-image row wears a lettered chip
        # naming its level, so a row's place in the hierarchy reads at a glance
        # rather than by counting indentation; the level joins the tooltip too.
        # The All row and the settings leaves get neither (folder_level returns
        # None).
        #
        # It is the row's *icon*, so it sits right of the caret and reads as the
        # first character of the folder's name — which is what it is. What that
        # costs is the label: Qt lays the text out after the icon, so a chipped
        # row's text starts a chip-width right of an unchipped sibling's. The
        # thing that stays uniform is where each row's name *block* begins, at
        # exactly its depth times the indentation.
        level = gallery.folder_level(group)
        if level is not None:
            item.setIcon(0, icons.level_badge_icon(level))
            item.setToolTip(0, f"{group.label} · {icons.LEVEL_LABELS[level]}")
        else:
            # A settings leaf is named by a code, so its tooltip is where the
            # prompt and the settings that set it apart from its siblings are
            # read — the row itself stays one short line.
            item.setToolTip(0, _row_tip(group))
        self._register(item, oriented_key(group.key, side.orientation), parent_item,
                       folder_key=group.key)
        if not isinstance(group, gallery.SettingsGroup):
            self._add_shelves(item, side, group.key)
        for child in gallery.child_groups(group):
            self._add_node(child, item, side)
        if isinstance(group, gallery.SettingsGroup):
            for row in group.rows:
                self.leaf_by_id[row["prompt_id"]] = item
        return item

    def shelves_in(self, item) -> list[str]:
        children = (item.child(i) for i in range(item.childCount()))
        return [child.data(0, TREE_KEY_ROLE) for child in children
                if child.data(0, GROUP_ROLE) is None]

    def keys_for_folder(self, folder_key: str) -> list[str]:
        """The tree keys drawing ``folder_key`` — a folder's own key or a shelf's
        — in side order, empty for one no side is holding right now."""
        return list(self.keys_by_folder.get(folder_key, ()))

    def mark_favorite(self, folder_key: str, favorite: bool) -> None:
        for key in self.keys_by_folder.get(folder_key, ()):
            item = self.item_by_key[key]
            item.data(0, GROUP_ROLE).favorite = favorite
            item.emitDataChanged()

    def shelf_item(self, shelf_key: str, orientation: str) -> QTreeWidgetItem | None:
        """One side's copy of a shelf row."""
        return self.item_by_key.get(oriented_key(shelf_key, orientation))

    def set_shelf_counts(self, orientation: str, counts: dict[str, int]) -> None:
        blocked = self._tree.blockSignals(True)
        for key, item in self.item_by_key.items():
            base, side = split_key(key)
            if side == orientation and folder_shelf(base) is not None:
                item.setData(0, COUNT_ROLE, counts.get(base, 0))
        self._tree.blockSignals(blocked)

    def default_item(self) -> QTreeWidgetItem | None:
        alls = [self.item_by_key[key] for key in self.keys_by_folder.get(gallery.ALL_KEY, ())]
        holding = [item for item in alls if gallery.child_groups(item.data(0, GROUP_ROLE))]
        return next(iter(holding or alls), None)

    def expanded_keys(self) -> set[str]:
        return {key for key, item in self.item_by_key.items() if item.isExpanded()}

    def selected_folder_key(self) -> str | None:
        """The tree key of the selected row — its folder's key with the side it is
        being looked at from appended, or a shelf's own oriented key."""
        item = self._tree.currentItem()
        return item.data(0, TREE_KEY_ROLE) if item is not None else None

    def breadcrumb(self, item) -> str:
        """The path down to ``item``, led by its side.

        The side comes from the row's own key rather than from a row above it —
        each half is a tree of its own — and it leads the path because a
        folder's label alone would not say which of the two copies of it you
        are standing in. The header over the browser pane is a long way from
        the label over the half you clicked.
        """
        parts = []
        node = item
        while node is not None:
            group = node.data(0, GROUP_ROLE)
            # Only a shelf row has no group, and it is named by its own text.
            parts.append(group.label if group is not None else node.text(0))
            node = node.parent()
        side = orientation_of(item.data(0, TREE_KEY_ROLE)) if item is not None else None
        if side is not None:
            parts.append(ORIENTATION_LABELS[side])
        return "  ›  ".join(reversed(parts))
