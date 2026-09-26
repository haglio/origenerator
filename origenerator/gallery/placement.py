from __future__ import annotations

from collections import Counter

from origenerator.gallery.groups import child_groups
from origenerator.gallery.output import produced_output
from origenerator.gallery.tree import ALL_KEY, folder_chain


class Placement:
    def __init__(self, library, image_index: dict):
        self._image_index = image_index
        self._placed: dict[str, tuple[str, ...]] = {}
        self._loose: dict[str, tuple[str, ...]] = {}
        self._folders: dict = {}
        self._place(library, ())

    def _place(self, folder, above: tuple[str, ...]) -> None:
        chain = (*above, folder.key)
        self._folders[folder.key] = folder
        for row in getattr(folder, "rows", ()):
            self._placed[row["prompt_id"]] = chain
        for child in child_groups(folder):
            self._place(child, chain)

    def folder(self, key: str):
        return self._folders.get(key)

    def chain(self, row: dict) -> tuple[str, ...]:
        prompt_id = row["prompt_id"]
        chain = self._placed.get(prompt_id) or self._loose.get(prompt_id)
        if chain is None:
            chain = self._loose[prompt_id] = folder_chain(row, self._image_index)
        return chain

    def holds(self, folder_key: str, prompt_id: str) -> bool:
        return folder_key == ALL_KEY or folder_key in self._placed.get(prompt_id, ())

    def held_by(self, folder_key: str, rows) -> list[dict]:
        if folder_key == ALL_KEY:
            return list(rows)
        return [row for row in rows if folder_key in self.chain(row)]

    def tally(self, rows) -> Counter:
        return Counter(key for row in rows for key in self.chain(row))

    def tally_favorites(self, rows) -> Counter:
        favorite_keys = {key for key, folder in self._folders.items() if folder.favorite}
        tally = Counter()
        for row in rows:
            if row.get("starred") and produced_output(row):
                tally.update(self.chain(row))
                continue
            placed = self._placed.get(row["prompt_id"], ())
            deepest = max((depth for depth, key in enumerate(placed) if key in favorite_keys),
                          default=0)
            tally.update(placed[:deepest])
        return tally
