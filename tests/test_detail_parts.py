"""The spoken-fix vocabulary: "fix teeth" resolved to a part, a part to the
installed detector that finds it, and a recorded detector back to its word.

Overlay-fed parts are exercised with the same fabricated placeholders the
committed content example uses — the real vocabulary is library content and
never appears in these repos.
"""

import pytest

from origenerator.gallery import detail_parts
from origenerator.gallery.detail_parts import (
    detector_for_part,
    detector_part_label,
    match_fix_command,
)


# --- recognizing a spoken command -------------------------------------------


@pytest.mark.parametrize("text, part", [
    ("Fix teeth.", "teeth"),
    ("fix the teeth", "teeth"),
    ("Fix her hands", "hands"),
    ("fix hand", "hands"),
    ("Fixed the eyes.", "eyes"),   # what an imperative "fix" is often heard as
    ("Fix face", "faces"),
    ("Fix her mouth", "teeth"),
    ("six-teeth.", "teeth"),       # whisper, quiet mic: "fix teeth" verbatim
    ("Mix her hands.", "hands"),   # one letter off "fix" still reads as it
])
def test_a_short_fix_utterance_names_its_part(text, part):
    assert match_fix_command(text).name == part


@pytest.mark.parametrize("text", [
    "fix the lighting",              # "fix" of something undetectable: a prompt edit
    "the teeth need fixing",         # doesn't lead with fix
    "make her teeth whiter",         # no fix at all
    "fix the way she is holding the wine glass in her left hand",  # sentence-shaped
    "six of them",                   # a fix-alike lead with no part named
    "vic shows teeth",               # two letters from "fix" is another word
    "",
    ". . . .",
])
def test_anything_else_is_left_for_prompt_steering(text):
    assert match_fix_command(text) is None


# --- resolving a part to an installed detector ------------------------------


def _part(name):
    return next(p for p in detail_parts.DETAIL_PARTS if p.name == name)


def test_a_part_resolves_to_the_installed_detector_that_finds_it(monkeypatch):
    monkeypatch.setattr(detail_parts, "list_detector_files",
                        lambda: ["Teeth_v1.pt", "face_yolov8m.pt", "hand_yolov8s.pt"])
    assert detector_for_part(_part("teeth")) == "Teeth_v1.pt"
    assert detector_for_part(_part("faces")) == "face_yolov8m.pt"
    assert detector_for_part(_part("hands")) == "hand_yolov8s.pt"


def test_a_part_with_no_installed_detector_resolves_to_nothing(monkeypatch):
    # The answer to "fix teeth" with nothing to find teeth is to say so, not to
    # run a pass that finds nothing — None is what lets the caller say it.
    monkeypatch.setattr(detail_parts, "list_detector_files",
                        lambda: ["face_yolov8m.pt", "hand_yolov8s.pt"])
    assert detector_for_part(_part("teeth")) is None


def test_a_detector_in_a_subfolder_is_matched_by_its_own_name(monkeypatch):
    # The install listing is relative to the category dir, so a nested model
    # arrives with a subfolder prefix that must not hide its name.
    monkeypatch.setattr(detail_parts, "list_detector_files",
                        lambda: [r"extra\eyes_yolov8n.pt"])
    assert detector_for_part(_part("eyes")) == r"extra\eyes_yolov8n.pt"


# --- naming a recorded detector back ----------------------------------------


def test_a_detector_file_labels_as_the_part_it_finds():
    assert detector_part_label("face_yolov8m.pt") == "faces"
    assert detector_part_label("hand_yolov8s.pt") == "hands"
    assert detector_part_label("Teeth_v1.pt") == "teeth"
    assert detector_part_label(r"extra\eyes_yolov8n.pt") == "eyes"


def test_an_unrecognized_detector_keeps_its_own_name():
    # Better named oddly than mislabeled as some other part.
    assert detector_part_label("wristwatch_yolov8n.pt") == "wristwatch_yolov8n"


# --- the overlay's own vocabulary -------------------------------------------


def _with_overlay(monkeypatch, entries):
    """Rebuild the table as a load with these overlay entries would have."""
    monkeypatch.setattr(detail_parts, "load_content",
                        lambda: {"detail_fix_parts": entries})
    monkeypatch.setattr(detail_parts, "DETAIL_PARTS",
                        detail_parts._BUILTIN_PARTS + detail_parts._overlay_parts())


def test_overlay_parts_join_the_vocabulary_whole(monkeypatch):
    # The private vocabulary rides in through the content overlay, shaped like
    # the built-ins: spoken words in, detector fragments out, label back.
    _with_overlay(monkeypatch, [
        {"name": "zeta", "spoken": ["zeta", "zetas"], "matches": ["zeta"]},
    ])
    monkeypatch.setattr(detail_parts, "list_detector_files",
                        lambda: ["zeta_yolov8n.pt"])

    part = match_fix_command("fix her zetas")
    assert part.name == "zeta"
    assert detector_for_part(part) == "zeta_yolov8n.pt"
    assert detector_part_label("zeta_yolov8n.pt") == "zeta"


def test_a_bare_overlay_part_answers_to_its_own_name(monkeypatch):
    _with_overlay(monkeypatch, [{"name": "Zeta"}])
    part = match_fix_command("fix zeta")
    assert part is not None and part.name == "Zeta"
    assert part.matches == ("zeta",)


def test_malformed_overlay_entries_are_skipped_not_fatal(monkeypatch):
    # A bad line in the overlay must not take voice commands down with it.
    _with_overlay(monkeypatch, ["zeta", {"spoken": ["zeta"]}, {"name": ""}])
    assert detail_parts.DETAIL_PARTS == detail_parts._BUILTIN_PARTS
