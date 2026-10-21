from __future__ import annotations

import bisect
from datetime import datetime, timedelta

from origenerator.db_connection import Store
from origenerator.media import MediaType

_SOUND_SEED = "audio_seed"
_A_TABS_PICK_FOR_ITS_NEXT_PRESS = timedelta(seconds=5)


def give_old_seed_uses_their_kind(conn) -> None:
    conn.execute(
        "UPDATE seed_uses SET media_type = ? WHERE media_type IS NULL AND (seed_key = ?"
        " OR EXISTS (SELECT 1 FROM seed_uses AS sound WHERE sound.seed_key = ?"
        " AND sound.kind = seed_uses.kind AND ABS(strftime('%s', sound.created_at)"
        " - strftime('%s', seed_uses.created_at)) <= 1))",
        (MediaType.VIDEO, _SOUND_SEED, _SOUND_SEED))
    conn.execute("UPDATE seed_uses SET media_type = ? WHERE media_type IS NULL",
                 (MediaType.IMAGE,))


def forget_the_seeds_tabs_picked_for_their_next_press(conn) -> None:
    presses = sorted(datetime.fromisoformat(at) for (at,) in conn.execute(
        "SELECT created_at FROM generations WHERE created_at IS NOT NULL"
        " UNION ALL SELECT json_extract(row_json, '$.created_at') FROM deletions"
        " WHERE json_extract(row_json, '$.created_at') IS NOT NULL"))
    picked = [(use_id,) for use_id, at in conn.execute(
        "SELECT id, created_at FROM seed_uses WHERE kind = 'drawn'")
        if _just_after_a_press(datetime.fromisoformat(at), presses)]
    conn.executemany("DELETE FROM seed_uses WHERE id = ?", picked)


def _just_after_a_press(at: datetime, presses: list[datetime]) -> bool:
    last = bisect.bisect_right(presses, at)
    return last > 0 and at - presses[last - 1] <= _A_TABS_PICK_FOR_ITS_NEXT_PRESS


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
