from __future__ import annotations

from origenerator.db_connection import Store


class FolderMetaStore(Store):
    def folder_meta_map(self) -> dict[str, dict]:
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

    def set_folder_favorite(self, folder_key: str, favorite: bool):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO folder_meta (folder_key, starred)
                   VALUES (?, ?)
                   ON CONFLICT(folder_key)
                   DO UPDATE SET starred = excluded.starred""",
                (folder_key, 1 if favorite else 0),
            )

    def folder_meta_full(self) -> list[dict]:
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
                           favorite: bool, level: str | None, ref_prompt_id: str | None):
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
                (folder_key, custom_name, 1 if favorite else 0, level, ref_prompt_id),
            )

    def delete_folder_meta(self, folder_key: str):
        with self._connect() as conn:
            conn.execute("DELETE FROM folder_meta WHERE folder_key = ?", (folder_key,))
