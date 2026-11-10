from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import NamedTuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTreeWidgetItem

from origenerator import gallery
from origenerator.gallery.collection import (
    COLLECTION_LABELS,
    COLLECTIONS,
    ENHANCED_KEY,
    EXPERIMENTS_KEY,
    FAVORITES_KEY,
    LATEST_KEY,
    TRASH_KEY,
    FolderCollection,
    folder_collection,
)
from origenerator.gallery.shapes import SHAPE_LABELS
from origenerator.gui import icons
from origenerator.gui.folder_tree import COUNT_ROLE, DROP_KEY_ROLE, RECENT_ROLE, TREE_KEY_ROLE
from origenerator.item_shape import key_holds, shape_of, shaped_key, split_key
from origenerator.media import MediaType

GROUP_ROLE = Qt.ItemDataRole.UserRole
_RECENT_TIP = " · worked in recently"

_COLLECTION_TIPS = {
    LATEST_KEY: "Recently generated",
    FAVORITES_KEY: "Your favorite folders and items — drop a folder here to add it",
    ENHANCED_KEY: "Your enhanced images",
    EXPERIMENTS_KEY: "Background experiments awaiting your review",
    TRASH_KEY: "Deleted items — after a day only their thumbnails are kept, "
               "and restoring one makes it again",
}


PATH_SEPARATOR = "  \u203a  "


class PathStep(NamedTuple):
    name: str
    key: str | None


def path_text(steps) -> str:
    return PATH_SEPARATOR.join(step.name for step in steps)


def _name_of(row) -> str:
    group = row.data(0, GROUP_ROLE)
    return group.label if group is not None else row.text(0)


def _taken_out(item: QTreeWidgetItem) -> bool:
    parent = item.parent()
    if parent is None:
        return False
    parent.takeChild(parent.indexOfChild(item))
    return True


def _children(row) -> Iterator[QTreeWidgetItem]:
    return (row.child(i) for i in range(row.childCount()))


def _tooltip_of(group, kind_icon) -> str:
    if kind_icon is None or isinstance(group, gallery.SettingsGroup) or kind_icon[1] == group.label:
        return group.label
    return f"{group.label} · {kind_icon[1]}"


def _inside(group, inside: tuple) -> tuple:
    return (*inside, group.key) if inside else ()


def _shown_collections(shape, folder_key: str) -> list[str]:
    left_off = set()
    if not shape.show_latest:
        left_off.add(LATEST_KEY)
    if not shape.tree_model:
        left_off |= {FAVORITES_KEY, ENHANCED_KEY}
    if key_holds(MediaType.VIDEO, folder_key):
        left_off.add(ENHANCED_KEY)
    return [collection for collection in COLLECTIONS if collection not in left_off]


@dataclass
class _DrawnFolder:
    group: object
    item: QTreeWidgetItem | None
    registered: list = field(default_factory=list)
    leaves: list = field(default_factory=list)


@dataclass
class ShapeModel:
    shape: str
    tree_model: list
    custom_collections: list = field(default_factory=list)
    show_latest: bool = False
    collection_counts: dict[str, int] = field(default_factory=dict)


class GalleryTree:
    def __init__(self, tree):
        self._tree = tree
        self.item_by_key: dict[str, QTreeWidgetItem] = {}
        self.leaf_by_id: dict[str, QTreeWidgetItem] = {}
        self.keys_by_folder: dict[str, list[str]] = {}
        self._recently_worked: set[str] = set()
        self._drawn_shapes: frozenset[str] | None = None
        self._folders_left_open: set[str] = set()
        self._drawn_workflows: dict[str, _DrawnFolder] = {}
        self._to_put_back: dict[str, _DrawnFolder] = {}
        self._drawing: _DrawnFolder | None = None

    def populate(self, shapes, *, folder_meta=None, recently_worked=()):
        self._recently_worked = {shaped_key(key, shape)
                                 for shape, key in recently_worked}
        self._folders_left_open = self.folders_left_open()
        self._tree.blockSignals(True)
        self._to_put_back = {key: drawn for key, drawn in self._drawn_workflows.items()
                             if _taken_out(drawn.item)}
        self._drawn_workflows = {}
        self._tree.clear()
        self.item_by_key = {}
        self.leaf_by_id = {}
        self.keys_by_folder = {}
        for shape in shapes:
            self._add_side(self._tree.root_for(shape.shape), shape, folder_meta)
        self._to_put_back = {}
        for key in self._folders_left_open:
            item = self.item_by_key.get(key)
            if item is not None:
                item.setExpanded(True)
        self._open_all()
        self._tree.blockSignals(False)
        self._drawn_shapes = frozenset(shape.shape for shape in shapes)

    def _add_side(self, root, shape, folder_meta) -> None:
        customs = [(custom, self._add_custom_collection(custom, root, shape))
                   for custom in shape.custom_collections]
        all_row = self._add_node(gallery.all_group(shape.tree_model, folder_meta), root, shape)
        all_row.setIcon(0, icons.all_icon())
        for custom, row in customs:
            self._add_children(custom, row, shape, (custom.key,))

    def _add_collections(self, folder_item, shape, folder_key: str, inside=()) -> None:
        for collection in _shown_collections(shape, folder_key):
            key = FolderCollection(collection, folder_key).key
            item = QTreeWidgetItem([COLLECTION_LABELS[collection]])
            item.setData(0, COUNT_ROLE, shape.collection_counts.get(key, 0))
            item.setIcon(0, icons.collection_icon(collection))
            item.setToolTip(0, _COLLECTION_TIPS[collection])
            if collection == FAVORITES_KEY:
                item.setData(0, DROP_KEY_ROLE, FAVORITES_KEY)
            self._register(item, shaped_key(key, shape.shape, inside), folder_item,
                           folder_key=key)

    def _register(self, item, key: str, parent_item,
                  folder_key: str | None = None) -> QTreeWidgetItem:
        item.setData(0, TREE_KEY_ROLE, key)
        self._mark_recent(item, key)
        parent_item.addChild(item)
        self._keep_track_of(item, key, folder_key)
        if self._drawing is not None:
            self._drawing.registered.append((key, item, folder_key))
        return item

    def _keep_track_of(self, item, key: str, folder_key: str | None) -> None:
        self.item_by_key[key] = item
        if folder_key is not None:
            self.keys_by_folder.setdefault(folder_key, []).append(key)

    def _mark_recent(self, item, key: str) -> None:
        recent = shaped_key(*split_key(key)) in self._recently_worked
        if bool(item.data(0, RECENT_ROLE)) == recent:
            return
        item.setData(0, RECENT_ROLE, True if recent else None)
        tip = item.toolTip(0)
        item.setToolTip(0, f"{tip}{_RECENT_TIP}" if recent else tip.removesuffix(_RECENT_TIP))

    def _open_all(self) -> None:
        if self.built or self._folders_left_open:
            return
        for key in self.keys_by_folder.get(gallery.ALL_KEY, ()):
            self.item_by_key[key].setExpanded(True)

    def _add_custom_collection(self, group, parent_item, shape, inside=()) -> QTreeWidgetItem:
        count = len(gallery.rows_under(group))
        item = QTreeWidgetItem([group.label])
        item.setIcon(0, icons.custom_collection_icon())
        item.setToolTip(0, f"{group.label} — {count} item{'s' if count != 1 else ''} "
                           "in a folder you made; drop folders or items here to add them")
        item.setData(0, GROUP_ROLE, group)
        item.setData(0, COUNT_ROLE, count)
        item.setData(0, DROP_KEY_ROLE, group.key)
        return self._register(item, shaped_key(group.key, shape.shape, inside), parent_item,
                              folder_key=group.key)

    def _add_node(self, group, parent_item, shape, inside=()) -> QTreeWidgetItem:
        if isinstance(group, gallery.WorkflowGroup) and not inside:
            return self._add_workflow(group, parent_item, shape)
        if isinstance(group, gallery.CustomCollection):
            item = self._add_custom_collection(group, parent_item, shape, inside)
        else:
            item = self._add_folder(group, parent_item, shape, inside)
        self._add_children(group, item, shape, _inside(group, inside))
        if isinstance(group, gallery.SettingsGroup) and not inside:
            for row in group.rows:
                self.leaf_by_id[row["prompt_id"]] = item
                if self._drawing is not None:
                    self._drawing.leaves.append((row["prompt_id"], item))
        return item

    def _add_workflow(self, group, parent_item, shape) -> QTreeWidgetItem:
        key = shaped_key(group.key, shape.shape)
        drawn = self._to_put_back.pop(key, None)
        if drawn is not None and drawn.group is group:
            self._put_back(drawn, parent_item, shape)
        else:
            drawn = self._drawing = _DrawnFolder(group, None)
            drawn.item = self._add_folder(group, parent_item, shape, ())
            self._add_children(group, drawn.item, shape, ())
            self._drawing = None
        self._drawn_workflows[key] = drawn
        return drawn.item

    def _put_back(self, drawn: _DrawnFolder, parent_item, shape) -> None:
        parent_item.addChild(drawn.item)
        for key, item, folder_key in drawn.registered:
            self._keep_track_of(item, key, folder_key)
            self._mark_recent(item, key)
            if folder_key is not None and folder_collection(folder_key) is not None:
                item.setData(0, COUNT_ROLE, shape.collection_counts.get(folder_key, 0))
        self.leaf_by_id.update(drawn.leaves)

    def _add_folder(self, group, parent_item, shape, inside) -> QTreeWidgetItem:
        item = QTreeWidgetItem([group.label])
        item.setData(0, GROUP_ROLE, group)
        item.setData(0, COUNT_ROLE, len(gallery.rows_under(group)))
        kind_icon = icons.folder_kind_icon(group)
        if kind_icon is not None:
            item.setIcon(0, kind_icon[0])
        item.setToolTip(0, _tooltip_of(group, kind_icon))
        self._register(item, shaped_key(group.key, shape.shape, inside), parent_item,
                       folder_key=group.key)
        if not isinstance(group, gallery.SettingsGroup):
            self._add_collections(item, shape, group.key, _inside(group, inside))
        return item

    def _add_children(self, group, item, shape, inside) -> None:
        for child in gallery.child_groups(group):
            self._add_node(child, item, shape, inside)

    def collections_in(self, item) -> list[str]:
        return [child.data(0, TREE_KEY_ROLE) for child in _children(item)
                if child.data(0, GROUP_ROLE) is None]

    def keys_for_folder(self, folder_key: str) -> list[str]:
        return list(self.keys_by_folder.get(folder_key, ()))

    def mark_favorite(self, folder_key: str, favorite: bool) -> None:
        for key in self.keys_by_folder.get(folder_key, ()):
            item = self.item_by_key[key]
            item.data(0, GROUP_ROLE).favorite = favorite
            item.emitDataChanged()

    def collection_item(self, collection_key: str, shape: str) -> QTreeWidgetItem | None:
        return self.item_by_key.get(shaped_key(collection_key, shape))

    def set_collection_counts(self, shape: str, counts: dict[str, int]) -> None:
        blocked = self._tree.blockSignals(True)
        for key, item in self.item_by_key.items():
            base, drawn_on = split_key(key)
            if drawn_on == shape and folder_collection(base) is not None:
                item.setData(0, COUNT_ROLE, counts.get(base, 0))
        self._tree.blockSignals(blocked)

    def default_item(self) -> QTreeWidgetItem | None:
        alls = [self.item_by_key[key] for key in self.keys_by_folder.get(gallery.ALL_KEY, ())]
        holding = [item for item in alls if gallery.child_groups(item.data(0, GROUP_ROLE))]
        return next(iter(holding or alls), None)

    @property
    def built(self) -> bool:
        return self._drawn_shapes is not None

    @property
    def drawn_sides(self) -> frozenset[str]:
        return self._drawn_shapes or frozenset()

    def expanded_keys(self) -> set[str]:
        return {key for key, item in self.item_by_key.items() if item.isExpanded()}

    def folders_left_open(self) -> set[str]:
        if not self.built:
            return set(self._folders_left_open)
        return ({key for key in self._folders_left_open if shape_of(key) not in self.drawn_sides}
                | self.expanded_keys())

    def leave_folders_open(self, keys) -> None:
        self._folders_left_open = set(keys)

    def selected_folder_key(self) -> str | None:
        item = self._tree.currentItem()
        return item.data(0, TREE_KEY_ROLE) if item is not None else None

    def path_steps(self, item) -> list[PathStep]:
        steps = []
        node = item
        while node is not None:
            steps.append(PathStep(_name_of(node), node.data(0, TREE_KEY_ROLE)))
            node = node.parent()
        shape = shape_of(item.data(0, TREE_KEY_ROLE)) if item is not None else None
        if shape is not None:
            steps.append(PathStep(SHAPE_LABELS[shape], None))
        return steps[::-1]

    def folder_path(self, item) -> str:
        return path_text(self.path_steps(item))
