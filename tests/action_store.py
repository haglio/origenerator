from __future__ import annotations

from origenerator.action_setter_tool import AnswersTold
from origenerator.item_actions import actions_if_any, columns, stored
from origenerator.media import MediaType
from tests.real_db import put_rows


class ActionStore(AnswersTold):
    def __init__(self, db, side=MediaType.IMAGE, *, items=(), had=None):
        had = had or {}
        put_rows(db, [{"prompt_id": prompt_id, **_stored_on(side, had.get(prompt_id))}
                      for prompt_id in (*items, *had)])
        self.db, self.side, self.sides = db, side, []
        super().__init__(db, lambda _prompt_id, told_side, _actions: self.sides.append(told_side))

    @property
    def item_actions(self):
        given = {row["prompt_id"]: actions_if_any(row, self.side)
                 for row in self.db.list_generations()}
        return {prompt_id: actions for prompt_id, actions in given.items() if actions is not None}


def _stored_on(side, item_actions):
    if item_actions is None:
        return {}
    return dict(zip(columns(side), stored(item_actions), strict=True))
