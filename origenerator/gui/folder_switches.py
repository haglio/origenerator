from __future__ import annotations

from typing import Protocol

from origenerator import gallery
from origenerator.branch_session import is_branch_session
from origenerator.folder_arrivals import arrivals_in
from origenerator.gui.enhance_controller import NO_VIDEO_ENHANCER, all_video
from origenerator.gui.gallery_pane_buttons import Button
from origenerator.item_shape import split_key

ONLY_A_LEAF_IS_FAVORITED = "Only a leaf folder can be favorited"
ONLY_A_LEAF_IS_ENHANCED = "Only a leaf folder can be enhanced as a whole"
_NEVER_SWITCHED = {"custom_name": None, "starred": False}


class FolderSwitchesHost(Protocol):
    def open_leaf_folder(self) -> gallery.SettingsGroup | None: ...

    def set_items_favorite(self, prompt_ids, favorite: bool) -> None: ...

    def enhance_offer_changed(self) -> None: ...


class FolderSwitches:
    def __init__(self, host: FolderSwitchesHost, db, enhance, *, library):
        self._host = host
        self._db = db
        self._library = library
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
            held = self.enhance_settings_of(leaf.key)
            return Button(tip=f"Stop enhancing new images in “{leaf.label}” "
                              "(enhancements stay)\nEnhancing at "
                              f"{gallery.describe_enhance_params(held.params)}", checked=True)
        return Button(tip=f"Enhance every image in “{leaf.label}”, and each new one that arrives",
                      checked=False)

    def enhancing(self, key: str) -> bool:
        return (self._library.folder_meta.get(key) or {}).get("enhance_after_id") is not None

    def set_favorite(self, key: str, favorite: bool) -> bool:
        meta = self._library.folder_meta
        if bool(meta.get(key, {}).get("starred")) == favorite:
            return False
        after_id = self._library.reading.highest_id if favorite else None
        self._db.set_folder_favorite(key, favorite, after_id=after_id)
        meta[key] = {**meta.get(key, _NEVER_SWITCHED), "starred": favorite,
                     "favorite_after_id": after_id}
        return True

    def star_what_is_in(self, key: str) -> None:
        self._host.set_items_favorite(
            [row["prompt_id"] for row in self._library.leaf_folders().get(key, [])
             if not row.get("starred")], True)

    def set_enhancing(self, key: str, on: bool,
                      settings: gallery.EnhanceSettings | None = None) -> None:
        after_id = self._library.reading.highest_id if on else None
        settings = (settings or self._enhance.settings) if on else None
        self._keep_enhance(key, after_id, settings)
        if on:
            self._enhance.enhance_what_awaits(self._library.leaf_folders().get(key, []),
                                              settings)

    def _keep_enhance(self, key: str, after_id: int | None,
                      settings: gallery.EnhanceSettings | None) -> None:
        kept = None if settings is None else gallery.EnhanceSettings(
            params=settings.params).to_json()
        self._db.set_folder_enhance(key, after_id=after_id, settings=kept)
        self._library.folder_meta.setdefault(key, dict(_NEVER_SWITCHED)).update(
            enhance_after_id=after_id, enhance_settings=kept)

    def enhance_settings_of(self, key: str) -> gallery.EnhanceSettings | None:
        held = self._library.folder_meta.get(key) or {}
        if held.get("enhance_after_id") is None:
            return None
        kept = held.get("enhance_settings")
        return gallery.EnhanceSettings.parse(kept) if kept else self._enhance.settings

    def enhance_params_of_the_open_folder(self) -> dict | None:
        leaf = self._host.open_leaf_folder()
        held = None if leaf is None else self.enhance_settings_of(leaf.key)
        return None if held is None else held.params

    def the_open_folder_takes_enhance_settings(self) -> bool:
        return self.enhance_switch().enabled

    def keep_enhance_params_of_the_open_folder(self, params: dict) -> None:
        key = self._host.open_leaf_folder().key
        settings = gallery.EnhanceSettings(params=gallery.full_settings(params))
        if self.enhancing(key):
            self._keep_enhance(key, self._library.folder_meta[key]["enhance_after_id"], settings)
        else:
            self.set_enhancing(key, True, settings)
        self._host.enhance_offer_changed()

    def enhance_params_of_the_one_enhancing(self, toc_keys: list[str]) -> dict | None:
        held = [settings for toc_key in toc_keys
                if (settings := self.enhance_settings_of(split_key(toc_key)[0]))]
        return held[0].params if len(held) == 1 else None

    def keep_the_settings_of_folders_switched_on_before_settings_were_kept(self) -> None:
        meta = self._library.folder_meta
        for key, held in meta.items():
            if held.get("enhance_after_id") is not None and not held.get("enhance_settings"):
                self._keep_enhance(key, held["enhance_after_id"], self._enhance.settings)

    def take_in_the_arrivals(self) -> None:
        meta = self._library.folder_meta
        switched_on = {key for key, held in meta.items()
                       if held.get("enhance_after_id") is not None
                       or (held.get("starred") and (held.get("favorite_after_id") is not None
                                                    or self._takes_up_older_stars))}
        if not switched_on:
            return
        leaves = {key: rows for key, rows in self._library.leaf_folders().items()
                  if key in switched_on}
        found = arrivals_in(
            leaves, meta, older_stars=self._takes_up_older_stars,
            would_enhance=lambda key, row: self._enhance.would_enhance(
                row, self.enhance_settings_of(key)))
        for key, (favorite_after_id, enhance_after_id) in found.marks.items():
            self._db.move_folder_arrivals_on(key, favorite_after_id=favorite_after_id,
                                             enhance_after_id=enhance_after_id)
            meta[key].update(favorite_after_id=favorite_after_id,
                             enhance_after_id=enhance_after_id)
        if found.to_star:
            self._host.set_items_favorite(found.to_star, True)
        for key, rows in found.to_enhance.items():
            self._enhance.enhance_rows(rows, self.enhance_settings_of(key))
