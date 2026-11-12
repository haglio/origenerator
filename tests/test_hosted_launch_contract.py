from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest
from app_support.file_channel import read_key_values
from shared_ui.preview import Preview

from origenerator import fun_time_mode as contract
from origenerator import gallery_names_file
from origenerator.config import LIBRARY_STATE_DIR
from origenerator.gui.core import Launch
from origenerator.workflows import detail_parts
from tests.children import run_python
from tests.test_core import _fun_time_session, _window

REPO_ROOT = Path(__file__).resolve().parents[1]


def _document() -> dict:
    return json.loads(
        contract.contract_path(REPO_ROOT).read_text(encoding="utf-8"))


def flags_the_parser_accepts() -> set[str]:
    return {option
            for action in contract.build_parser()._actions
            for option in action.option_strings} - {"-h", "--help"}


def test_the_published_document_is_what_this_module_says():
    published = contract.contract_path(REPO_ROOT)

    assert published.read_text(encoding="utf-8") == contract.published_text(), (
        "the agreement is a file because neither app may import the other: a host builds its "
        "command line from this document alone; run origenerator.fun_time_mode when this fails: "
        "it writes the document")


def test_the_parser_accepts_exactly_the_flags_the_document_names():
    document = _document()
    declared = {
        *document["required_flags"],
        *(flag for group in ("region_flags", "player_flags")
          for side in document[group] for flag in document[group][side]),
        *document["headset_flags"],
        document["check_launch_flag"],
    }

    assert flags_the_parser_accepts() == declared, (
        "no more: a flag this app grew and never published is one no host will ever send; no "
        "fewer: a flag the document names and the parser refuses kills a hosted launch in "
        "argparse before it can log")


def test_a_hosted_launch_short_of_a_required_flag_is_refused():
    full = [word
            for flag in contract.required_flags()[1:]
            for word in (flag, "7")] + [contract.MODE_FLAG]

    assert contract.parse_app_args(full).fun_time is not None

    short = [word for word in full if word != contract.TASKBAR_IDENTITY_FLAG]
    short.remove("7")
    with pytest.raises(SystemExit):
        contract.parse_app_args(short)


def test_a_launch_that_is_not_hosted_needs_none_of_them():
    assert contract.parse_app_args([]).fun_time is None


@pytest.mark.parametrize("preview", [None, Preview(feature="the new seed row")])
def test_the_caption_the_document_names_is_the_one_hosted_core_wears(
        qtbot, tmp_path, preview):
    window = _window(qtbot, tmp_path, fun_time=_fun_time_session(),
                     launch=Launch(preview=preview))

    assert window.windowTitle() == _document()["window_title"]


def test_the_document_names_every_line_a_hosted_core_writes_in_its_status_file(
        qtbot, tmp_path):
    status_file = tmp_path / "origenerator_status.txt"
    _window(qtbot, tmp_path, fun_time=replace(_fun_time_session(), status_file=status_file))

    qtbot.waitUntil(status_file.exists, timeout=3000)

    assert sorted(read_key_values(status_file)) == sorted(_document()["status_keys"])


def test_the_document_names_where_the_gallery_names_are_kept_in_the_production_checkout():
    assert _document()["gallery_names_file"] == f"state/{gallery_names_file.GALLERY_NAMES_FILE}"
    assert gallery_names_file.GALLERY_NAMES_PATH.parent == LIBRARY_STATE_DIR


def test_no_other_window_here_wears_that_caption():
    wears_it = re.compile(
        r'setWindowTitle\(\s*"' + re.escape(_document()["window_title"]) + r'"\s*\)')
    elsewhere = [
        source for source in (REPO_ROOT / "origenerator").rglob("*.py")
        if source.name != "core.py"
        and wears_it.search(source.read_text(encoding="utf-8"))
    ]

    assert elsewhere == [], (
        "a host finds Core by its exact caption, so a second window wearing it would be picked up "
        "in Core's place")


def test_the_module_the_document_names_tells_a_session_what_to_hear_said_to_a_side():
    done = run_python(["-m", _document()["spoken_phrases_module"]], timeout=60, check=True)

    assert "request" in json.loads(done.stdout)["phrases"]


def test_publishing_writes_the_document_where_a_host_would_look(tmp_path):
    written = contract.publish(tmp_path)

    assert written == tmp_path / contract.CONTRACT_FILE
    assert written.read_bytes() == contract.published_text().encode("utf-8"), (
        "byte for byte what the tracked copy holds, line endings included, so publishing on "
        "Windows leaves the checkout clean")


def test_a_region_rect_is_not_required_of_a_launch():
    full = [word
            for flag in contract.required_flags()[1:]
            for word in (flag, "7")] + [contract.MODE_FLAG]

    try:
        session = contract.parse_app_args(full).fun_time
    except SystemExit:
        pytest.fail(
            "a session that hands a Funestra over opens no window of ours on that side, so the "
            "rect it would take is beside the point, and a session too old to send one must go "
            "on launching")

    assert session is not None
    assert session.region_rect("portrait") == contract.Rect(0, 0, 0, 0)


def test_the_document_names_every_fix_a_session_should_hear_for_the_built_in_parts():
    phrases = contract.declaration()["fix_phrases"]
    assert {"fix teeth", "fix skin", "fix hair"} <= set(phrases), (
        "the session owns the room's microphone and can only hear a phrase it was told to "
        "listen for, so a part added here without being published is one nobody can fix by "
        "voice from the headset")
    assert [phrase for phrase in phrases if not detail_parts.match_fix_command(phrase)] == []
