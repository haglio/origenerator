"""The one interface every driver of a show reaches through.

The players' HUD, the console's clip-seconds pair and — inside a session — Fun
Time's own file channels all drive whatever is holding a region. What they may ask of it
used to be written nowhere: each caller re-discovered the interface by probing
attribute names as strings, sixteen times over three modules, and the three did
not agree about what a host must provide. These pin the interface itself, both
of its implementors, and the fact that nothing probes for it any more.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

import pytest

from origenerator.fun_time_mode import PlayerChannel
from origenerator.gui.frame_files import FrameFiles
from origenerator.gui.player_show import PlayerShow
from origenerator.gui.show_host import ShowHost
from origenerator.gui.show_panel import show_hud_model
from origenerator.gui.slideshow_view import SlideshowView
from tests.funestra_fakes import FakePlayer

# What a show answers to, written out so an attribute added to the protocol without
# a reason recorded here is a failure rather than a surprise. The first six are
# the transport; the rest are about a set.
TRANSPORT = (
    "locked", "dwell_s", "set_dwell_s",
    "show_step", "show_toggle_lock", "show_cull",
    # The lock said which way rather than flipped: a session's spoken "lock"
    # and "unlock".
    "set_locked",
)
THE_SET = (
    "show_reset", "hud_map", "hud_favorites_filter", "hud_order_label",
    "hud_is_favorite", "hud_item_note", "toggle_favorites_filter", "show_item",
    # F-mode said which way, as the lock is: "f mode on" and "f mode off".
    "set_favorites_filter",
    # The map's own chrome and the session's keys over it: the loops along
    # its two axes, the loop key that steps them, the expand mark, and a step
    # to a neighboring cell.
    "show_loop", "show_loop_cycle", "show_more_seeds", "show_nav",
    # The act filter: the button at the head of each map row, and what lights it.
    "show_filter", "hud_act_filter", "clear_modes",
    # And the same filter set from the item on screen: a session's "filter".
    "show_filter_to_the_act_on_screen",
    # The enhanced-only switch beside F-mode: declared here because three
    # drivers reach for it — the HUD's button, the session console's, and the
    # spoken word — and it was the last of the switches still being probed for.
    "hud_enhanced_mode", "toggle_enhanced_mode", "set_enhanced_mode",
    "show_order",
    # The device half of the one panel a show wears: what to draw on it, and
    # what a press on its rows asks for.
    "hud_device", "press_console",
    # The queue block at that panel's foot: what is in flight, the order a row
    # dragged down it asks for, and the Clear that drops another app's work.
    "hud_queue", "requeue", "clear_foreign_queue",
    # The one thing a hosting session does to a show's sound: a show landing
    # on a satellite region is silenced.  The track, the time and the volume
    # are the Funestra's own, so no host answers for them.
    "set_audio_muted",
)

# The three modules that drive a host. Each is checked for probes separately, so
# a probe put back in one of them cannot be paid for by one removed in another.
DRIVERS = (
    "origenerator/gui/show_panel.py",
    "origenerator/fun_time_bridge.py",
    "origenerator/gui/console.py",
)


def test_the_protocol_is_exactly_the_attributes_written_down_here():
    # An equality, not a ceiling: an attribute added to ShowHost without a line here
    # reds, and so does one deleted from it that is still listed.
    assert set(ShowHost.__protocol_attrs__) == set(TRANSPORT + THE_SET)


@pytest.fixture
def slideshow(qtbot):
    view = SlideshowView([("a.png", "image")], player=FakePlayer(),
                         shuffle=lambda order: None)
    qtbot.addWidget(view)
    return view


@pytest.fixture
def on_a_player(qtbot, tmp_path):
    show = PlayerShow([("a.png", "image")], side="portrait", channel=PlayerChannel(
        playlist=tmp_path / "portrait.tsv", command_file=tmp_path / "portrait_cmd.txt",
        status_file=tmp_path / "portrait_status.txt",
        hud_file=tmp_path / "origenerator_portrait_hud.json"),
        frames=FrameFiles(tmp_path / "frames"))
    show._timer.stop()
    return show


@pytest.mark.parametrize("attribute", TRANSPORT + THE_SET)
def test_a_slideshow_answers_every_attribute_of_the_protocol(slideshow, attribute):
    # The full host: it has a set, so it answers all of it itself. Asked of an
    # instance rather than the class, because two of the attributes are settled
    # when the show is built rather than declared on it.
    assert hasattr(slideshow, attribute)


@pytest.mark.parametrize("attribute", TRANSPORT + THE_SET)
def test_a_show_on_a_player_answers_every_attribute_of_the_protocol(on_a_player, attribute):
    # The other host: a show handed to a session's player.  It has a set, so it
    # answers all of it itself, the same as the window does.
    assert hasattr(on_a_player, attribute)


def test_a_show_with_nothing_to_map_has_no_hud_model(slideshow, monkeypatch):
    monkeypatch.setattr(slideshow, "hud_map", lambda: None)

    assert show_hud_model("portrait", slideshow) is None


def _probes_in(relative_path: str) -> list[str]:
    """Every hasattr/getattr in the file that names an attribute of the protocol."""
    tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
    attributes = set(TRANSPORT + THE_SET)
    return [
        f"{relative_path}:{node.lineno} {node.func.id}(…, {node.args[1].value!r})"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id in ("hasattr", "getattr") and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value in attributes
    ]


@pytest.mark.parametrize("driver", DRIVERS)
def test_no_driver_asks_a_host_what_it_can_do_by_probing_for_it(driver):
    # Held per file at zero. The interface is declared, so a caller that guards
    # an attribute of it is either guarding against a host that cannot exist or
    # hiding one that does — and either way the guard, not the host, is the bug.
    assert _probes_in(driver) == []
