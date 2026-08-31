"""The folders the user composes by hand, and what each one gathers.

Two of the six tables `Database` used to hold all of, and they are one concern:
`custom_folders` is the name, `custom_folder_members` is everything under it (see
origenerator.gallery.custom). A custom folder holds references, not items -- the
gathered folders and their generations outlive it.

Membership is by tree key, so it drifts when a key formula moves exactly as a
`folder_meta` bookmark does, and carries the same identity columns for the same
reason: `origenerator.bookmark_reconcile` re-points it from a member generation.
"""
from origenerator.db_connection import Store


class CustomFolderStore(Store):
    """The nine queries over `custom_folders` and `custom_folder_members`."""

    def create_custom_folder(self, name: str, folder_id: int | None = None) -> int:
        """Make an empty custom folder and return its id.

        ``folder_id`` re-creates one at the id it had, so an undone removal comes
        back under the very key the session was saved with (see
        :meth:`GalleryActions.delete_custom_folder`)."""
        with self._connect() as conn:
            if folder_id is None:
                cur = conn.execute("INSERT INTO custom_folders (name) VALUES (?)", (name,))
                return int(cur.lastrowid)
            conn.execute("INSERT INTO custom_folders (id, name) VALUES (?, ?)",
                         (folder_id, name))
            return int(folder_id)

    def rename_custom_folder(self, folder_id: int, name: str):
        with self._connect() as conn:
            conn.execute("UPDATE custom_folders SET name = ? WHERE id = ?",
                         (name, folder_id))

    def delete_custom_folder(self, folder_id: int):
        """Drop a custom folder and its membership. The gathered folders and their
        generations are untouched — a custom folder holds references, not items."""
        with self._connect() as conn:
            conn.execute("DELETE FROM custom_folder_members WHERE folder_id = ?",
                         (folder_id,))
            conn.execute("DELETE FROM custom_folders WHERE id = ?", (folder_id,))

    def add_custom_folder_members(self, folder_id: int, members: list[tuple]):
        """Add ``(folder_key, level, ref_prompt_id)`` members to a custom folder,
        appended after whatever it already holds. A key already in the folder keeps
        its position and refreshes its identity, so re-dropping a folder is a no-op
        rather than a duplicate."""
        if not members:
            return
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(position), -1) FROM custom_folder_members "
                "WHERE folder_id = ?", (folder_id,)
            ).fetchone()
            position = int(row[0]) + 1
            for folder_key, level, ref_prompt_id in members:
                conn.execute(
                    """INSERT INTO custom_folder_members
                           (folder_id, folder_key, level, ref_prompt_id, position)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(folder_id, folder_key) DO UPDATE SET
                           level = excluded.level,
                           ref_prompt_id = excluded.ref_prompt_id""",
                    (folder_id, folder_key, level, ref_prompt_id, position),
                )
                position += 1

    def remove_custom_folder_member(self, folder_id: int, folder_key: str):
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM custom_folder_members WHERE folder_id = ? AND folder_key = ?",
                (folder_id, folder_key),
            )

    def list_custom_folders(self) -> list[dict]:
        """Every custom folder as ``{"id", "name", "members": [folder_key, ...]}``,
        oldest first, each member list in the order it was built up."""
        with self._connect() as conn:
            folders = [
                {"id": r["id"], "name": r["name"], "members": []}
                for r in conn.execute(
                    "SELECT id, name FROM custom_folders ORDER BY id"
                )
            ]
            by_id = {f["id"]: f for f in folders}
            for r in conn.execute(
                "SELECT folder_id, folder_key FROM custom_folder_members "
                "ORDER BY folder_id, position, rowid"
            ):
                folder = by_id.get(r["folder_id"])
                if folder is not None:
                    folder["members"].append(r["folder_key"])
            return folders

    def custom_folder_members_full(self) -> list[dict]:
        """Every membership row with its stored identity, for the reconcile."""
        with self._connect() as conn:
            return [
                {"folder_id": r["folder_id"], "folder_key": r["folder_key"],
                 "level": r["level"], "ref_prompt_id": r["ref_prompt_id"]}
                for r in conn.execute(
                    "SELECT folder_id, folder_key, level, ref_prompt_id "
                    "FROM custom_folder_members"
                )
            ]

    def repoint_custom_folder_member(self, folder_id: int, old_key: str, new_key: str,
                                     *, level: str | None, ref_prompt_id: str | None):
        """Move a membership onto ``new_key``, keeping its place in the folder.

        Used by the reconcile when a member's folder key drifts. If the folder
        already holds ``new_key`` the stale row is simply dropped — the grouping
        already contains that folder once, which is all it can mean.
        """
        with self._connect() as conn:
            held = conn.execute(
                "SELECT position FROM custom_folder_members "
                "WHERE folder_id = ? AND folder_key = ?", (folder_id, old_key)
            ).fetchone()
            position = int(held["position"]) if held is not None else 0
            conn.execute(
                "DELETE FROM custom_folder_members WHERE folder_id = ? AND folder_key = ?",
                (folder_id, old_key),
            )
            conn.execute(
                """INSERT INTO custom_folder_members
                       (folder_id, folder_key, level, ref_prompt_id, position)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(folder_id, folder_key) DO UPDATE SET
                       level = excluded.level,
                       ref_prompt_id = excluded.ref_prompt_id""",
                (folder_id, new_key, level, ref_prompt_id, position),
            )

    def stamp_custom_folder_member(self, folder_id: int, folder_key: str,
                                   *, level: str | None, ref_prompt_id: str | None):
        """Refresh a live membership's stored identity, so a future key formula
        change can re-derive it from a member generation."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE custom_folder_members SET level = ?, ref_prompt_id = ? "
                "WHERE folder_id = ? AND folder_key = ?",
                (level, ref_prompt_id, folder_id, folder_key),
            )
