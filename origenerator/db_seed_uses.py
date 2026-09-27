from __future__ import annotations

from origenerator.db_connection import Store


class SeedUseStore(Store):
    def record_seed_use(self, *, kind: str, seed_key: str, seed: int,
                        width: int | None = None, height: int | None = None,
                        thumbnail_path: str | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO seed_uses (kind, seed_key, seed, width, height, thumbnail_path)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (kind, seed_key, seed, width, height, thumbnail_path),
            )

    def list_seed_uses(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT kind, seed_key, seed, width, height, thumbnail_path, created_at"
                " FROM seed_uses ORDER BY id DESC"
            ).fetchall()
            return [dict(r) for r in rows]
