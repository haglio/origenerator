from __future__ import annotations

from typing import Protocol

from origenerator import gallery
from origenerator.branch_session import is_branch_session
from origenerator.folder_arrivals import arrivals_in
from origenerator.gui.enhance_controller import NO_VIDEO_ENHANCER, all_video
from origenerator.gui.gallery_pane_buttons import Button

ONLY_A_LEAF_IS_FAVORITED = "Only a leaf folder can be favorited"
ONLY_A_LEAF_IS_ENHANCED = "Only a leaf folder can be enhanced as a whole"
_NEVER_SWITCHED = {"custom_name": None, "starred": False}


class FolderSwitchesHost(Protocol):
    def open_leaf_folder(self) -> gallery.SettingsGroup | None: ...

    def leaf_folders(self) -> dict[str, list[dict]]: ...

    def folder_meta(self) -> dict[str, dict]: ...

    def highest_id_listed(self) -> int: ...

    def set_items_favorite(self, prompt_ids, favorite: bool) -> None: ...


class FolderSwitches:
    def __init__(self, host: FolderSwitchesHost, db, enhance):
        self._host = host
        self._db = db
        self._enhance = enhance
        self._takes_up_older_stars = not is_branch_session()

    def favorite_switch(self) -> Button:
        leaf = self._host.open_leaf_folder()
        if leaf is None:
            return Button(enabled=False, tip=ONLY_A_LEAF_IS_FAVORITED, checked=False)
        if leaf.favorite:
            return Button(tip=f"Stop favoriting new items in “{leaf.label}” (their stars stay)",
                          checked=True)
        return Button(tip=f"Favorite every item in “{leaf.label}”, and each new one that arrives",
                      checked=False)

    def enhance_switch(self) -> Button:
        leaf = self._host.open_leaf_folder()
        if leaf is None:
            return Button(enabled=False, tip=ONLY_A_LEAF_IS_ENHANCED, checked=False)
        if all_video(leaf.rows):
            return Button(enabled=False, tip=NO_VIDEO_ENHANCER, checked=False)
        if self.enhancing(leaf.key):
            return Button(tip=f"Stop enhancing new images in “{leaf.label}” "
                              "(enhancements stay)", checked=True)
        return Button(tip=f"Enhance every image in “{leaf.label}”, and each new one that arrives",
                      checked=False)

    def enhancing(self, key: str) -> bool:
        return (self._host.folder_meta().get(key) or {}).get("enhance_after_id") is not None

    def set_favorite(self, key: str, favorite: bool) -> bool:
        meta = self._host.folder_meta()
        if bool(meta.get(key, {}).get("starred")) == favorite:
            return False
        after_id = self._host.highest_id_listed() if favorite else None
        self._db.set_folder_favorite(key, favorite, after_id=after_id)
        meta[key] = {**meta.get(key, _NEVER_SWITCHED), "starred": favorite,
                     "favorite_after_id": after_id}
        return True

    def star_what_is_in(self, key: str) -> None:
        self._host.set_items_favorite(
            [row["prompt_id"] for row in self._host.leaf_folders().get(key, [])
             if not row.get("starred")], True)

    def set_enhancing(self, key: str, on: bool) -> None:
        after_id = self._host.highest_id_listed() if on else None
        self._db.set_folder_enhance(key, after_id=after_id)
        self._host.folder_meta().setdefault(key, dict(_NEVER_SWITCHED))[
            "enhance_after_id"] = after_id
        if on:
            self._enhance.enhance_what_awaits(self._host.leaf_folders().get(key, []))

    def take_in_the_arrivals(self) -> None:
        meta = self._host.folder_meta()
        switched_on = {key for key, held in meta.items()
                       if held.get("enhance_after_id") is not None
                       or (held.get("starred") and (held.get("favorite_after_id") is not None
                                                    or self._takes_up_older_stars))}
        if not switched_on:
            return
        leaves = {key: rows for key, rows in self._host.leaf_folders().items()
                  if key in switched_on}
        found = arrivals_in(leaves, meta, would_enhance=self._enhance.would_enhance,
                            older_stars=self._takes_up_older_stars)
        for key, (favorite_after_id, enhance_after_id) in found.marks.items():
            self._db.move_folder_arrivals_on(key, favorite_after_id=favorite_after_id,
                                             enhance_after_id=enhance_after_id)
            meta[key].update(favorite_after_id=favorite_after_id,
                             enhance_after_id=enhance_after_id)
        if found.to_star:
            self._host.set_items_favorite(found.to_star, True)
        if found.to_enhance:
            self._enhance.enhance_items([row["prompt_id"] for row in found.to_enhance])
