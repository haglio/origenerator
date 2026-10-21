from __future__ import annotations

from origenerator.db_connection import Store


class CombineVideoUseStore(Store):
    def record_combine_video_use(self, intent: str, video_prompt_id: str,
                                 generation_prompt_id: str | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO combine_video_uses (intent, video_prompt_id, generation_prompt_id)"
                " VALUES (?, ?, ?)",
                (intent, video_prompt_id, generation_prompt_id),
            )

    def repoint_combine_video_uses(self, gone: str, stays: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE combine_video_uses SET video_prompt_id = ?"
                         " WHERE video_prompt_id = ?", (stays, gone))

    def list_combine_video_uses(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT intent, video_prompt_id, generation_prompt_id, created_at"
                " FROM combine_video_uses ORDER BY id DESC"
            ).fetchall()
            return [dict(r) for r in rows]
