"""A request and the generation it queued.

One of the six tables `Database` used to hold all of. What the Requests shelf
lists, and the only record of why one generation differs from the one it came
from: the item it was made about, what was heard, and the prompt pair before the
edit (the pair after it is the queued generation's own params).

Kept even when its generation goes -- a delete here is undoable, and a restored
item should come back with the request that made it, so the shelf skips a record
it cannot resolve rather than the record being dropped.

Spoken ("Request ... over") or typed: a folder rewrite asks the same thing of
every picture in a folder at once and records one of these per picture, which is
what links each result to the one it was rewritten from. Such a record has
nothing heard and no single term -- it says what it wanted by rewriting the
prompt, which the old/new pair holds -- so `heard` is empty there and
`term`/`polarity`/`action` are unset.
"""
from origenerator.db_connection import Store


class RequestStore(Store):
    """The three queries over the `requests` table."""

    def record_request(self, *, prompt_id: str, source_prompt_id: str, heard: str,
                       term: str | None = None, polarity: str | None = None,
                       action: str | None = None, old_positive: str = "",
                       old_negative: str = "", new_positive: str = "",
                       new_negative: str = ""):
        """Record that ``prompt_id`` was queued by a request about
        ``source_prompt_id`` — spoken, or typed as one picture of a folder-wide
        rewrite, which leaves ``heard`` empty. Replaces any earlier record for
        the same generation, which only a re-used prompt id could produce."""
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO requests
                       (prompt_id, source_prompt_id, heard, term, polarity, action,
                        old_positive, old_negative, new_positive, new_negative)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (prompt_id, source_prompt_id, heard, term, polarity, action,
                 old_positive, old_negative, new_positive, new_negative),
            )

    def list_requests(self) -> list[dict]:
        """Every recorded request, newest first — the Requests shelf's listing.

        The stamp has second resolution, so requests made in one burst tie; the
        rowid breaks it, keeping them in the order they were spoken.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM requests ORDER BY created_at DESC, rowid DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_request(self, prompt_id: str) -> dict | None:
        """The request that queued this generation, or ``None`` if none did."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM requests WHERE prompt_id = ?", (prompt_id,)
            ).fetchone()
            return dict(row) if row else None
