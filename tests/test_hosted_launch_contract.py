from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from shared_ui.preview import Preview

from origenerator import fun_time_mode as contract
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

    assert published.read_text(encoding="utf-8") == contract.published_text()


def test_the_parser_accepts_exactly_the_flags_the_document_names():
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


def test_no_other_window_here_wears_that_caption():
    wears_it = re.compile(
        r'setWindowTitle\(\s*"' + re.escape(_document()["window_title"]) + r'"\s*\)')
    elsewhere = [
        source for source in (REPO_ROOT / "origenerator").rglob("*.py")
        if source.name != "core.py"
        and wears_it.search(source.read_text(encoding="utf-8"))
    ]

    assert elsewhere == []


def test_the_module_the_document_names_tells_a_session_what_to_hear_said_to_a_side():
    done = run_python(["-m", _document()["spoken_phrases_module"]], timeout=60, check=True)

    assert "request" in json.loads(done.stdout)["phrases"]


def test_publishing_writes_the_document_where_a_host_would_look(tmp_path):
    written = contract.publish(tmp_path)

    assert written == tmp_path / contract.CONTRACT_FILE
    assert written.read_bytes() == contract.published_text().encode("utf-8")


def test_a_region_rect_is_not_required_of_a_launch():
    full = [word
            for flag in contract.required_flags()[1:]
            for word in (flag, "7")] + [contract.MODE_FLAG]

    session = contract.parse_app_args(full).fun_time

    assert session is not None
    assert session.region_rect("portrait") == contract.Rect(0, 0, 0, 0)


def test_the_document_names_every_fix_a_session_should_hear_for_the_built_in_parts():
    phrases = contract.declaration()["fix_phrases"]
    assert {"fix teeth", "fix skin", "fix hair"} <= set(phrases)
    assert [phrase for phrase in phrases if not detail_parts.match_fix_command(phrase)] == []
