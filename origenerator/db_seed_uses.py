from __future__ import annotations

from origenerator.db_connection import Store
from origenerator.media import MediaType

_SOUND_SEED = "audio_seed"


def give_old_seed_uses_their_kind(conn) -> None:
    conn.execute(
        "UPDATE seed_uses SET media_type = ? WHERE media_type IS NULL AND (seed_key = ?"
        " OR EXISTS (SELECT 1 FROM seed_uses AS sound WHERE sound.seed_key = ?"
        " AND sound.kind = seed_uses.kind AND ABS(strftime('%s', sound.created_at)"
        " - strftime('%s', seed_uses.created_at)) <= 1))",
        (MediaType.VIDEO, _SOUND_SEED, _SOUND_SEED))
    conn.execute("UPDATE seed_uses SET media_type = ? WHERE media_type IS NULL",
                 (MediaType.IMAGE,))


class SeedUseStore(Store):
    def record_seed_use(self, *, kind: str, seed_key: str, seed: int, media_type: str,
                        width: int | None = None, height: int | None = None,
                        thumbnail_path: str | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO seed_uses"
                " (kind, seed_key, seed, media_type, width, height, thumbnail_path)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (kind, seed_key, seed, media_type, width, height, thumbnail_path),
            )

    def list_seed_uses(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT kind, seed_key, seed, media_type, width, height, thumbnail_path,"
                " created_at"
                " FROM seed_uses ORDER BY id DESC"
            ).fetchall()
            return [dict(r) for r in rows]
