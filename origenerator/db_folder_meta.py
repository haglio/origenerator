"""A gallery folder's bookmark: the name the user gave it, and its star.

One of the six tables `Database` used to hold all of. `origenerator.bookmark_reconcile`
and the gallery tree are its readers.

A folder here is a tree key, which is derived rather than stored -- so a bookmark
also carries the identity it can be re-derived from, the tier it sits at and one
member generation, and the reconcile re-points it when the key formula moves.
`folder_meta_map` is the view's half (labels and stars); `folder_meta_full` is
the reconcile's, and adds those two identity columns.
"""
from origenerator.db_connection import Store


class FolderMetaStore(Store):
    """The six queries over the `folder_meta` table."""

    def folder_meta_map(self) -> dict[str, dict]:
        """Return ``{folder_key: {"custom_name": str|None, "starred": bool}}``."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT folder_key, custom_name, starred FROM folder_meta"
            ).fetchall()
        return {
            r["folder_key"]: {
                "custom_name": r["custom_name"],
                "starred": bool(r["starred"]),
            }
            for r in rows
        }

    def rename_folder(self, folder_key: str, custom_name: str | None):
        """Set (or clear, when ``None``) a folder's custom display name."""
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO folder_meta (folder_key, custom_name)
                   VALUES (?, ?)
                   ON CONFLICT(folder_key)
                   DO UPDATE SET custom_name = excluded.custom_name""",
                (folder_key, custom_name),
            )

    def set_folder_starred(self, folder_key: str, starred: bool):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO folder_meta (folder_key, starred)
                   VALUES (?, ?)
                   ON CONFLICT(folder_key)
                   DO UPDATE SET starred = excluded.starred""",
                (folder_key, 1 if starred else 0),
            )

    def folder_meta_full(self) -> list[dict]:
        """Every folder_meta row with its bookmark identity, for the reconcile.

        Unlike :meth:`folder_meta_map` (which the view uses for labels/stars), this
        also carries ``level`` and ``ref_prompt_id`` so a stale key can be re-derived.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT folder_key, custom_name, starred, level, ref_prompt_id "
                "FROM folder_meta"
            ).fetchall()
        return [
            {
                "folder_key": r["folder_key"],
                "custom_name": r["custom_name"],
                "starred": bool(r["starred"]),
                "level": r["level"],
                "ref_prompt_id": r["ref_prompt_id"],
            }
            for r in rows
        ]

    def upsert_folder_meta(self, folder_key: str, *, custom_name: str | None,
                           starred: bool, level: str | None, ref_prompt_id: str | None):
        """Write a folder_meta row in full — the reconcile's tool for re-pointing a
        bookmark onto a new key and for stamping identity onto a matched one."""
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO folder_meta
                       (folder_key, custom_name, starred, level, ref_prompt_id)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(folder_key) DO UPDATE SET
                       custom_name = excluded.custom_name,
                       starred = excluded.starred,
                       level = excluded.level,
                       ref_prompt_id = excluded.ref_prompt_id""",
                (folder_key, custom_name, 1 if starred else 0, level, ref_prompt_id),
            )

    def delete_folder_meta(self, folder_key: str):
        """Drop a folder_meta row — used to clear a bookmark's old key after the
        reconcile has re-pointed it onto its current one."""
        with self._connect() as conn:
            conn.execute("DELETE FROM folder_meta WHERE folder_key = ?", (folder_key,))
