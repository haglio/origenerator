"""The fix vocabulary: "fix teeth" resolved to a part, a part to the installed
detector that finds it, a recorded detector back to its word, and one
enhancement's settings to the passes it runs.

Overlay-fed parts are exercised with the same fabricated placeholders the
committed content example uses — the real vocabulary is library content and
never appears in these repos.
"""

import pytest

from origenerator.workflows import detail_parts
from origenerator.workflows.detail_parts import (
    detail_fix_passes,
    detail_fixes_of,
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


def test_the_whisper_bias_names_every_spoken_word_once(monkeypatch):
    # What the transcriber is taught to expect: fix itself and every part
    # word, the overlay's private vocabulary included — whisper can only
    # come back with "fix <part>" if it has heard of the part.
    _with_overlay(monkeypatch, [{"name": "zeta", "spoken": ["zeta", "zetas"]}])
    bias = detail_parts.fix_command_bias()
    for word in ("fix", "fixed", "teeth", "hands", "eyes", "zeta", "zetas"):
        assert word in bias
    assert bias.count("fix,") == 1  # each word once, not once per part


# --- the passes one enhancement's settings ask for ---------------------------


def test_a_part_at_zero_or_absent_asks_for_no_pass():
    # Zero is how the panel says "leave this part alone", and a part it has
    # never been given a number for reads the same way.
    assert detail_fixes_of({"enhance_detail_fixes": {}}) == {}
    assert detail_fixes_of({"enhance_detail_fixes": {"teeth": 0}}) == {}
    assert detail_fixes_of({}) == {}


def test_each_part_carries_its_own_denoise():
    assert detail_fixes_of({"enhance_detail_fixes": {"teeth": 0.5, "hands": 0.6}})         == {"teeth": 0.5, "hands": 0.6}


def test_junk_where_a_number_should_be_asks_for_no_pass():
    # These come back through JSON, where a hand edit or an older version can
    # leave anything at all — and a pass is better dropped than submitted with
    # a denoise the sampler will reject.
    assert detail_fixes_of({"enhance_detail_fixes": {"teeth": "lots"}}) == {}
    assert detail_fixes_of({"enhance_detail_fixes": "all of them"}) == {}


def test_an_enhancement_recorded_the_old_way_reads_as_the_parts_it_fixed():
    # Every enhancement in the library predates the per-part numbers: one tick,
    # one denoise, two detector slots. What that ran is a fix on each part those
    # detectors find, all at that denoise — and it must go on saying so.
    assert detail_fixes_of({
        "enhance_detail_fix": True, "enhance_detail_denoise": 0.45,
        "enhance_face_detector": "face_yolov8m.pt",
        "enhance_hand_detector": "hand_yolov8s.pt",
    }) == {"faces": 0.45, "hands": 0.45}
    assert detail_fixes_of({
        "enhance_detail_fix": True, "enhance_detail_denoise": 0.5,
        "enhance_face_detector": "Teeth_v1.pt", "enhance_hand_detector": "",
    }) == {"teeth": 0.5}
    assert detail_fixes_of({"enhance_detail_fix": False,
                            "enhance_detail_denoise": 0.45}) == {}


def test_an_old_pass_that_named_no_detector_ran_the_generic_pair():
    # Levels recorded before the detectors were: the pass was faces and hands.
    assert detail_fixes_of({"enhance_detail_fix": True}) == {
        "faces": detail_parts.DEFAULT_FIX_DENOISE,
        "hands": detail_parts.DEFAULT_FIX_DENOISE,
    }


def test_the_passes_are_the_installed_detector_for_each_part_asked_for(monkeypatch):
    monkeypatch.setattr(detail_parts, "list_detector_files",
                        lambda: ["Teeth_v1.pt", "face_yolov8m.pt"])
    assert detail_fix_passes({"enhance_detail_fixes": {"teeth": 0.5, "faces": 0.4}})         == [("face_yolov8m.pt", 0.4), ("Teeth_v1.pt", 0.5)]


def test_the_passes_come_in_the_tables_order_however_they_were_asked_for(monkeypatch):
    # The same fixes must build the same graph, whichever order they were set
    # in — otherwise a re-run of one enhancement is a different one.
    monkeypatch.setattr(detail_parts, "list_detector_files",
                        lambda: ["Teeth_v1.pt", "face_yolov8m.pt"])
    asked = {"enhance_detail_fixes": {"teeth": 0.5, "faces": 0.4}}
    backwards = {"enhance_detail_fixes": {"faces": 0.4, "teeth": 0.5}}
    assert detail_fix_passes(asked) == detail_fix_passes(backwards)


def test_a_part_with_no_installed_detector_is_dropped_rather_than_submitted(monkeypatch):
    # ComfyUI validates the model name and rejects the whole prompt over one it
    # cannot find — which would take every other pass down with it. Settings
    # outlive the file they named, so this is an ordinary state, not an error.
    monkeypatch.setattr(detail_parts, "list_detector_files",
                        lambda: ["face_yolov8m.pt"])
    assert detail_fix_passes({"enhance_detail_fixes": {"teeth": 0.5, "faces": 0.4}})         == [("face_yolov8m.pt", 0.4)]


def test_a_part_the_vocabulary_no_longer_lists_is_dropped(monkeypatch):
    # An overlay entry removed after a folder was configured with it: the
    # settings still name the part, and nothing in the table answers to it.
    monkeypatch.setattr(detail_parts, "list_detector_files",
                        lambda: ["omega_yolov8n.pt"])
    assert detail_fix_passes({"enhance_detail_fixes": {"omega": 0.5}}) == []
