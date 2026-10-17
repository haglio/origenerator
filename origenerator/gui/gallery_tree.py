"""Builds and queries the gallery's folder list — the left pane.

The pane draws one tree per side, each under a standing label and each scrolling
on its own (:class:`~origenerator.gui.split_folder_tree.SplitFolderTree`), and
each carries the whole table of contents over the rows that side holds. Standing
anywhere is standing on one side, so a slideshow started there knows what to
play (see :mod:`origenerator.orientation`).

A row's key in the tree is therefore its folder's own key with the side
appended, and the two maps kept here — key→item and prompt-id→item — are keyed
that way. The folder's own key is what a star, a name and a place in a custom
folder hang off, and it is untouched: ``keys_by_folder`` maps one back to
the rows drawing it, which is how a navigation that knows only a folder key
(a re-roll, a combine, a folder tile) finds a row to select.

Pure rendering and lookups over the pane the GalleryView owns and lays out; it
has no database or refresh concerns — folder star/delete live in the view,
which rebuilds every side through :meth:`populate`.

The folders the user composed by hand are drawn flat: a custom folder's items
can sit anywhere in the hierarchy, so nesting them under it would draw the same
folder twice and put two rows in ``item_by_key`` for one key. Its contents show
as tiles in the browser pane instead, exactly as a Favorites collection shows its
bookmarked folders.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTreeWidgetItem

from origenerator import gallery
from origenerator.gallery.collection import (
    COLLECTION_LABELS,
    COLLECTIONS,
    EXPERIMENTS_KEY,
    FAVORITES_KEY,
    RECENTS_KEY,
    REQUESTS_KEY,
    TRASH_KEY,
    FolderCollection,
    folder_collection,
)
from origenerator.gallery.sides import SIDE_LABELS
from origenerator.gui import icons
from origenerator.gui.folder_tree import COUNT_ROLE, DROP_KEY_ROLE, RECENT_ROLE, TREE_KEY_ROLE
from origenerator.orientation import oriented_key, side_of, split_key

# A search does not narrow this tree: a narrowed list of folder names is a poor
# answer to "where is the one with the two of them on the couch", because a
# folder's name is a short code and the thing you would actually recognize is
# the picture. The search fills the browser pane with matching thumbnails
# instead (see BrowserPane.show_search_results), and the tree is left alone — so the folder
# you were standing in is still there when the search clears.

GROUP_ROLE = Qt.ItemDataRole.UserRole  # the gallery group a tree node represents

_COLLECTION_TIPS = {
    RECENTS_KEY: "Recently generated",
    FAVORITES_KEY: "Your favorite folders and items — drop a folder here to add it",
    EXPERIMENTS_KEY: "Background experiments awaiting your review",
    REQUESTS_KEY: "What you asked for out loud — “Request … over”",
    TRASH_KEY: "Deleted items — restorable here until you delete them for good",
}


PATH_SEPARATOR = "  ›  "


def _name_of(row) -> str:
    group = row.data(0, GROUP_ROLE)
    return group.label if group is not None else row.text(0)


def _children(row) -> Iterator[QTreeWidgetItem]:
    return (row.child(i) for i in range(row.childCount()))


def _same_name(typed: str, name: str) -> bool:
    return " ".join(typed.split()).casefold() == " ".join(name.split()).casefold()


def _shown_collections(side) -> list[str]:
    return [collection for collection in COLLECTIONS
            if (collection != RECENTS_KEY or side.show_recents)
            and (collection != FAVORITES_KEY or side.tree_model)]


@dataclass
class SideModel:
    """One side of the list: everything that side's section draws."""

    side: str
    tree_model: list                       # the media roots this side holds
    custom_folders: list = field(default_factory=list)
    show_recents: bool = False             # anything at all to list yet
    collection_counts: dict[str, int] = field(default_factory=dict)


class GalleryTree:
    """The folder tree: builds it from the gallery model and answers the lookups
    (key→item, prompt→item, breadcrumb, the selected folder's key) the view
    navigates by. The pane holding the two trees is owned by the view."""

    def __init__(self, tree):
        self._tree = tree
        self.item_by_key: dict[str, QTreeWidgetItem] = {}  # tree key -> its row
        self.leaf_by_id: dict[str, QTreeWidgetItem] = {}   # prompt_id -> its settings row
        # plain key -> the tree keys drawing it, in side order. Each side draws
        # its own copy of every collection, and of every folder holding rows of its
        # shape — so a caller holding a key with no side (a re-roll's folder, a
        # saved session's, a spoken collection name) can still find a row.
        self.keys_by_folder: dict[str, list[str]] = {}
        self._recently_worked: set[str] = set()  # tree keys wearing the mark
        self._drawn_sides: frozenset[str] | None = None
        self._folders_left_open: set[str] = set()

    def populate(self, sides, *, folder_meta=None, recently_worked=()):
        """Rebuild the list from ``sides``, with the folders left open opened again.

        ``sides`` are the :class:`SideModel`s of the sections the pane is
        drawing. ``folder_meta`` is the same label/star overlay the tree models
        were built with, so the All row each side wraps around its model wears
        its name and star like any folder under it.

        ``recently_worked`` are the ``(side, folder key)`` pairs of the folders
        worked in lately (:func:`~origenerator.gallery.recently_worked_folders`),
        whose rows wear a mark. A folder stays where the row that made it put
        it, so the mark is the whole of what says where the work has been.
        """
        self._recently_worked = {oriented_key(key, side)
                                 for side, key in recently_worked}
        self._folders_left_open = self.folders_left_open()
        self._tree.blockSignals(True)
        self._tree.clear()
        self.item_by_key = {}
        self.leaf_by_id = {}
        self.keys_by_folder = {}
        for side in sides:
            self._add_side(self._tree.root_for(side.side), side, folder_meta)
        # Folders default to collapsed; only restore folders the user had open.
        for key in self._folders_left_open:
            item = self.item_by_key.get(key)
            if item is not None:
                item.setExpanded(True)
        self._open_all()
        self._tree.blockSignals(False)
        self._drawn_sides = frozenset(side.side for side in sides)

    def _add_side(self, root, side, folder_meta) -> None:
        """One side's whole table of contents, filling that side's section.

        Drawn even for a side with nothing in it yet: the split is what tells a
        slideshow which screen it is for, so the shape you have not generated
        for is still somewhere you can stand and somewhere its first generation
        can appear.
        """
        for custom in side.custom_folders:
            self._add_custom_folder(root, custom, side.side)
        all_row = self._add_node(gallery.all_group(side.tree_model, folder_meta), root, side)
        all_row.setIcon(0, icons.all_icon())

    def _add_collections(self, folder_item, side, folder_key: str) -> None:
        for collection in _shown_collections(side):
            key = FolderCollection(collection, folder_key).key
            item = QTreeWidgetItem([COLLECTION_LABELS[collection]])
            item.setData(0, COUNT_ROLE, side.collection_counts.get(key, 0))
            item.setIcon(0, icons.collection_icon(collection))
            item.setToolTip(0, _COLLECTION_TIPS[collection])
            if collection == FAVORITES_KEY:
                item.setData(0, DROP_KEY_ROLE, FAVORITES_KEY)
            self._register(item, oriented_key(key, side.side), folder_item,
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

    def _open_all(self) -> None:
        """Open every side's All row on a gallery's first build.

        Every other folder defaults shut, but All shut is a side with nothing in
        it — the workflow folders are where the gallery starts. Only on the first
        build: after that its state is the user's, saved and restored with every
        other folder's, so collapsing it sticks.
        """
        if self.built or self._folders_left_open:
            return
        for key in self.keys_by_folder.get(gallery.ALL_KEY, ()):
            self.item_by_key[key].setExpanded(True)

    def _add_custom_folder(self, side_item, group, side) -> QTreeWidgetItem:
        """Add a row for one of the user's own folders: a collection-shaped row carrying
        its group (so the view's folder machinery — breadcrumb, tiles, slideshow —
        treats it like any other folder), and collecting the folders dropped onto
        it."""
        count = len(gallery.rows_under(group))
        item = QTreeWidgetItem([group.label])
        item.setIcon(0, icons.custom_folder_icon())
        item.setToolTip(0, f"{group.label} — {count} item{'s' if count != 1 else ''} "
                           "in a folder you made; drop folders here to add them")
        item.setData(0, GROUP_ROLE, group)
        item.setData(0, COUNT_ROLE, count)
        item.setData(0, DROP_KEY_ROLE, group.key)  # the folder gathers, not the side
        return self._register(item, oriented_key(group.key, side), side_item,
                              folder_key=group.key)

    def _add_node(self, group, parent_item, side) -> QTreeWidgetItem:
        item = QTreeWidgetItem([group.label])
        item.setData(0, GROUP_ROLE, group)
        item.setData(0, COUNT_ROLE, len(gallery.rows_under(group)))
        badge = icons.folder_badge(group)
        if badge is not None:
            item.setIcon(0, badge[0])
        level = gallery.folder_level(group)
        if level is not None:
            item.setToolTip(0, f"{group.label} · {icons.LEVEL_LABELS[level]}")
        else:
            item.setToolTip(0, group.label)
        self._register(item, oriented_key(group.key, side.side), parent_item,
                       folder_key=group.key)
        if not isinstance(group, gallery.SettingsGroup):
            self._add_collections(item, side, group.key)
        for child in gallery.child_groups(group):
            self._add_node(child, item, side)
        if isinstance(group, gallery.SettingsGroup):
            for row in group.rows:
                self.leaf_by_id[row["prompt_id"]] = item
        return item

    def collections_in(self, item) -> list[str]:
        return [child.data(0, TREE_KEY_ROLE) for child in _children(item)
                if child.data(0, GROUP_ROLE) is None]

    def keys_for_folder(self, folder_key: str) -> list[str]:
        """The tree keys drawing ``folder_key`` — a folder's own key or a collection's
        — in side order, empty for one no side is holding right now."""
        return list(self.keys_by_folder.get(folder_key, ()))

    def mark_favorite(self, folder_key: str, favorite: bool) -> None:
        for key in self.keys_by_folder.get(folder_key, ()):
            item = self.item_by_key[key]
            item.data(0, GROUP_ROLE).favorite = favorite
            item.emitDataChanged()

    def collection_item(self, collection_key: str, side: str) -> QTreeWidgetItem | None:
        """One side's copy of a collection row."""
        return self.item_by_key.get(oriented_key(collection_key, side))

    def set_collection_counts(self, side: str, counts: dict[str, int]) -> None:
        blocked = self._tree.blockSignals(True)
        for key, item in self.item_by_key.items():
            base, drawn_on = split_key(key)
            if drawn_on == side and folder_collection(base) is not None:
                item.setData(0, COUNT_ROLE, counts.get(base, 0))
        self._tree.blockSignals(blocked)

    def default_item(self) -> QTreeWidgetItem | None:
        alls = [self.item_by_key[key] for key in self.keys_by_folder.get(gallery.ALL_KEY, ())]
        holding = [item for item in alls if gallery.child_groups(item.data(0, GROUP_ROLE))]
        return next(iter(holding or alls), None)

    @property
    def built(self) -> bool:
        return self._drawn_sides is not None

    @property
    def drawn_sides(self) -> frozenset[str]:
        return self._drawn_sides or frozenset()

    def expanded_keys(self) -> set[str]:
        return {key for key, item in self.item_by_key.items() if item.isExpanded()}

    def folders_left_open(self) -> set[str]:
        if not self.built:
            return set(self._folders_left_open)
        return ({key for key in self._folders_left_open if side_of(key) not in self.drawn_sides}
                | self.expanded_keys())

    def leave_folders_open(self, keys) -> None:
        self._folders_left_open = set(keys)

    def selected_folder_key(self) -> str | None:
        """The tree key of the selected row — its folder's key with the side it is
        being looked at from appended, or a collection's own oriented key."""
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
            parts.append(_name_of(node))
            node = node.parent()
        side = side_of(item.data(0, TREE_KEY_ROLE)) if item is not None else None
        if side is not None:
            parts.append(SIDE_LABELS[side])
        return PATH_SEPARATOR.join(reversed(parts))

    def key_at_path(self, path: str) -> str | None:
        side_name, *names = path.split(PATH_SEPARATOR.strip())
        side = next((side for side, label in SIDE_LABELS.items()
                     if _same_name(side_name, label)), None)
        if side is None or not names:
            return None
        row = self._tree.root_for(side)
        for name in names:
            row = next((child for child in _children(row)
                        if _same_name(name, _name_of(child))), None)
            if row is None:
                return None
        return row.data(0, TREE_KEY_ROLE)
