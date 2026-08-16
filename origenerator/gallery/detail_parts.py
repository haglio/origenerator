"""The parts a detail fix can be aimed at by name — "fix teeth" resolved to the
installed detector that finds teeth.

The enhance's detail pass runs whatever detector models its two slots name
(:meth:`~origenerator.workflows.base.WorkflowTemplate.detail_fix_nodes`), so
aiming it at one part is a matter of putting the right model file in a slot and
blanking the other. What this module adds is the naming: a table of the parts
worth asking for out loud, each carrying the words a spoken command may call it
and the filename fragments an installed detector is recognized by. The table is
deliberately not derived from the installed files — ``face_yolov8m.pt`` says
"face" only to something that knows to look — and a part stays in the table with
no detector installed, so the answer to "fix teeth" can name the file to add
rather than pretend nothing was said.

Only the anatomy any photo has is named here. The rest of the vocabulary is
library content, unpublishable for the same reason the act names are, so it
comes from the content overlay's optional ``detail_fix_parts`` entries
(``content.example.json`` documents the shape) and extends this table at load.

Both directions live here: a spoken command resolves to a part and an installed
detector (:func:`match_fix_command`, :func:`detector_for_part`), and a recorded
detector filename resolves back to the word that captions the level it made
(:func:`detector_part_label`).
"""

import re
from dataclasses import dataclass
from pathlib import PureWindowsPath

from origenerator.content import load_content
from origenerator.workflows.model_files import list_detector_files


@dataclass(frozen=True)
class DetailPart:
    """One part a targeted fix can be asked for.

    ``name`` is the canonical word — what the level's caption and the on-screen
    answer call it. ``spoken`` is every word a command may use for it, and
    ``matches`` the lowercase filename fragments that recognize an installed
    detector as finding it.
    """

    name: str
    spoken: tuple
    matches: tuple


# The published vocabulary. Fragments follow the naming the ADetailer-style
# YOLO models use in the wild (face_yolov8m, hand_yolov8s, and the rest named
# for what they find), so a model dropped into ComfyUI is recognized as-is.
_BUILTIN_PARTS = (
    DetailPart("faces", ("face", "faces"), ("face",)),
    DetailPart("hands", ("hand", "hands"), ("hand",)),
    DetailPart("teeth", ("teeth", "tooth", "mouth"), ("teeth", "tooth", "mouth")),
    DetailPart("eyes", ("eye", "eyes"), ("eye",)),
)


def _overlay_parts() -> tuple:
    """The overlay's own additions, in the built-ins' shape.

    Tolerant the way every overlay consumer is: a malformed entry is skipped
    rather than taking voice down with it, and a listed part missing its words
    answers to its own name.
    """
    parts = []
    for entry in load_content().get("detail_fix_parts") or []:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        name = str(entry["name"])
        spoken = tuple(str(w).lower() for w in entry.get("spoken") or ()) or (name.lower(),)
        matches = tuple(str(w).lower() for w in entry.get("matches") or ()) or (name.lower(),)
        parts.append(DetailPart(name, spoken, matches))
    return tuple(parts)


DETAIL_PARTS = _BUILTIN_PARTS + _overlay_parts()

# A command is a few words — "fix her teeth, please" — while anything
# sentence-shaped is a prompt edit that happens to start with "fix".
_MAX_COMMAND_WORDS = 6


def _lead_is_fix(word: str) -> bool:
    """Whether the utterance's first word is "fix" — as whisper renders it.

    Off a quiet mic the base model takes real liberties with a one-syllable
    imperative: "fixed" for it, and one-letter misses like "six" ("fix teeth"
    arrives as "six-teeth."). One substitution against the two real forms is
    accepted; the part-word requirement is what keeps this loose lead from
    firing on prose.
    """
    if word in ("fix", "fixed"):
        return True
    return any(
        len(word) == len(target)
        and sum(a != b for a, b in zip(word, target)) == 1
        for target in ("fix", "fixed")
    )


def match_fix_command(text: str) -> DetailPart | None:
    """The part a spoken utterance asks to fix, or ``None`` when it isn't asking.

    Deliberately strict about the shape — it must lead with "fix" (as heard,
    :func:`_lead_is_fix`) and name a known part within a few words — because
    while prompt steering is also listening, everything unmatched here falls
    through to a prompt rewrite, and "fix the lighting" is one of those.
    Punctuation and case are whisper's, so both are ignored.
    """
    words = re.findall(r"[a-z]+", (text or "").lower())
    if not words or not _lead_is_fix(words[0]) or len(words) > _MAX_COMMAND_WORDS:
        return None
    named = set(words[1:])
    for part in DETAIL_PARTS:
        if named & set(part.spoken):
            return part
    return None


def _basename(filename: str) -> str:
    """The bare lowercase filename of a detector entry, which may be listed
    under a subfolder with either separator."""
    return PureWindowsPath(str(filename)).name.lower()


def detector_for_part(part: DetailPart) -> str | None:
    """The installed detector that finds ``part``, or ``None`` with none to.

    First match wins over the sorted install listing — with both a yolov8n and
    a yolov8m of one part installed, which runs matters less than that one does.
    """
    for name in list_detector_files():
        base = _basename(name)
        if any(fragment in base for fragment in part.matches):
            return name
    return None


def detector_part_label(filename: str) -> str:
    """The part a detector file finds, as the word a caption uses.

    A file the table doesn't recognize keeps its own stem — an exotic detector
    is better named oddly than mislabeled as some other part.
    """
    base = _basename(filename)
    for part in DETAIL_PARTS:
        if any(fragment in base for fragment in part.matches):
            return part.name
    return PureWindowsPath(str(filename)).stem
