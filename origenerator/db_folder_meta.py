from __future__ import annotations

from origenerator.db_connection import Store
from origenerator.folder_switch_fields import SWITCH_KEYS

_SWITCHES = ", ".join(SWITCH_KEYS)


def _switches(r) -> dict:
    return {key: r[key] for key in SWITCH_KEYS}


class FolderMetaStore(Store):
    def folder_meta_map(self) -> dict[str, dict]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT folder_key, custom_name, starred, {_SWITCHES} FROM folder_meta"
            ).fetchall()
        return {
            r["folder_key"]: {
                "custom_name": r["custom_name"],
                "starred": bool(r["starred"]),
                **_switches(r),
            }
            for r in rows
        }

    def set_folder_favorite(self, folder_key: str, favorite: bool, *,
                            after_id: int | None = None):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO folder_meta (folder_key, starred, favorite_after_id)
                   VALUES (?, ?, ?)
                   ON CONFLICT(folder_key)
                   DO UPDATE SET starred = excluded.starred,
                                 favorite_after_id = excluded.favorite_after_id""",
                (folder_key, 1 if favorite else 0, after_id if favorite else None),
            )

    def set_folder_enhance(self, folder_key: str, *, after_id: int | None,
                           settings: str | None = None):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO folder_meta (folder_key, enhance_after_id, enhance_settings)
                   VALUES (?, ?, ?)
                   ON CONFLICT(folder_key)
                   DO UPDATE SET enhance_after_id = excluded.enhance_after_id,
                                 enhance_settings = excluded.enhance_settings""",
                (folder_key, after_id, settings),
            )

    def move_folder_arrivals_on(self, folder_key: str, *, favorite_after_id: int | None,
                                enhance_after_id: int | None):
        with self._connect() as conn:
            conn.execute(
                "UPDATE folder_meta SET favorite_after_id = ?, enhance_after_id = ? "
                "WHERE folder_key = ?",
                (favorite_after_id, enhance_after_id, folder_key),
            )

    def folder_meta_full(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT folder_key, custom_name, starred, level, ref_prompt_id, "
                f"{_SWITCHES} FROM folder_meta"
            ).fetchall()
        return [
            {
                "folder_key": r["folder_key"],
                "custom_name": r["custom_name"],
                "starred": bool(r["starred"]),
                "level": r["level"],
                "ref_prompt_id": r["ref_prompt_id"],
                **_switches(r),
            }
            for r in rows
        ]

    def upsert_folder_meta(self, folder_key: str, *, custom_name: str | None,
                           favorite: bool, level: str | None, ref_prompt_id: str | None,
                           favorite_after_id: int | None = None,
                           enhance_after_id: int | None = None,
                           enhance_settings: str | None = None):
        with self._connect() as conn:
            conn.execute(
                f"""INSERT INTO folder_meta
                       (folder_key, custom_name, starred, level, ref_prompt_id, {_SWITCHES})
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(folder_key) DO UPDATE SET
                       custom_name = excluded.custom_name,
                       starred = excluded.starred,
                       level = excluded.level,
                       ref_prompt_id = excluded.ref_prompt_id,
                       favorite_after_id = excluded.favorite_after_id,
                       enhance_after_id = excluded.enhance_after_id,
                       enhance_settings = excluded.enhance_settings""",
                (folder_key, custom_name, 1 if favorite else 0, level, ref_prompt_id,
                 favorite_after_id, enhance_after_id, enhance_settings),
            )

    def delete_folder_meta(self, folder_key: str):
        with self._connect() as conn:
            conn.execute("DELETE FROM folder_meta WHERE folder_key = ?", (folder_key,))
