"""Content overlay — the values that must not be published, loaded at runtime.

The act vocabulary the recipe matcher scores prompts against, the detector's
class labels, and the suite root all describe the library this tool serves, so
they live in ``content.local.json`` (git-ignored) rather than in source.  A
committed ``content.example.json`` documents the shape and is what a fresh or
public checkout loads; every consumer reads them through here, so the matcher,
the workflows and the tests behave the same whichever is present.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent.parent
LOCAL_CONTENT = PROJECT_DIR / "content.local.json"
EXAMPLE_CONTENT = PROJECT_DIR / "content.example.json"


def load_content(
    local_path: Path | None = None,
    example_path: Path | None = None,
) -> dict[str, Any]:
    """The local overlay's content when present, else the committed example."""
    local_path = LOCAL_CONTENT if local_path is None else local_path
    example_path = EXAMPLE_CONTENT if example_path is None else example_path
    path = local_path if local_path.exists() else example_path
    return json.loads(path.read_text(encoding="utf-8"))
