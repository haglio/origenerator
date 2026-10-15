"""Walking the animations one at a time, settling what each runs: best-attested
first (:mod:`origenerator.animation_samples`), one with no sample coming up blank."""
from __future__ import annotations

import json

Path = tuple[str, str, str]  # lane, act, state


class AnimationCheckSession:

    def __init__(self, paths: list[Path], samples: dict[Path, list[dict]], store,
                 *, pinned=None):
        """``pinned(act, lane)`` answers the act's own settings, which an
        animation nobody ever kept a video of starts from instead of a sample."""
        self._pinned = pinned or (lambda act, lane: None)
        self._paths = list(paths)
        self._ranks = {path: rank for rank, path in enumerate(self._paths)}
        self._samples = {path: list(clips) for path, clips in samples.items()}
        self._store = store
        self._at = 0


    @property
    def path(self) -> Path | None:
        return self._paths[self._at] if self._at < len(self._paths) else None

    @property
    def sample(self) -> dict | None:
        found = self._samples.get(self.path) or []
        return found[0] if found else None

    @property
    def starting_point(self) -> dict | None:
        """The settings on screen: what he has already assigned to this
        animation, else the sample's own, else the act's."""
        here = self.path
        if here is None:
            return None
        assigned = self._store.assigned(*here)
        if assigned is not None:
            return assigned
        sample = self.sample
        if sample is not None:
            return {"workflow": sample.get("workflow_name") or "",
                    "params": _params(sample)}
        return self._pinned(here[1], here[0])

    @property
    def another_sample(self) -> bool:
        return len(self._samples.get(self.path) or []) > 1

    @property
    def position(self) -> tuple[int, int]:
        here = self.path
        if here is None:
            return (len(self._paths), len(self._paths))
        return (self._ranks[here] + 1, len(self._paths))

    @property
    def answered(self) -> int:
        return len(self._store.accepted_paths() & set(self._paths))


    def accept(self, *, positive: str, negative: str) -> None:
        """Take the settings on screen, with the prompts as they now read (the
        half he edits), as what this animation runs -- then move on."""
        here = self.path
        if here is None:
            return
        from_here = self.starting_point or {}
        self._store.remember(
            *here,
            workflow=from_here.get("workflow") or "",
            params={**(from_here.get("params") or {}),
                    "positive_prompt": positive, "negative_prompt": negative},
        )
        self._forward()

    def next_sample(self) -> None:
        found = self._samples.get(self.path)
        if found:
            found.pop(0)

    def forward(self) -> None:
        self._at = min(len(self._paths) - 1, self._at + 1)

    def back(self) -> None:
        self._at = max(0, self._at - 1)

    def _forward(self) -> None:
        self._at = min(len(self._paths), self._at + 1)


def _params(row: dict) -> dict:
    try:
        held = json.loads(row.get("params_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return held if isinstance(held, dict) else {}
