"""The document this repo publishes about its hosted launch, held against the code.

A host builds an 18-flag command line, then finds the windows it opened by
their captions.  It cannot import this package, so ``origenerator_contract.json``
is the whole agreement -- and a document that no longer matches this app is
exactly the silent break it exists to end: a flag renamed on one side, a window
that never appears on the other, every suite green through it.

These hold the document to the parser and to the windows.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from shared_ui.preview import Preview

from origenerator import fun_time_mode as contract
from origenerator.win32 import this_process_creation_time
from tests.test_main_window import _fun_time_session, _window

REPO_ROOT = Path(__file__).resolve().parents[1]


def _document() -> dict:
    return json.loads(
        contract.contract_path(REPO_ROOT).read_text(encoding="utf-8"))


def flags_the_parser_accepts() -> set[str]:
    return {option
            for action in contract.build_parser()._actions
            for option in action.option_strings} - {"-h", "--help"}


def test_the_published_document_is_what_this_module_says():
    """Run this module when it fails: ``origenerator.fun_time_mode`` writes it."""
    published = contract.contract_path(REPO_ROOT)

    assert published.read_text(encoding="utf-8") == contract.published_text()


def test_the_parser_accepts_exactly_the_flags_the_document_names():
    """No more: a flag this app grew and never published is one no host will
    ever send.  No fewer: a flag the document names and the parser refuses
    kills a hosted launch in argparse before it can log."""
    document = _document()
    declared = {
        *document["required_flags"],
        *(flag for group in ("region_flags", "player_flags")
          for side in document[group] for flag in document[group][side]),
        *document["headset_flags"],
        document["check_launch_flag"],
    }

    assert flags_the_parser_accepts() == declared


def test_a_hosted_launch_short_of_a_required_flag_is_refused():
    """The half of the drift argparse cannot see.  An unknown flag it already
    refuses; a flag a host STOPPED sending used to be a silent default."""
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
def test_the_caption_the_document_names_is_the_one_the_hosted_main_window_wears(
        qtbot, tmp_path, preview):
    window = _window(qtbot, tmp_path, fun_time=_fun_time_session(), preview=preview)

    assert window.windowTitle() == _document()["window_title"]


def test_no_other_window_here_wears_that_caption():
    """A host matches the caption exactly, so a second window of this app's
    wearing it would be picked up in the main window's place -- which is why
    the splash is "Origenerator Loading" rather than the plain name."""
    wears_it = re.compile(
        r'setWindowTitle\(\s*"' + re.escape(_document()["window_title"]) + r'"\s*\)')
    elsewhere = [
        source for source in (REPO_ROOT / "origenerator").rglob("*.py")
        if source.name != "main_window.py"
        and wears_it.search(source.read_text(encoding="utf-8"))
    ]

    assert elsewhere == []


def test_the_slideshow_captions_the_document_names_are_the_ones_a_region_slideshow_wears():
    source = (REPO_ROOT / "origenerator" / "gui" / "slideshow_director.py").read_text(
        encoding="utf-8")

    assert "view.setWindowTitle(SLIDESHOW_TITLES[side])" in source
    assert _document()["show_titles"] == dict(contract.SLIDESHOW_TITLES)


def test_publishing_writes_the_document_where_a_host_would_look(tmp_path):
    """Byte for byte what the tracked copy holds, line endings included, so
    publishing on Windows leaves the checkout clean."""
    written = contract.publish(tmp_path)

    assert written == tmp_path / contract.CONTRACT_FILE
    assert written.read_bytes() == contract.published_text().encode("utf-8")


def test_a_region_rect_is_not_required_of_a_launch():
    """A session that hands a Funestra over opens no window of ours on that side,
    so the rect it would take is beside the point -- and a session too old to
    send them must go on launching."""
    full = [word
            for flag in contract.required_flags()[1:]
            for word in (flag, "7")] + [contract.MODE_FLAG]

    session = contract.parse_app_args(full).fun_time

    assert session is not None
    assert session.region_rect("portrait") == contract.Rect(0, 0, 0, 0)


def _handoff() -> dict:
    return contract.declaration()["handoff"]


def test_the_document_names_each_file_this_app_and_a_session_hand_each_other():
    assert {side: entry["file"] for side, entry in _handoff().items()} == {
        "offer": contract.OFFER_NAME, "showing": contract.SHOWING_NAME,
        "session": contract.SESSION_NAME, "takeover": contract.TAKEOVER_NAME}


def test_a_claim_on_the_device_is_read_exactly_when_the_document_says_it_is(tmp_path):
    pattern = _handoff()["session"]["reads"]["pattern"]
    live = f"{os.getpid()} {this_process_creation_time()}"

    for claim, read in ((live, True), (f"{live} more", False), (live.replace(" ", ", "), False)):
        (tmp_path / contract.SESSION_NAME).write_text(claim, encoding="utf-8")
        assert (bool(re.fullmatch(pattern, claim)),
                contract.a_session_holds_the_device(tmp_path)) == (read, read), claim


def test_a_takeover_carrying_what_the_document_says_this_app_reads_is_taken(tmp_path):
    asked = {contract.TAKEOVER_PID: os.getpid(), contract.TAKEOVER_ARGS: [contract.MODE_FLAG]}
    (tmp_path / contract.TAKEOVER_NAME).write_text(json.dumps(asked), encoding="utf-8")

    assert sorted(asked) == _handoff()["takeover"]["reads"]["keys"]
    assert contract.take_the_takeover(tmp_path, pid=os.getpid()) is not None


def test_every_offer_and_slideshow_mark_the_document_says_this_app_writes_is_one_it_writes():
    pid, created_at = 4321, 8765

    assert {side: entry["writes"] for side, entry in contract.handoff(pid, created_at).items()
            if "writes" in entry} == {
        "offer": [contract.offer_of(pid, created_at),
                  contract.offer_of(pid, created_at, starting=True)],
        "showing": [contract.slideshow_mark(pid, created_at)]}
