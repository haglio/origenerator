from __future__ import annotations


class ActionStore:
    def __init__(self, had=None):
        self.item_actions = dict(had or {})
        self.sides = []

    def set_actions(self, prompt_id, side, item_actions):
        replaced = {prompt_id: self.item_actions.get(prompt_id)}
        self.item_actions[prompt_id] = item_actions
        self.sides.append(side)
        return replaced

    def put_back(self, side, replaced):
        self.item_actions.update(replaced)
        self.sides.append(side)
