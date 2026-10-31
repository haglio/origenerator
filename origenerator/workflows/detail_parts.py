"""The parts a detail fix can be aimed at by name — "fix teeth" resolved to the
installed detector that finds teeth.

An enhancement's detail pass is a fix per part: each part it names says how hard
its own regions are redrawn, and a part it doesn't name builds no nodes at all
(:meth:`~origenerator.workflows.base.WorkflowTemplate.detail_fix_nodes`). The
table is deliberately not derived from the installed files — ``face_yolov8m.pt``
says "face" only to something that knows to look — and a part stays in it with
no detector installed, so the Enhance pane can gray that part with the reason
on it and the answer to "fix teeth" can name the file to add.

Only the anatomy any photo has is named here. The rest of the vocabulary is
library content, unpublishable for the same reason the act names are, so it
comes from the content overlay's optional ``detail_fix_parts`` entries
(``content.example.json`` documents the shape) and extends this table at load.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PureWindowsPath

from origenerator.content import load_content
from origenerator.voice.text import sounds_like, words
from origenerator.workflows.model_files import (
    is_no_lora,
    list_detector_files,
    list_outline_detector_files,
)

# Bold enough to actually re-form a part: the Enhance pane's fields start here.
DEFAULT_FIX_DENOISE = 0.45
# How much harder a part is fixed each time a fix of it is asked for again, and
# the hardest a fix goes.
FIX_STEP = 0.1
FIX_MAX = 1.0


@dataclass(frozen=True)
class DetailPart:
    """One part a targeted fix can be asked for: ``name`` is what the version's
    caption and the on-screen answer call it, ``spoken`` every word a command
    may use for it, and ``matches`` the lowercase filename fragments that
    recognize an installed detector as finding it."""

    name: str
    spoken: tuple
    matches: tuple
    outline: bool = False
    prompt: str = ""
    avoid: str = ""
    dilation: int = 10  # pixels grown around each rect, so edges are inside
    framed_together: bool = False
    shared_photos: bool = True


# Fragments follow the naming the ADetailer-style YOLO models use in the wild,
# so a model dropped into ComfyUI is recognized as-is.
_BUILTIN_PARTS = (
    DetailPart("faces", ("face", "faces"), ("face",),
               prompt=("natural detailed face, natural proportions of the face, realistic skin "
                       "texture, photographic detail"),
               avoid="deformed face, distorted features, plastic skin, waxy, blurry"),
    DetailPart("hands", ("hand", "hands"), ("hand",),
               prompt=("natural hands, five fingers on each hand, realistic knuckles and "
                       "fingernails, natural skin creases, photographic detail"),
               avoid="extra fingers, missing fingers, fused fingers, deformed hands, blurry"),
    DetailPart("teeth", ("teeth", "tooth"), ("teeth", "tooth"),
               prompt=("natural teeth, distinct evenly sized teeth, natural gum line, "
                       "realistic mouth, photographic detail"),
               avoid="fused teeth, extra teeth, deformed mouth, blurry"),
    DetailPart("eyes", ("eye", "eyes"), ("eye",), framed_together=True,
               prompt=("natural eyes, detailed iris, round pupils, natural catchlight, "
                       "realistic eyelashes, photographic detail"),
               avoid="cross-eyed, mismatched eyes, deformed pupils, blurry"),
    DetailPart("skin", ("skin",), ("skin",), outline=True,
               prompt=("natural skin texture, visible pores, fine lines, slight "
                       "imperfections, soft light under the skin, photographic detail"),
               avoid="smooth plastic skin, airbrushed, waxy, doll-like, blurry"),
    DetailPart("hair", ("hair",), ("hair",), outline=True,
               prompt=("natural hair, individual strands, flyaway hairs, soft natural "
                       "sheen, photographic detail"),
               avoid="helmet hair, one solid smooth shape, painted hair, blurry"),
    DetailPart("mouth", ("mouth", "tongue"), ("mouth", "lips"), dilation=64,
               prompt=("natural mouth, tongue clearly separate from the lips, defined lip "
                       "edges, natural teeth, photographic detail"),
               avoid="tongue merged with lips, fused lips, deformed mouth, extra tongue, blurry"),
)


def _overlay_parts(content: dict | None = None) -> tuple:
    if content is None:
        content = load_content()
    parts = []
    for entry in content.get("detail_fix_parts") or []:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        name = str(entry["name"])
        spoken = tuple(str(w).lower() for w in entry.get("spoken") or ()) or (name.lower(),)
        matches = tuple(str(w).lower() for w in entry.get("matches") or ()) or (name.lower(),)
        parts.append(DetailPart(name, spoken, matches, outline=entry.get("outline") is True,
                                prompt=_text(entry.get("prompt")),
                                avoid=_text(entry.get("avoid")),
                                shared_photos=entry.get("shared_photos") is not False))
    return tuple(parts)


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def part_table(content: dict | None = None) -> tuple:
    """The built-in parts, then the overlay's own — asked for rather than built
    at import, so a different overlay can be handed through."""
    return _BUILTIN_PARTS + _overlay_parts(content)


def part_named(name: str) -> DetailPart:
    return next(part for part in part_table() if part.name == name)


def parts_framed_together() -> frozenset[str]:
    return frozenset(part.name for part in part_table() if part.framed_together)


# A command is a few words; anything sentence-shaped is no command, though it
# happens to start with "fix" ("fix the color of her eyes to blue").
_MAX_COMMAND_WORDS = 6

# One word standing in for the whole table.
ALL_PARTS_WORDS = ("all", "everything")


def _lead_is_fix(word: str) -> bool:
    """Whether the first word is "fix" as whisper renders it off a quiet mic:
    "fixed", or one letter off ("six")."""
    return sounds_like(word, ("fix", "fixed"))


def match_fix_command(text: str) -> tuple:
    """The parts a spoken utterance asks to fix, in the table's order — ``()``
    when it isn't asking. Strict about the shape: "fix the lighting" starts
    like one and names no part."""
    heard = words(text)
    if not heard or not _lead_is_fix(heard[0]) or len(heard) > _MAX_COMMAND_WORDS:
        return ()
    named = set(heard[1:])
    table = part_table()
    if named & set(ALL_PARTS_WORDS):
        return tuple(table)
    return tuple(part for part in table if named & set(part.spoken))


def fix_command_phrases() -> frozenset[str]:
    """Every fix a recognizer that listens for words should hear: one part by
    each word it answers to, two parts at once, and the lot. More than two is
    said rarely enough to be left to the engine that takes sentences down."""
    table = part_table()
    one = {word: part for part in table for word in part.spoken}
    phrases = {f"fix {word}" for word in (*one, *ALL_PARTS_WORDS)}
    phrases |= {f"fix {first} and {second}" for first in one for second in one
                if one[first] is not one[second]}
    return frozenset(phrases)


def published_fix_phrases() -> tuple[str, ...]:
    """Every fix of a built-in part a host's recognizer should hear."""
    return tuple(f"fix {word}" for part in _BUILTIN_PARTS for word in part.spoken)


def fix_command_spelling(text: str) -> str | None:
    """A fix command with its lead verb spelled the way the app names it —
    "Six teeth." read back as "fix teeth" — or ``None`` when it is no fix."""
    if not match_fix_command(text):
        return None
    heard = words(text)
    return " ".join(["fix", *heard[1:]])


def _basename(filename: str) -> str:
    return PureWindowsPath(str(filename)).name.lower()


def finder_of(part: DetailPart) -> str:
    return "segm" if part.outline else "bbox"


def detector_folder(part: DetailPart) -> str:
    return f"models/ultralytics/{finder_of(part)}"


def detector_for_part(part: DetailPart) -> str | None:
    """The first installed detector that finds ``part``, or ``None``."""
    for name in list_outline_detector_files() if part.outline else list_detector_files():
        base = _basename(name)
        if any(fragment in base for fragment in part.matches):
            return name
    return None


def fixable_parts(parts) -> tuple:
    """Those of ``parts`` something installed can find. ComfyUI rejects a whole
    prompt over one detector it cannot find, so a part with none is dropped
    rather than run, and the rest of the command still happens."""
    return tuple(part for part in parts if detector_for_part(part) is not None)


def detector_part(filename: str) -> DetailPart | None:
    base = _basename(filename)
    return next((part for part in part_table() if any(fragment in base for fragment in part.matches)),
                None)


def detector_part_label(filename: str) -> str:
    """The part a detector file finds, or its own stem for a file the table
    doesn't recognize — better named oddly than mislabeled as another part."""
    part = detector_part(filename)
    return part.name if part is not None else PureWindowsPath(str(filename)).stem


def name_parts(parts) -> str:
    """The parts of one fix as the words that caption its version: "hands & teeth"."""
    return " & ".join(part.name for part in parts)


def _denoise(value) -> float | None:
    """A part's stored number as a denoise; ``None`` for zero or for no number."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def detail_fixes_of(params: dict) -> dict:
    """The parts an enhancement redraws and how hard, as ``{part: denoise}``.

    ``enhance_detail_fixes`` is one number per part; the older shape every
    enhancement the library already carries was recorded in — a tick, a single
    denoise and up to two detector files — is translated rather than ignored,
    so those go on captioning themselves and re-running as what they were.
    """
    fixes = params.get("enhance_detail_fixes")
    if isinstance(fixes, dict):
        found = {str(name): _denoise(value) for name, value in fixes.items()}
        return {name: value for name, value in found.items() if value is not None}
    if not params.get("enhance_detail_fix"):
        return {}
    denoise = _denoise(params.get("enhance_detail_denoise")) or DEFAULT_FIX_DENOISE
    named = [detector_part_label(params[key])
             for key in ("enhance_face_detector", "enhance_hand_detector")
             if params.get(key)]
    return dict.fromkeys(named or ["faces", "hands"], denoise)


def fix_prompts(params: dict) -> dict:
    """The prompts each part an enhancement fixes is redrawn toward and away from:
    the ones its settings give that part, else the part's own."""
    given = params.get("enhance_fix_prompts")
    given = given if isinstance(given, dict) else {}
    fixes = detail_fixes_of(params)
    return {part.name: fix_prompts_of(part, given.get(part.name))
            for part in part_table() if part.name in fixes}


def fix_prompts_of(part: DetailPart, named) -> dict:
    named = named if isinstance(named, dict) else {}
    lora = named.get("lora")
    return {"prompt": str(named.get("prompt", part.prompt)),
            "avoid": str(named.get("avoid", part.avoid)),
            "lora": "" if is_no_lora(lora) else str(lora),
            "strength": float(named.get("strength", 1.0))}


@dataclass(frozen=True)
class DetailFixPass:
    part: DetailPart
    detector: str
    denoise: float


def detail_fix_passes(params: dict) -> list[DetailFixPass]:
    """The passes an enhancement's detail stage actually builds, in the table's
    order: one per part asked for that has a detector installed, since settings
    outlive the file they named."""
    wanted = detail_fixes_of(params)
    passes = []
    for part in part_table():
        denoise = wanted.get(part.name)
        if denoise is None:
            continue
        detector = detector_for_part(part)
        if detector:
            passes.append(DetailFixPass(part, detector, denoise))
    return passes
