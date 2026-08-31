"""The one interface every driver of a show reaches through.

The players' HUD, the on-video console and — inside a session — Fun Time's own
file channels all drive whatever is holding a region. What they may ask of it
used to be written nowhere: each caller re-discovered the interface by probing
attribute names as strings, sixteen times over three modules, and the three did
not agree about what a host must provide. These pin the interface itself, both
of its implementors, and the fact that nothing probes for it any more.
"""

import ast
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent

import pytest

from origenerator.gui.show_host import ShowHost
from origenerator.gui.slideshow_pace import PaceOnlyHost, SlideshowPace
from origenerator.gui.slideshow_view import SlideshowView

# What a show answers to, written out so a member added to the protocol without
# a reason recorded here is a failure rather than a surprise. The first six are
# the transport every host has; the rest are about a set, and a host with no set
# behind it takes the protocol's own answers for them.
TRANSPORT = (
    "locked", "dwell_s", "set_dwell_s",
    "stroke_step", "stroke_toggle_hold", "stroke_cull",
)
THE_SET = (
    "stroke_reset", "hud_items", "hud_f_mode", "hud_order_label", "hud_looping",
    "hud_is_favorite", "toggle_f_mode", "show_item", "current_media_path",
)

# The three modules that drive a host. Each is checked for probes separately, so
# a probe put back in one of them cannot be paid for by one removed in another.
DRIVERS = (
    "origenerator/gui/show_hud.py",
    "origenerator/gui/fun_time_bridge.py",
    "origenerator/gui/stroke_panel.py",
)


def test_the_protocol_is_exactly_the_members_written_down_here():
    # An equality, not a ceiling: a member added to ShowHost without a line here
    # reds, and so does one deleted from it that is still listed.
    assert set(ShowHost.__protocol_attrs__) == set(TRANSPORT + THE_SET)


@pytest.fixture
def slideshow(qtbot):
    view = SlideshowView([("a.png", "image")], player=MagicMock(),
                         shuffle=lambda order: None)
    qtbot.addWidget(view)
    return view


@pytest.fixture
def pace_only():
    return PaceOnlyHost(SlideshowPace())


@pytest.mark.parametrize("member", TRANSPORT + THE_SET)
def test_a_slideshow_answers_every_member_of_the_protocol(slideshow, member):
    # The full host: it has a set, so it answers all of it itself. Asked of an
    # instance rather than the class, because two of the members are settled
    # when the show is built rather than declared on it.
    assert hasattr(slideshow, member)


@pytest.mark.parametrize("member", TRANSPORT + THE_SET)
def test_a_pace_only_host_answers_every_member_of_the_protocol(pace_only, member):
    # The main window's console with nothing behind it: it answers the transport
    # itself and takes the protocol's answers for the set it does not have.
    assert hasattr(pace_only, member)


def test_a_host_with_no_set_says_it_has_no_set(pace_only):
    host = pace_only

    assert host.hud_items() == ((), 0, True)
    assert host.hud_f_mode is False
    assert host.hud_order_label == ""
    assert host.hud_looping is True
    assert host.hud_is_favorite is False
    assert host.current_media_path() == ""


def test_the_verbs_about_a_set_do_nothing_where_there_is_no_set(pace_only):
    # Not an error and not a silence to be guarded against at every call site:
    # the one documented answer for a host with nothing to step.
    host = pace_only

    assert host.stroke_reset() is None
    assert host.toggle_f_mode() is None
    assert host.show_item("anything", hold=True) is None


def test_a_host_with_no_set_draws_no_hud_map(pace_only):
    # show_hud_model asks rather than probes now, and an empty set is the answer
    # that means "nothing to map" — the same None the hasattr used to return.
    from origenerator.gui.show_hud import show_hud_model

    assert show_hud_model("portrait", pace_only) is None


def _probes_in(relative_path: str) -> list[str]:
    """Every hasattr/getattr in the file that names a member of the protocol."""
    tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
    members = set(TRANSPORT + THE_SET)
    return [
        f"{relative_path}:{node.lineno} {node.func.id}(…, {node.args[1].value!r})"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id in ("hasattr", "getattr") and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value in members
    ]


@pytest.mark.parametrize("driver", DRIVERS)
def test_no_driver_asks_a_host_what_it_can_do_by_probing_for_it(driver):
    # Held per file at zero. The interface is declared, so a caller that guards
    # a member of it is either guarding against a host that cannot exist or
    # hiding one that does — and either way the guard, not the host, is the bug.
    assert _probes_in(driver) == []
