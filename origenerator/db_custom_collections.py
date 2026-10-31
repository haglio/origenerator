"""The folders the user composes by hand, and what each one gathers.

`custom_folders` is the name, `custom_folder_items` the folders it gathers and
`custom_folder_generations` the items it holds on their own (see
origenerator.gallery.custom). A custom collection holds references, not copies -- what
it gathers outlives it.

A gathered folder is stored by tree key, so it drifts when a key formula moves
exactly as a `folder_meta` favorite does, and carries the same identity columns for
the same reason: `origenerator.favorite_reconcile` re-points it from a generation
under it.
"""
from __future__ import annotations

from origenerator.db_connection import Store


class CustomCollectionStore(Store):
    """The queries over `custom_folders` and `custom_folder_items`."""

    def create_custom_collection(self, name: str, folder_id: int | None = None,
                             side: str | None = None) -> int:
        """Make an empty custom collection and return its id.

        ``folder_id`` re-creates one at the id it had, so an undone removal comes
        back under the very key the session was saved with (see
        :meth:`GalleryActions.delete_custom_collection`)."""
        with self._connect() as conn:
            cur = conn.execute("INSERT INTO custom_folders (id, name, side) VALUES (?, ?, ?)",
                               (folder_id, name, side))
            return int(cur.lastrowid)

    def set_custom_collection_shape(self, folder_id: int, side: str):
        with self._connect() as conn:
            conn.execute("UPDATE custom_folders SET side = ? WHERE id = ?",
                         (side, folder_id))

    def delete_custom_collection(self, folder_id: int):
        """Drop a custom collection and everything it holds. The gathered folders and
        their generations are untouched — it holds references, not copies."""
        with self._connect() as conn:
            for table in ("custom_folder_items", "custom_folder_generations"):
                conn.execute(f"DELETE FROM {table} WHERE folder_id = ?", (folder_id,))
            conn.execute("DELETE FROM custom_folders WHERE id = ?", (folder_id,))

    def add_folders_to_custom_collection(self, folder_id: int, folders: list[tuple]):
        """Add ``(folder_key, level, ref_prompt_id)`` folders to a custom collection,
        appended after whatever it already holds. A key already in the folder keeps
        its position and refreshes its identity, so re-dropping a folder is a no-op
        rather than a duplicate."""
        if not folders:
            return
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(position), -1) FROM custom_folder_items "
                "WHERE folder_id = ?", (folder_id,)
            ).fetchone()
            position = int(row[0]) + 1
            for folder_key, level, ref_prompt_id in folders:
                conn.execute(
                    """INSERT INTO custom_folder_items
                           (folder_id, folder_key, level, ref_prompt_id, position)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(folder_id, folder_key) DO UPDATE SET
                           level = excluded.level,
                           ref_prompt_id = excluded.ref_prompt_id""",
                    (folder_id, folder_key, level, ref_prompt_id, position),
                )
                position += 1

    def add_items_to_custom_collection(self, folder_id: int, prompt_ids: list[str]):
        with self._connect() as conn:
            (last,) = conn.execute(
                "SELECT COALESCE(MAX(position), -1) FROM custom_folder_generations "
                "WHERE folder_id = ?", (folder_id,)
            ).fetchone()
            for position, prompt_id in enumerate(prompt_ids, start=int(last) + 1):
                conn.execute(
                    "INSERT OR IGNORE INTO custom_folder_generations "
                    "(folder_id, prompt_id, position) "
                    "VALUES (?, ?, ?)", (folder_id, prompt_id, position),
                )

    def remove_items_from_custom_collection(self, folder_id: int, prompt_ids: list[str]):
        with self._connect() as conn:
            conn.executemany(
                "DELETE FROM custom_folder_generations WHERE folder_id = ? AND prompt_id = ?",
                [(folder_id, prompt_id) for prompt_id in prompt_ids],
            )

    def repoint_item_in_custom_collections(self, old_prompt_id: str, new_prompt_id: str):
        with self._connect() as conn:
            conn.execute(
                "UPDATE OR IGNORE custom_folder_generations SET prompt_id = ? "
                "WHERE prompt_id = ?", (new_prompt_id, old_prompt_id),
            )
            conn.execute("DELETE FROM custom_folder_generations WHERE prompt_id = ?",
                         (old_prompt_id,))

    def remove_folder_from_custom_collection(self, folder_id: int, folder_key: str):
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM custom_folder_items WHERE folder_id = ? AND folder_key = ?",
                (folder_id, folder_key),
            )

    def list_custom_collections(self) -> list[dict]:
        """Every custom collection as ``{"id", "name", "side", "folders": [folder_key, ...]}``,
        oldest first, each folder list in the order it was built up."""
        with self._connect() as conn:
            folders = [
                {"id": r["id"], "name": r["name"], "side": r["side"], "folders": [],
                 "items": []}
                for r in conn.execute(
                    "SELECT id, name, side FROM custom_folders ORDER BY id"
                )
            ]
            by_id = {f["id"]: f for f in folders}
            for r in conn.execute(
                "SELECT folder_id, folder_key FROM custom_folder_items "
                "ORDER BY folder_id, position, rowid"
            ):
                folder = by_id.get(r["folder_id"])
                if folder is not None:
                    folder["folders"].append(r["folder_key"])
            for r in conn.execute(
                "SELECT folder_id, prompt_id FROM custom_folder_generations "
                "ORDER BY folder_id, position, rowid"
            ):
                folder = by_id.get(r["folder_id"])
                if folder is not None:
                    folder["items"].append(r["prompt_id"])
            return folders

    def folders_in_custom_collections(self) -> list[dict]:
        """Every gathered folder with its stored identity, for the reconcile."""
        with self._connect() as conn:
            return [
                {"folder_id": r["folder_id"], "folder_key": r["folder_key"],
                 "level": r["level"], "ref_prompt_id": r["ref_prompt_id"]}
                for r in conn.execute(
                    "SELECT folder_id, folder_key, level, ref_prompt_id "
                    "FROM custom_folder_items"
                )
            ]

    def repoint_folder_in_custom_collection(self, folder_id: int, old_key: str, new_key: str,
                                        *, level: str | None, ref_prompt_id: str | None):
        """Move a gathered folder onto ``new_key``, keeping its place.

        Used by the reconcile when a gathered folder's key drifts. If the folder
        already holds ``new_key`` the stale row is simply dropped — the grouping
        already contains that folder once, which is all it can mean.
        """
        with self._connect() as conn:
            held = conn.execute(
                "SELECT position FROM custom_folder_items "
                "WHERE folder_id = ? AND folder_key = ?", (folder_id, old_key)
            ).fetchone()
            position = int(held["position"]) if held is not None else 0
            conn.execute(
                "DELETE FROM custom_folder_items WHERE folder_id = ? AND folder_key = ?",
                (folder_id, old_key),
            )
            conn.execute(
                """INSERT INTO custom_folder_items
                       (folder_id, folder_key, level, ref_prompt_id, position)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(folder_id, folder_key) DO UPDATE SET
                       level = excluded.level,
                       ref_prompt_id = excluded.ref_prompt_id""",
                (folder_id, new_key, level, ref_prompt_id, position),
            )

    def stamp_folder_in_custom_collection(self, folder_id: int, folder_key: str,
                                      *, level: str | None, ref_prompt_id: str | None):
        """Refresh a gathered folder's stored identity, so a future key formula
        change can re-derive it from a generation under it."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE custom_folder_items SET level = ?, ref_prompt_id = ? "
                "WHERE folder_id = ? AND folder_key = ?",
                (level, ref_prompt_id, folder_id, folder_key),
            )
