from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import NamedTuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem

from origenerator import gallery
from origenerator.gallery.collection import (
    FolderCollection,
    all_collections,
    folder_collection,
)
from origenerator.gallery.shapes import LANDSCAPE, SHAPE_LABELS, shape_holding
from origenerator.gui import folder_icons, icons
from origenerator.gui.folder_tree import COUNT_ROLE, DROP_KEY_ROLE, RECENT_ROLE, TREE_KEY_ROLE
from origenerator.gui.split_folder_tree import SplitFolderTree
from origenerator.item_shape import base_of, shape_of, shaped_key, split_key
from origenerator.workflows.non_ai import folder_kind

GROUP_ROLE = Qt.ItemDataRole.UserRole
_RECENT_TIP = " · worked in recently"

PATH_SEPARATOR = "  \u203a  "


class PathStep(NamedTuple):
    name: str
    key: str | None


def path_text(steps) -> str:
    return PATH_SEPARATOR.join(step.name for step in steps)


def _name_of(row) -> str:
    group = row.data(0, GROUP_ROLE)
    return group.label if group is not None else row.text(0)


def _children(row) -> Iterator[QTreeWidgetItem]:
    return (row.child(i) for i in range(row.childCount()))


def _tooltip_of(group, kind_icon) -> str:
    if kind_icon is None or isinstance(group, gallery.SettingsGroup) or kind_icon[1] == group.label:
        return group.label
    return f"{group.label} · {kind_icon[1]}"


def _inside(group, inside: tuple) -> tuple:
    return (*inside, group.key) if inside else ()


def _shown_collections(shape, group) -> list:
    nothing_generated = folder_kind(getattr(group, "workflow_name", None)) == "non_ai"
    at_the_top = getattr(group, "key", None) == gallery.ALL_KEY
    return [shown for shown in all_collections() if shown.shown_in(shape)
            and not (shown.of_what_was_generated and nothing_generated)
            and (at_the_top or not shown.at_the_top_only)]


@dataclass
class _DrawnFolder:
    group: object
    item: QTreeWidgetItem | None
    own: list = field(default_factory=list)
    leaves: list = field(default_factory=list)
    children: list = field(default_factory=list)


@dataclass
class ShapeModel:
    shape: str
    tree_model: list
    custom_collections: list = field(default_factory=list)
    show_latest: bool = False
    collection_counts: dict[str, int] = field(default_factory=dict)


def takes_a_favorite(group) -> bool:
    return isinstance(group, gallery.SettingsGroup)


class GalleryTree:
    def __init__(self, tree=None):
        self._tree = tree if tree is not None else SplitFolderTree(
            GROUP_ROLE, takes_item=self.takes_item, takes_folder=self.takes_folder)
        self.item_by_key: dict[str, QTreeWidgetItem] = {}
        self.leaf_by_id: dict[str, QTreeWidgetItem] = {}
        self.keys_by_folder: dict[str, list[str]] = {}
        self._recently_worked: set[str] = set()
        self._drawn_shapes: frozenset[str] | None = None
        self._folders_left_open: set[str] = set()
        self._drawn_folders: dict[str, _DrawnFolder] = {}
        self._customs_drawn: dict[str, list[_DrawnFolder]] = {}
        self._counts_drawn: dict[str, dict[str, int]] = {}
        self._drawing: list[_DrawnFolder] = []
        self.picked_together = None

    def populate(self, shapes, *, folder_meta=None, recently_worked=()):
        recent_before = self._recently_worked
        self._recently_worked = {shaped_key(key, shape)
                                 for shape, key in recently_worked}
        self._tree.blockSignals(True)
        drawing = frozenset(shape.shape for shape in shapes)
        if self.built and drawing == self._drawn_shapes:
            for shape in shapes:
                self._bring_the_side_up_to_date(self._tree.root_for(shape.shape), shape,
                                                folder_meta)
            self._mark_what_turned_recent(recent_before ^ self._recently_worked)
        else:
            self._draw_every_side(shapes, folder_meta)
        self._tree.blockSignals(False)
        self._drawn_shapes = drawing

    def _draw_every_side(self, shapes, folder_meta) -> None:
        self._folders_left_open = self.folders_left_open()
        self._tree.clear()
        self.item_by_key, self.leaf_by_id, self.keys_by_folder = {}, {}, {}
        self._drawn_folders, self._customs_drawn = {}, {}
        for shape in shapes:
            root = self._tree.root_for(shape.shape)
            customs = self._add_customs(root, shape)
            self._add_node(gallery.all_group(shape.tree_model, folder_meta), root,
                           shape).setIcon(0, icons.all_icon())
            self._fill_customs(customs, shape)
            self._counts_drawn[shape.shape] = dict(shape.collection_counts)
        for key in self._folders_left_open:
            item = self.item_by_key.get(key)
            if item is not None:
                item.setExpanded(True)
        self._open_all()

    def _add_customs(self, root, shape) -> list[_DrawnFolder]:
        customs = []
        for custom in shape.custom_collections:
            holder = _DrawnFolder(custom, None)
            self._drawing.append(holder)
            holder.item = self._add_custom_collection(custom, root, shape)
            self._drawing.pop()
            customs.append(holder)
        self._customs_drawn[shape.shape] = customs
        return customs

    def _fill_customs(self, customs: list[_DrawnFolder], shape) -> None:
        for holder in customs:
            self._drawing.append(holder)
            self._add_children(holder.group, holder.item, shape, (holder.group.key,))
            self._drawing.pop()

    def _bring_the_side_up_to_date(self, root, shape, folder_meta) -> None:
        left_open = set()
        for holder in self._customs_drawn.pop(shape.shape, []):
            left_open |= self._open_under(holder)
            root.removeChild(holder.item)
            self._forget(holder)
        customs = self._add_customs(root, shape)
        for place, holder in enumerate(customs):
            root.removeChild(holder.item)
            root.insertChild(place, holder.item)
        everything = gallery.all_group(shape.tree_model, folder_meta)
        self._bring_up_to_date(self._drawn_folders[shaped_key(everything.key, shape.shape)],
                               everything, shape, ())
        self._fill_customs(customs, shape)
        for key in left_open:
            if (item := self.item_by_key.get(key)) is not None:
                item.setExpanded(True)
        self._take_the_counts_that_moved(shape)

    def _open_under(self, drawn: _DrawnFolder) -> set[str]:
        left_open = {key for key, item, _folder_key in drawn.own if item.isExpanded()}
        for child_key in drawn.children:
            if (child := self._drawn_folders.get(child_key)) is not None:
                left_open |= self._open_under(child)
        return left_open

    def _bring_up_to_date(self, drawn: _DrawnFolder, group, shape, inside) -> None:
        if drawn.group is group:
            return
        item = drawn.item
        drawn.group = group
        item.setText(0, group.label)
        item.setData(0, GROUP_ROLE, group)
        item.setData(0, COUNT_ROLE, len(gallery.rows_under(group)))
        kind_icon = folder_icons.folder_kind_icon(group)
        if kind_icon is not None:
            item.setIcon(0, kind_icon[0])
        item.setToolTip(0, _tooltip_of(group, kind_icon))
        if isinstance(group, gallery.SettingsGroup) and not inside:
            self._forget_the_leaves(drawn)
            drawn.leaves = [(row["prompt_id"], item) for row in group.rows]
            self.leaf_by_id.update(drawn.leaves)
        self._bring_the_children_up_to_date(drawn, group, shape, _inside(group, inside))

    def _bring_the_children_up_to_date(self, drawn: _DrawnFolder, group, shape, inside) -> None:
        item = drawn.item
        wanted = []
        self._drawing.append(drawn)
        for child in gallery.child_groups(group):
            child_key = shaped_key(child.key, shape.shape, inside)
            child_drawn = self._drawn_folders.get(child_key)
            if child_drawn is not None and child_drawn.item.parent() is item:
                self._bring_up_to_date(child_drawn, child, shape, inside)
            else:
                if child_drawn is not None:
                    self._drop(child_key)
                self._add_node(child, item, shape, inside)
                drawn.children.pop()
            wanted.append(child_key)
        self._drawing.pop()
        keeping = set(wanted)
        for gone in [child_key for child_key in drawn.children if child_key not in keeping]:
            self._drop(gone)
        drawn.children = wanted
        first = len(self.collections_in(item))
        for place, child_key in enumerate(wanted, start=first):
            child_item = self._drawn_folders[child_key].item
            if item.indexOfChild(child_item) != place:
                item.removeChild(child_item)
                item.insertChild(place, child_item)

    def _drop(self, key: str) -> None:
        drawn = self._drawn_folders.pop(key, None)
        if drawn is None:
            return
        parent = drawn.item.parent()
        if parent is not None:
            parent.removeChild(drawn.item)
        self._forget(drawn)

    def _forget(self, drawn: _DrawnFolder) -> None:
        for key, item, folder_key in drawn.own:
            if self.item_by_key.get(key) is item:
                del self.item_by_key[key]
                if folder_key is not None and key in self.keys_by_folder.get(folder_key, ()):
                    self.keys_by_folder[folder_key].remove(key)
        self._forget_the_leaves(drawn)
        for child_key in drawn.children:
            child = self._drawn_folders.pop(child_key, None)
            if child is not None:
                self._forget(child)

    def _forget_the_leaves(self, drawn: _DrawnFolder) -> None:
        for prompt_id, item in drawn.leaves:
            if self.leaf_by_id.get(prompt_id) is item:
                del self.leaf_by_id[prompt_id]

    def _mark_what_turned_recent(self, turned) -> None:
        for recent in turned:
            folder_key, shape = split_key(recent)
            for key in self.keys_by_folder.get(folder_key, ()):
                if split_key(key)[1] == shape:
                    self._mark_recent(self.item_by_key[key], key)

    def _take_the_counts_that_moved(self, shape) -> None:
        before = self._counts_drawn.get(shape.shape, {})
        now = dict(shape.collection_counts)
        for folder_key in {*before, *now}:
            if before.get(folder_key, 0) == now.get(folder_key, 0):
                continue
            for key in self.keys_by_folder.get(folder_key, ()):
                if split_key(key)[1] == shape.shape:
                    self.item_by_key[key].setData(0, COUNT_ROLE, now.get(folder_key, 0))
        self._counts_drawn[shape.shape] = now

    def _add_collections(self, folder_item, shape, group, inside=()) -> None:
        folder_key = group.key
        for shown in _shown_collections(shape, group):
            key = FolderCollection(shown.key, folder_key).key
            item = QTreeWidgetItem([shown.label])
            item.setData(0, COUNT_ROLE, shape.collection_counts.get(key, 0))
            item.setIcon(0, folder_icons.collection_icon(shown.key))
            item.setToolTip(0, shown.tooltip)
            if shown.gathers_folders:
                item.setData(0, DROP_KEY_ROLE, shown.key)
            self._register(item, shaped_key(key, shape.shape, inside), folder_item,
                           folder_key=key)

    def _register(self, item, key: str, parent_item,
                  folder_key: str | None = None) -> QTreeWidgetItem:
        item.setData(0, TREE_KEY_ROLE, key)
        self._mark_recent(item, key)
        parent_item.addChild(item)
        self._keep_track_of(item, key, folder_key)
        if self._drawing:
            self._drawing[-1].own.append((key, item, folder_key))
        return item

    def _keep_track_of(self, item, key: str, folder_key: str | None) -> None:
        self.item_by_key[key] = item
        if folder_key is not None:
            keys = self.keys_by_folder.setdefault(folder_key, [])
            if key not in keys:
                keys.append(key)

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
        rows = gallery.rows_under(group)
        count = len(rows)
        item = QTreeWidgetItem([group.label])
        item.setIcon(0, icons.custom_collection_icon())
        item.setToolTip(0, f"{group.label} — {gallery.counted(rows)} "
                           "in a folder you made; drop folders or items here to add them")
        item.setData(0, GROUP_ROLE, group)
        item.setData(0, COUNT_ROLE, count)
        item.setData(0, DROP_KEY_ROLE, group.key)
        return self._register(item, shaped_key(group.key, shape.shape, inside), parent_item,
                              folder_key=group.key)

    def _add_node(self, group, parent_item, shape, inside=()) -> QTreeWidgetItem:
        if isinstance(group, gallery.CustomCollection):
            item = self._add_custom_collection(group, parent_item, shape, inside)
            self._add_children(group, item, shape, _inside(group, inside))
            return item
        key = shaped_key(group.key, shape.shape, inside)
        drawn = _DrawnFolder(group, None)
        if self._drawing:
            self._drawing[-1].children.append(key)
        self._drawing.append(drawn)
        drawn.item = self._add_folder(group, parent_item, shape, inside)
        self._add_children(group, drawn.item, shape, _inside(group, inside))
        self._drawing.pop()
        if isinstance(group, gallery.SettingsGroup) and not inside:
            drawn.leaves = [(row["prompt_id"], drawn.item) for row in group.rows]
            self.leaf_by_id.update(drawn.leaves)
        self._drawn_folders[key] = drawn
        return drawn.item

    def _add_folder(self, group, parent_item, shape, inside) -> QTreeWidgetItem:
        item = QTreeWidgetItem([group.label])
        item.setData(0, GROUP_ROLE, group)
        item.setData(0, COUNT_ROLE, len(gallery.rows_under(group)))
        kind_icon = folder_icons.folder_kind_icon(group)
        if kind_icon is not None:
            item.setIcon(0, kind_icon[0])
        item.setToolTip(0, _tooltip_of(group, kind_icon))
        self._register(item, shaped_key(group.key, shape.shape, inside), parent_item,
                       folder_key=group.key)
        if not isinstance(group, gallery.SettingsGroup):
            self._add_collections(item, shape, group, _inside(group, inside))
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

    @property
    def widget(self):
        return self._tree

    def place(self) -> dict[str, int]:
        return self._tree.scroll_places()

    def return_to(self, place: dict[str, int]) -> None:
        self._tree.scroll_back_to(place)

    def selected_folder_key(self) -> str | None:
        item = self._tree.currentItem()
        return item.data(0, TREE_KEY_ROLE) if item is not None else None

    def shape_in_view(self) -> str:
        return (shape_of(self.selected_folder_key())
                or shape_holding(LANDSCAPE, self._tree.shapes))

    def item_for(self, key: str) -> QTreeWidgetItem | None:
        item = self.item_by_key.get(key)
        if item is not None:
            return item
        folder = base_of(key)
        drawn = self.keys_for_folder(folder)
        if shape_of(key) in self._tree.shapes:
            return next((self.item_by_key[row] for row in drawn
                         if shape_of(row) == shape_of(key)), None)
        if not drawn:
            return None
        here = shaped_key(folder, self.shape_in_view())
        return self.item_by_key[here if here in drawn else drawn[0]]

    def stand_in_collection(self, key: str, shape: str | None) -> bool:
        item = self.item_for(shaped_key(key, shape) if shape else key)
        if item is None:
            return False
        self._tree.setCurrentItem(item)
        return True

    def group_for_key(self, key: str):
        item = self.item_for(key)
        return item.data(0, GROUP_ROLE) if item is not None else None

    def forget_the_picking(self) -> None:
        self._tree.clearSelection()
        self.picked_together = None

    def takes_item(self, row_key: str, prompt_id: str) -> bool:
        folder = self.group_for_key(row_key)
        leaf = self.leaf_by_id.get(prompt_id)
        return (isinstance(folder, gallery.CustomCollection) and leaf is not None
                and shape_of(leaf.data(0, TREE_KEY_ROLE)) == shape_of(row_key))

    def takes_folder(self, row_key: str, folder_key: str) -> bool:
        target, dragged = self.group_for_key(row_key), self.group_for_key(folder_key)
        if dragged is None:
            return False
        if isinstance(target, gallery.CustomCollection):
            return not gallery.holds(dragged, target)
        return takes_a_favorite(dragged)

    def folder_context(self, key: str) -> str:
        item = self.item_for(key)
        if item is None or item.parent() is None:
            return ""
        return self.folder_path(item.parent())

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
