from __future__ import annotations

from dataclasses import dataclass

from origenerator.db_connection import Store


@dataclass(frozen=True, kw_only=True)
class NewRequest:
    prompt_id: str
    source_prompt_id: str
    heard: str
    term: str | None = None
    polarity: str | None = None
    action: str | None = None
    old_positive: str = ""
    old_negative: str = ""
    new_positive: str = ""
    new_negative: str = ""
    asked: str | None = None


class RequestStore(Store):
    def record_request(self, request: NewRequest):
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO requests
                       (prompt_id, source_prompt_id, heard, term, polarity, action,
                        old_positive, old_negative, new_positive, new_negative, asked)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (request.prompt_id, request.source_prompt_id, request.heard, request.term,
                 request.polarity, request.action, request.old_positive, request.old_negative,
                 request.new_positive, request.new_negative, request.asked),
            )

    def list_requests(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM requests ORDER BY created_at DESC, rowid DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def requests_about(self, source_prompt_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM requests WHERE source_prompt_id = ?"
                " ORDER BY created_at DESC, rowid DESC", (source_prompt_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_request(self, prompt_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM requests WHERE prompt_id = ?", (prompt_id,)
            ).fetchone()
            return dict(row) if row else None
