"""Content overlay — the values that must not be published, loaded at runtime.

The act vocabulary the recipe matcher scores prompts against, the detector's
class labels, and the suite root all describe the library this tool serves, so
they live in ``content.local.json`` (git-ignored) rather than in source.  A
committed ``content.example.json`` documents the shape and is what a fresh or
public checkout loads; every consumer reads them through here, so the matcher,
the workflows and the tests behave the same whichever is present.

**The read is cached; the parse is not.** Five module scopes across four packages
call ``load_content``, and twenty-four modules import ``config``, so importing
the app used to read and parse the same JSON six times over. What is cached is
the file's text, keyed by the path it came from — so each caller still gets a
dictionary of its own, and one module editing the overlay it was handed can
never be every other module's edit of it. ``load_content.cache_clear()`` drops
the cache, which a test pointing ``LOCAL_CONTENT`` somewhere new needs.

The overlay does NOT merge: a local file answers instead of the example, never
on top of it, so a local overlay must carry every key. A consumer should read it
the way ``workflows.detail_parts`` does — ``.get(key) or default`` — rather than
subscript it at import, where a key the overlay predates takes the whole app
down before there is a window to say so.
"""
from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent.parent
LOCAL_CONTENT = PROJECT_DIR / "content.local.json"
EXAMPLE_CONTENT = PROJECT_DIR / "content.example.json"


@cache
def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def overlay_path(
    local_path: Path | None = None,
    example_path: Path | None = None,
) -> Path:
    """The file :func:`load_content` will read: the local overlay, or the example."""
    local_path = LOCAL_CONTENT if local_path is None else local_path
    example_path = EXAMPLE_CONTENT if example_path is None else example_path
    return local_path if local_path.exists() else example_path


def load_content(
    local_path: Path | None = None,
    example_path: Path | None = None,
) -> dict[str, Any]:
    """The local overlay's content when present, else the committed example."""
    return json.loads(_text(overlay_path(local_path, example_path)))


load_content.cache_clear = _text.cache_clear


def missing_overlay_keys(
    local_path: Path | None = None,
    example_path: Path | None = None,
) -> tuple[str, ...]:
    """Keys the committed example documents that the local overlay does not have.

    The example IS the list of what an overlay must carry — it is the file whose
    job is to document the shape — so there is no second list here to keep in
    step, and a key added to it is a key the overlay has to gain.

    ``content.local.json`` is git-ignored and hand-maintained, so it does not
    grow a key when the app does; the example has gone from three keys to nine
    in six weeks. A key present but EMPTY is not missing: that is how a feature
    is switched off, and every consumer of an optional key already reads it as
    ``.get(key) or default``.

    Empty when there is no local overlay at all: a fresh or public checkout runs
    on the example, so there is nothing to be short of.
    """
    local_path = LOCAL_CONTENT if local_path is None else local_path
    example_path = EXAMPLE_CONTENT if example_path is None else example_path
    if not local_path.exists():
        return ()
    documented = {key for key in json.loads(_text(example_path)) if key != "_comment"}
    return tuple(sorted(documented - set(json.loads(_text(local_path)))))


class MissingOverlayKey(LookupError):
    """A key the overlay has to carry, and does not — named, with its file.

    The overlay replaces the committed example rather than merging with it, so a
    ``content.local.json`` written before a key existed simply does not have it.
    A bare ``KeyError`` out of a module scope says neither which key nor which
    file, and arrives before there is a window to say it in.
    """

    def __init__(self, keys: tuple[str, ...], path: Path | None = None):
        self.keys = tuple(keys)
        self.path = overlay_path() if path is None else path
        super().__init__(
            f"the content overlay {self.path} has no "
            f"{' -> '.join(self.keys)}. It replaces content.example.json rather "
            f"than merging with it, so it has to carry every key that one does."
        )


def overlay_value(content: dict[str, Any], *keys: str) -> Any:
    """The value at *keys*, or :class:`MissingOverlayKey` naming what is absent.

    For the values a consumer genuinely cannot work without. Where it can — a
    list of optional entries, a folder that may not be configured — read the
    overlay tolerantly instead (``content.get(key) or default``), the way
    ``workflows.detail_parts`` does.
    """
    here: Any = content
    for depth, key in enumerate(keys, start=1):
        if not isinstance(here, dict) or key not in here:
            raise MissingOverlayKey(keys[:depth])
        here = here[key]
    return here
