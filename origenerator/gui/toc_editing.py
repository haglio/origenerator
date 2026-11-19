from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Protocol

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QInputDialog, QMenu, QWidget

from origenerator import gallery
from origenerator.gallery.collection import FAVORITES_KEY
from origenerator.gui.copy_names import offer_copy_names_above_a_line
from origenerator.gui.deleting import asked_to_delete, deleting_a_folder, deleting_folders
from origenerator.gui.folder_tree import TREE_KEY_ROLE, offer_collapse_and_expand
from origenerator.gui.gallery_tree import GROUP_ROLE, takes_a_favorite
from origenerator.item_shape import base_of, shape_of


@dataclass(frozen=True)
class AroundAnEdit:
    refresh: Callable[[], None]
    re_aim_every_button: Callable[[], None]
    delete_rows: Callable[[list[dict]], None]
    current_group: Callable[[], object]
    showing_search: Callable[[], bool]
    draw_folder_favorite: Callable[[str, bool], None]


def _kept_on_removal(custom) -> str:
    folders, items = len(gallery.child_groups(custom)), len(custom.rows)
    if not items:
        return f"The {folders} folder{'s' if folders != 1 else ''} it holds, and their items, are kept."
    held = f"{items} item{'s' if items != 1 else ''}"
    if folders:
        held = f"{folders} folder{'s' if folders != 1 else ''} and {held}"
    return f"The {held} it holds are kept."


@dataclass(frozen=True)
class FolderAsked:
    key: str
    group: object
    holder: object
    toc_rows: tuple


class FolderAction(Protocol):
    def offer(self, menu: QMenu, asked: FolderAsked, editing: TocEditing) -> dict: ...


class FavoriteIt:
    def offer(self, menu, asked, editing) -> dict:
        if not takes_a_favorite(asked.group):
            return {}
        return {menu.addAction("Unfavorite" if asked.group.favorite else "Favorite"):
                lambda: editing.toggle_favorite(asked.key)}


class TakeItOutOfItsCollection:
    def offer(self, menu, asked, editing) -> dict:
        holder, group = asked.holder, asked.group
        if not holder or all(m.key != group.key for m in gallery.child_groups(holder)):
            return {}
        return {menu.addAction(f"Remove from “{holder.label}”"):
                lambda: editing.remove_from_collection(holder, [group.key])}


class AddItToACollection:
    def offer(self, menu, asked, editing) -> dict:
        targets = editing.collections_that_could_take(asked)
        if not targets:
            return {}
        submenu = menu.addMenu("Add to collection")
        return {submenu.addAction(folder.label): partial(editing.dropped, folder.key, [asked.key])
                for folder in targets}


class RemoveTheCollection:
    def offer(self, menu, asked, editing) -> dict:
        if not isinstance(asked.group, gallery.CustomCollection):
            return {}
        return {menu.addAction("Remove collection…"):
                lambda: editing.remove_collection(asked.group)}


class DeleteTheFolder:
    def offer(self, menu, asked, editing) -> dict:
        if not is_deletable_folder(asked.group):
            return {}
        menu.addSeparator()
        return {menu.addAction("Delete folder…"): lambda: editing.delete_folders([asked.group])}


class CollapseAndExpandIt:
    def offer(self, menu, asked, editing) -> dict:
        return offer_collapse_and_expand(menu, asked.toc_rows)


FOLDER_ACTIONS: tuple[FolderAction, ...] = (
    FavoriteIt(), TakeItOutOfItsCollection(), AddItToACollection(), RemoveTheCollection(),
    DeleteTheFolder(), CollapseAndExpandIt())


def _folder_of_your_own_above(rows):
    parent = rows[0].parent()
    return saved_custom_collection(parent.data(0, GROUP_ROLE)) if parent is not None else None


def saved_custom_collection(group):
    return group if isinstance(group, gallery.CustomCollection) and group.folder_id is not None else None


def names_of_the_picked_folders(selection_group) -> list[str]:
    return [group.label for group in gallery.child_groups(selection_group)]


def _is_one_of_the_picked(selection_group, group) -> bool:
    return (selection_group is not None and group is not None
            and any(m.key == group.key for m in gallery.child_groups(selection_group)))


def is_deletable_folder(group) -> bool:
    return isinstance(group, gallery.SettingsGroup)


class TocEditing:
    def __init__(self, tree, toc, *, edits, library, folder_switches, screen: AroundAnEdit,
                 asks_over: QWidget,
                 folder_actions: tuple[FolderAction, ...] = FOLDER_ACTIONS) -> None:
        self._folder_actions = folder_actions
        self._tree = tree
        self._toc = toc
        self._edits = edits
        self._library = library
        self._folder_switches = folder_switches
        self._screen = screen
        self._asks_over = asks_over
        self.visits: list[str] = []

    def note_visit(self, key: str) -> None:
        if not self.visits or self.visits[-1] != key:
            self.visits.append(key)

    def confirm(self, text: str) -> bool:
        return asked_to_delete(self._asks_over, text)

    def group_the_picked(self):
        group = self._toc.picked_together
        if group is None:
            return
        folders = gallery.child_groups(group)
        name, ok = QInputDialog.getText(
            self._asks_over, "New collection",
            f"Name for a collection holding these {len(folders)} folders:",
        )
        if not ok or not name.strip():
            return
        folder_id = self._edits.custom_collections.create(
            name.strip(), [self._folder_identity(f) for f in folders], self._toc.shape_in_view()
        )
        self._open_collection_of_your_own(folder_id)

    def _folder_identity(self, group) -> tuple:
        rows = gallery.rows_under(group)
        return (group.key, gallery.group_level(group),
                rows[0]["prompt_id"] if rows else None)

    def _open_collection_of_your_own(self, folder_id: int):
        self._toc.forget_the_picking()
        self._screen.refresh()
        self._screen.re_aim_every_button()
        item = self._toc.item_for(gallery.custom_collection_key(folder_id))
        if item is not None:
            self._tree.setCurrentItem(item)

    def dropped(self, target_key: str, keys: list, prompt_ids: list = ()):
        groups = [g for key in keys if (g := self._toc.group_for_key(key)) is not None]
        if target_key == FAVORITES_KEY:
            for group in groups:
                if takes_a_favorite(group):
                    self.set_folder_favorite(group.key, True)
            self._screen.re_aim_every_button()
            return
        folder_id = gallery.custom_folder_id(target_key)
        if folder_id is None:
            return
        self._edits.custom_collections.add_to(
            folder_id, [self._folder_identity(g) for g in groups], prompt_ids
        )
        self._open_collection_of_your_own(folder_id)

    def landing_in_the_open_collection(self, mime, source):
        if saved_custom_collection(self._screen.current_group()) is None:
            return None
        return self._tree.landing_on(self._tree.currentItem(), mime, source)

    def _new_collection(self, shape: str):
        name, ok = QInputDialog.getText(self._asks_over, "New collection", "Collection name:")
        if ok and name.strip():
            self._open_collection_of_your_own(
                self._edits.custom_collections.create(name.strip(), [], shape))

    def remove_collection(self, group):
        if not self.confirm(f"Remove the folder “{group.label}”?\n\n{_kept_on_removal(group)}"):
            return
        self._edits.custom_collections.delete(group.folder_id)
        self._toc.forget_the_picking()
        self._screen.refresh()
        self._screen.re_aim_every_button()

    def remove_from_collection(self, group, folder_keys=(), items=()):
        folders = [self._folder_identity(gathered)
                   if (gathered := self._toc.group_for_key(key)) is not None else (key, None, None)
                   for key in folder_keys]
        self._edits.custom_collections.remove_from(group.folder_id, folders, items)
        self._screen.refresh()
        self._screen.re_aim_every_button()

    def deletable_folders(self) -> list:
        if self._screen.showing_search():
            return []
        if self._toc.picked_together is None:
            folders = [self._screen.current_group()]
        else:
            folders = [self._toc.group_for_key(key) for key in self._tree.selected_folder_keys()]
        return folders if all(is_deletable_folder(group) for group in folders) else []

    def delete_folders(self, groups):
        if not groups or not all(is_deletable_folder(group) for group in groups):
            return
        rows = list({row["prompt_id"]: row for group in groups
                     for row in gallery.rows_under(group)}.values())
        if not rows:
            return
        if not self.confirm(deleting_a_folder(groups[0].label, len(rows)) if len(groups) == 1
                             else deleting_folders(len(groups), len(rows))):
            return
        target = self._post_delete_target(groups)
        if target is not None:
            self._tree.setCurrentItem(target)
        self._screen.delete_rows(rows)

    def _post_delete_target(self, groups):
        doomed = set().union(*(self._keys_under(group) for group in groups))
        for key in reversed(self.visits):
            if key not in doomed and (item := self._toc.item_by_key.get(key)) is not None:
                return item
        item = self._toc.item_for(groups[0].key)
        while item is not None and item.data(0, TREE_KEY_ROLE) in doomed:
            item = item.parent()
        return item

    def _keys_under(self, group) -> set[str]:
        keys, stack = set(), [self._toc.item_by_key[key] for key
                              in self._toc.keys_for_folder(group.key)]
        while stack:
            node = stack.pop()
            if node.data(0, GROUP_ROLE) is not None:
                keys.add(node.data(0, TREE_KEY_ROLE))
            stack.extend(node.child(i) for i in range(node.childCount()))
        return keys

    def tree_context_menu(self, item, global_pos: QPoint, shape: str):
        if item is None:
            self._empty_tree_context_menu(global_pos, shape)
            return
        if _is_one_of_the_picked(self._toc.picked_together, item.data(0, GROUP_ROLE)):
            self._selection_context_menu(global_pos)
            return
        if item.data(0, GROUP_ROLE) is not None:
            self.folder_context_menu(item.data(0, TREE_KEY_ROLE), global_pos,
                                      toc_rows=[item])

    def _empty_tree_context_menu(self, global_pos: QPoint, shape: str):
        menu = QMenu(self._asks_over)
        new_action = menu.addAction("New collection…")
        if menu.exec(global_pos) == new_action:
            self._new_collection(shape)

    def _selection_context_menu(self, global_pos: QPoint):
        names = names_of_the_picked_folders(self._toc.picked_together)
        menu = QMenu(self._asks_over)
        offer_copy_names_above_a_line(menu, names)
        group_action = menu.addAction(f"Group {len(names)} folders into a new collection…")
        doomed = self.deletable_folders()
        delete_action = None
        if doomed:
            menu.addSeparator()
            delete_action = menu.addAction(f"Delete {len(doomed)} folders…")
        collapse_and_expand = offer_collapse_and_expand(menu, self._tree.selectedItems())
        chosen = menu.exec(global_pos)
        if chosen == group_action:
            self.group_the_picked()
        elif delete_action is not None and chosen == delete_action:
            self.delete_folders(doomed)
        elif chosen in collapse_and_expand:
            collapse_and_expand[chosen]()

    def folder_context_menu(self, key: str, global_pos: QPoint, toc_rows=()):
        group = self._toc.group_for_key(key)
        if group is None:
            return
        holder = (_folder_of_your_own_above(toc_rows) if toc_rows
                  else saved_custom_collection(self._screen.current_group()))
        asked = FolderAsked(key, group, holder, tuple(toc_rows))
        menu = QMenu(self._asks_over)
        offer_copy_names_above_a_line(menu, [group.label])
        offered: dict = {}
        for action in self._folder_actions:
            offered.update(action.offer(menu, asked, self))
        chosen = menu.exec(global_pos)
        if chosen in offered:
            offered[chosen]()

    def collections_that_could_take(self, asked: FolderAsked) -> list:
        if isinstance(asked.group, gallery.CustomCollection):
            return []
        shape = shape_of(asked.key) or self._toc.shape_in_view()
        return [f for f in self._library.customs_by_shape.get(shape, ())
                if not any(m.key == base_of(asked.key) for m in gallery.child_groups(f))]

    def toggle_favorite(self, key: str):
        group = self._toc.group_for_key(key)
        if takes_a_favorite(group):
            self.set_folder_favorite(group.key, not group.favorite)
            self._screen.re_aim_every_button()

    def set_folder_favorite(self, key: str, favorite: bool):
        if not self._folder_switches.set_favorite(key, favorite):
            return
        self._toc.mark_favorite(key, favorite)
        self._library.folder_meta_edited()
        self._screen.draw_folder_favorite(key, favorite)
        if favorite:
            self._folder_switches.star_what_is_in(key)

    def delete_folder_by_key(self, key: str):
        group = self._toc.group_for_key(key)
        if _is_one_of_the_picked(self._toc.picked_together, group):
            self.delete_folders(self.deletable_folders())
        elif group is not None:
            self.delete_folders([group])
