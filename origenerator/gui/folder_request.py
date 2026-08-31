"""A config tab that is one folder's prompt rewrite rather than one generation.

:class:`FolderRequest` is that state, and the words the tab wears while it is in
it. Kept out of the panel because the panel has a dozen other things to be about
and this has four questions and no Qt in it.
"""

from __future__ import annotations

from dataclasses import dataclass

from origenerator.generation_config import ConfigSnapshot, configs_match

_REQUEST_CAPTION = "Request changes"
_REQUEST_TIP = (
    "Run all {count} images in this folder again, each with its own seed and "
    "the prompt as you have rewritten it, landing them in a new folder."
)
# Its own wording rather than a plural switched off, which left "Run all 1
# image ... each with its own seed" on a folder holding one.
_REQUEST_TIP_ONE = (
    "Run this folder's one image again with its own seed and the prompt as "
    "you have rewritten it, landing it in a new folder."
)
_REQUEST_TITLE = "Request {folder}"


@dataclass(frozen=True)
class FolderRequest:
    """A tab that is a whole folder's prompt rewrite rather than one config.

    A tab opened this way is about a folder: it shows the folder's pictures
    instead of a file, its Generate asks for one run per picture rather than one
    run, and its name is the folder's. That is a distinct state, and it used to
    be a four-key dict tested for None at four sites — each site knowing on its
    own which key it wanted and what to make of it.

    ``opened_on`` is the settings the tab opened at, and is the whole of how a
    press tells a rewrite from a re-run of the folder being rewritten: a request
    that asked for nothing would re-run every seed in the folder to re-create the
    folder. Frozen, because a request that could be edited could quietly come to
    agree with whatever was typed after it.

    ``count`` is one per run the press will make, whether or not there is a
    thumbnail to draw for it, so the hover counts images rather than readable
    files.
    """

    folder_key: str
    label: str
    count: int
    opened_on: ConfigSnapshot

    def title(self) -> str:
        """What the row of tabs calls this one."""
        return _REQUEST_TITLE.format(folder=self.label)

    def caption(self) -> str:
        """What the Generate button says: one ask, not a count of runs."""
        return _REQUEST_CAPTION

    def tooltip(self) -> str:
        """…and how many runs that ask costs, a hover away."""
        return (_REQUEST_TIP_ONE if self.count == 1
                else _REQUEST_TIP.format(count=self.count))

    def is_unchanged(self, config: ConfigSnapshot) -> bool:
        """Whether the tab still says exactly what it opened saying."""
        return configs_match(self.opened_on, config)
