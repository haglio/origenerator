from __future__ import annotations

import json
from dataclasses import dataclass
from typing import NamedTuple

from origenerator.db_connection import Store
from origenerator.db_generations import MADE_ELSEWHERE, MADE_HERE


class Turn(NamedTuple):

    said: str
    answered: str = ""
    old_positive: str = ""
    old_negative: str = ""
    new_positive: str = ""
    new_negative: str = ""
    settings: str = ""
    made: str = ""

    def changes(self) -> list[tuple[str, str, str]]:
        return [tuple(change) for change in json.loads(self.settings)] if self.settings else []


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
    turns: tuple = ()


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
        self.record_turns(request.prompt_id, request.turns)

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

    def distinct_positive_prompts(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT positive_prompt FROM generations
                   WHERE positive_prompt IS NOT NULL AND TRIM(positive_prompt) != ''
                     AND {MADE_HERE}
                   GROUP BY positive_prompt ORDER BY MIN(id)""",
                MADE_ELSEWHERE,
            ).fetchall()
            return [row[0] for row in rows]

    def distinct_prompts(self) -> list[tuple[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT positive_prompt, MIN(COALESCE(negative_prompt, '')) FROM generations
                   WHERE positive_prompt IS NOT NULL AND TRIM(positive_prompt) != ''
                     AND {MADE_HERE}
                   GROUP BY positive_prompt ORDER BY MIN(id)""",
                MADE_ELSEWHERE,
            ).fetchall()
            return [(row[0], row[1]) for row in rows]

    def record_turns(self, prompt_id: str, turns) -> None:
        with self._connect() as conn:
            conn.executemany(
                """INSERT INTO request_turns
                       (prompt_id, said, answered, old_positive, old_negative,
                        new_positive, new_negative, settings_json, made)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [(prompt_id, *Turn(*turn)) for turn in turns])

    def mark_made(self, prompt_id: str, position: int, made: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """UPDATE request_turns SET made = ? WHERE id =
                       (SELECT id FROM request_turns WHERE prompt_id = ?
                        ORDER BY id LIMIT 1 OFFSET ?)""", (made, prompt_id, position))

    def turns_of(self, prompt_id: str) -> list[Turn]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT said, answered, old_positive, old_negative, new_positive, new_negative,
                          settings_json, made
                   FROM request_turns WHERE prompt_id = ? ORDER BY id""", (prompt_id,)).fetchall()
        turns = [Turn(*row) for row in rows]
        if turns and not turns[-1].made:
            turns[-1] = turns[-1]._replace(made=prompt_id)
        return turns

    def _chain(self, prompt_id: str) -> list[str]:
        chain: list[str] = []
        current: str | None = prompt_id
        while current and current not in chain:
            chain.insert(0, current)
            request = self.get_request(current)
            current = request["source_prompt_id"] if request else None
        return chain

    def exchange_of(self, prompt_id: str) -> list[Turn]:
        return [turn for link in self._chain(prompt_id) for turn in self.turns_of(link)]

    def items_asked_into(self, prompt_id: str) -> list[str]:
        return [link for link in self._chain(prompt_id) for _turn in self.turns_of(link)]

    def started_on(self, prompt_id: str) -> str | None:
        root = self._chain(prompt_id)[0]
        return None if root == prompt_id or self.get_request(root) else root
