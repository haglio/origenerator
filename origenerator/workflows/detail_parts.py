"""The parts a detail fix can be aimed at by name — "fix teeth" resolved to the
installed detector that finds teeth.

An enhancement's detail pass is a fix per part: each part it names says how hard
its own regions are redrawn, and a part it doesn't name builds no nodes at all
(:meth:`~origenerator.workflows.base.WorkflowTemplate.detail_fix_nodes`). What
this module owns is the naming that makes that possible — a table of the parts
worth asking for, each carrying the words a spoken command may call it and the
filename fragments an installed detector is recognized by. The table is
deliberately not derived from the installed files — ``face_yolov8m.pt`` says
"face" only to something that knows to look — and a part stays in the table with
no detector installed, so the Enhance panel can grey that part with the reason
on it and the answer to "fix teeth" can name the file to add rather than pretend
nothing was said.

Only the anatomy any photo has is named here. The rest of the vocabulary is
library content, unpublishable for the same reason the act names are, so it
comes from the content overlay's optional ``detail_fix_parts`` entries
(``content.example.json`` documents the shape) and extends this table at load.

Every direction lives here: a spoken command or a panel row resolves to a part
and an installed detector (:func:`match_fix_command`, :func:`detector_for_part`),
a recorded detector filename resolves back to the word that captions the level
it made (:func:`detector_part_label`), and one enhancement's params resolve to
the passes it actually runs (:func:`detail_fixes_of`, :func:`detail_fix_passes`).
"""

import re
from dataclasses import dataclass
from pathlib import PureWindowsPath

from origenerator.content import load_content
from origenerator.workflows.model_files import list_detector_files

# What a fix runs at unless it is given a number of its own — the Enhance
# panel's fields start here, and a spoken "fix teeth" over a folder that has
# that part switched off uses it. Bold enough to actually re-form the part,
# which is the whole point of a pass that touches nothing outside what it found.
DEFAULT_FIX_DENOISE = 0.45


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


def fix_command_bias() -> str:
    """The command vocabulary as whisper's initial prompt.

    Off a quiet mic the base/small models mangle a short imperative — a
    captured "fix <part>" transcribed as "thick stick" — and the matcher can
    only stretch so far. Handing the expected phrases to whisper up front is
    what actually fixed that capture, so the transcriber is biased with every
    word a command may use, overlay parts included.
    """
    words = ["fix", "fixed"]
    for part in DETAIL_PARTS:
        words += [w for w in part.spoken if w not in words]
    return "Voice commands: " + ", ".join(words) + "."


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


def part_named(name: str) -> DetailPart | None:
    """The table's entry for a part by its canonical name, or ``None`` — a part
    an old row names that the overlay no longer lists is simply not fixable."""
    return next((part for part in DETAIL_PARTS if part.name == str(name)), None)


def _denoise(value) -> float | None:
    """One part's number as a denoise, or ``None`` when it asks for no pass.

    Zero is how a part says "leave it alone", and so is anything that isn't a
    number at all — these come back through JSON, where a stored setting can be
    whatever an older version or a hand edit left behind.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def detail_fixes_of(params: dict) -> dict:
    """The parts an enhancement redraws and how hard, as ``{part: denoise}``.

    ``enhance_detail_fixes`` is where that lives now — one number per part it
    fixes, and a part it doesn't name is a part left alone (zero counts as not
    named too, which is what a stored setting from before the panel had a box
    per part looks like). The older shape is translated
    rather than ignored: a tick, a single denoise and up to two detector files
    named is exactly a fix on whichever parts those files find, all at that one
    denoise. Every enhancement this library already carries was recorded that
    way, so they must go on captioning themselves and re-running as what they
    were.
    """
    fixes = params.get("enhance_detail_fixes")
    if isinstance(fixes, dict):
        found = {str(name): _denoise(value) for name, value in fixes.items()}
        return {name: value for name, value in found.items() if value is not None}
    if not params.get("enhance_detail_fix"):
        return {}
    denoise = _denoise(params.get("enhance_detail_denoise")) or DEFAULT_FIX_DENOISE
    # A level recorded before the detectors were carries neither name, and what
    # it ran was the generic pair.
    named = [detector_part_label(params[key])
             for key in ("enhance_face_detector", "enhance_hand_detector")
             if params.get(key)]
    return {name: denoise for name in (named or ["faces", "hands"])}


def detail_fix_passes(params: dict) -> list:
    """The passes an enhancement's detail stage actually builds: ``(detector
    file, denoise)`` per part asked for, in the table's own order.

    A part with no installed detector is dropped here rather than carried into
    the graph: ComfyUI validates the model name and rejects the whole prompt
    over one it cannot find, which would take every other pass down with it.
    Settings outlive the file they named — a folder configured while a detector
    was installed must go on enhancing after it is removed, minus that part.

    Table order rather than the order the parts were asked for, so the same
    fixes always build the same graph.
    """
    wanted = detail_fixes_of(params)
    passes = []
    for part in DETAIL_PARTS:
        denoise = wanted.get(part.name)
        if denoise is None:
            continue
        detector = detector_for_part(part)
        if detector:
            passes.append((detector, denoise))
    return passes
