from __future__ import annotations

import json
from pathlib import Path

from origenerator import animation_settings, combine_runs
from origenerator.action_settings import VIDEO


def test_offering_every_action_reads_the_accepted_settings_once(tmp_path, monkeypatch):
    held = tmp_path / "animation_recipes.json"
    held.write_text(json.dumps({VIDEO: {}}), encoding="utf-8")
    monkeypatch.setattr(animation_settings, "SETTINGS_PATH", held)
    read = []
    read_text = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda path, *a, **k: (
        read.append(path) if path == held else None) or read_text(path, *a, **k))

    combine_runs.offered_actions([], VIDEO, (), "state one")

    assert len(read) == 1
