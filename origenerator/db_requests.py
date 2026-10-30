"""A request and the generation it queued.

One of the six tables `Database` used to hold all of. The only record of why one
generation differs from the one it came from: the item it was made about, what
was heard, and the prompt pair before the edit (the pair after it is the queued
generation's own params).

Kept even when its generation goes -- a delete here is undoable, and a restored
item should come back with the request that made it.

A request records one, and so does a folder's Modify (all seeds), which rewrites
every image in a folder at once and records one per image, linking each
result to the one it was rewritten from. A Modify has nothing heard and no single
term -- it says what it wanted by rewriting the prompt, which the old/new pair
holds -- so `heard` is empty there and `term`/`polarity`/`action` are unset.
"""
from __future__ import annotations

from typing import NamedTuple

from origenerator.db_connection import Store


class Turn(NamedTuple):
    """One turn of the exchange that led to an item: what was asked, what the
    model answered, and the prompt pair before and after it."""

    said: str
    answered: str = ""
    old_positive: str = ""
    old_negative: str = ""
    new_positive: str = ""
    new_negative: str = ""


class RequestStore(Store):
    """The four queries over the `requests` table."""

    def record_request(self, *, prompt_id: str, source_prompt_id: str, heard: str,
                       term: str | None = None, polarity: str | None = None,
                       action: str | None = None, old_positive: str = "",
                       old_negative: str = "", new_positive: str = "",
                       new_negative: str = "", asked: str | None = None):
        """Record that ``prompt_id`` was queued by a request about
        ``source_prompt_id`` — spoken, or typed as one image of a folder-wide
        rewrite, which leaves ``heard`` empty. Replaces any earlier record for
        the same generation, which only a re-used prompt id could produce."""
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO requests
                       (prompt_id, source_prompt_id, heard, term, polarity, action,
                        old_positive, old_negative, new_positive, new_negative, asked)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (prompt_id, source_prompt_id, heard, term, polarity, action,
                 old_positive, old_negative, new_positive, new_negative, asked),
            )

    def list_requests(self) -> list[dict]:
        """Every recorded request, newest first.

        The stamp has second resolution, so requests made in one burst tie; the
        rowid breaks it, keeping them in the order they were spoken.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM requests ORDER BY created_at DESC, rowid DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def requests_about(self, source_prompt_id: str) -> list[dict]:
        """Every request made of this generation, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM requests WHERE source_prompt_id = ?"
                " ORDER BY created_at DESC, rowid DESC", (source_prompt_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_request(self, prompt_id: str) -> dict | None:
        """The request that queued this generation, or ``None`` if none did."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM requests WHERE prompt_id = ?", (prompt_id,)
            ).fetchone()
            return dict(row) if row else None

    def record_turns(self, prompt_id: str, turns) -> None:
        with self._connect() as conn:
            conn.executemany(
                """INSERT INTO request_turns
                       (prompt_id, said, answered, old_positive, old_negative,
                        new_positive, new_negative)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [(prompt_id, *Turn(*turn)) for turn in turns])

    def turns_of(self, prompt_id: str) -> list[Turn]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT said, answered, old_positive, old_negative, new_positive, new_negative
                   FROM request_turns WHERE prompt_id = ? ORDER BY id""", (prompt_id,)).fetchall()
            return [Turn(*row) for row in rows]

    def exchange_of(self, prompt_id: str) -> list[Turn]:
        """Every turn along the way to this item, oldest first: those of the item
        it was requested from, and theirs before, then its own."""
        exchange: list[Turn] = []
        seen: set[str] = set()
        current: str | None = prompt_id
        while current and current not in seen:
            seen.add(current)
            exchange = self.turns_of(current) + exchange
            request = self.get_request(current)
            current = request["source_prompt_id"] if request else None
        return exchange
