"""The one interface every driver of a slideshow reaches through.

The Funestras' HUD, the console's clip-seconds pair and — inside a session — Fun
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

from origenerator.fun_time_mode import FunestraChannel
from origenerator.gui.frame_files import FrameFiles
from origenerator.gui.funestra_slideshow import FunestraSlideshow
from origenerator.gui.slideshow_host import SlideshowHost
from origenerator.gui.slideshow_panel import slideshow_hud_model
from origenerator.gui.slideshow_view import SlideshowView
from tests.funestra_fakes import FakeEngine

# What a slideshow answers to, written out so an attribute added to the protocol without
# a reason recorded here is a failure rather than a surprise. The first six are
# the transport; the rest are about a set.
TRANSPORT = (
    "locked", "dwell_s", "set_dwell_s",
    "slideshow_step", "slideshow_toggle_lock", "slideshow_cull",
    # The lock said which way rather than flipped: a session's spoken "lock"
    # and "unlock".
    "set_locked",
)
THE_SET = (
    "slideshow_reset", "hud_map", "hud_favorites_filter", "hud_order_label",
    "hud_is_favorite", "hud_item_note", "toggle_favorites_filter", "show_item",
    # F-mode said which way, as the lock is: "f mode on" and "f mode off".
    "set_favorites_filter",
    # The map's own chrome and the session's keys over it: the loops along
    # its two axes, the loop key that steps them, the expand mark, and a step
    # to a neighboring cell.
    "slideshow_loop", "slideshow_loop_cycle", "slideshow_more_seeds", "slideshow_nav",
    # The act filter: the button at the head of each map row, and what lights it.
    "slideshow_filter", "hud_act_filter", "clear_modes",
    # And the same filter set from the item on screen: a session's "filter".
    "slideshow_filter_to_the_act_on_screen",
    # The enhanced-only switch beside F-mode: declared here because three
    # drivers reach for it — the HUD's button, the session console's, and the
    # spoken word — and it was the last of the switches still being probed for.
    "hud_enhanced_mode", "toggle_enhanced_mode", "set_enhanced_mode",
    "slideshow_order",
    # The device half of the one panel a slideshow wears: what to draw on it, and
    # what a press on its rows asks for.
    "hud_device", "press_console",
    # The queue block at that panel's foot: what is in flight, the order a row
    # dragged down it asks for, and the Clear that drops another app's work.
    "hud_queue", "requeue", "clear_foreign_queue",
    # The one thing a hosting session does to a slideshow's sound: a slideshow landing
    # on a satellite region is silenced.  The track, the time and the volume
    # are the Funestra's own, so no host answers for them.
    "set_audio_muted",
)

# The three modules that drive a host. Each is checked for probes separately, so
# a probe put back in one of them cannot be paid for by one removed in another.
DRIVERS = (
    "origenerator/gui/slideshow_panel.py",
    "origenerator/fun_time_bridge.py",
    "origenerator/gui/console.py",
)


def test_the_protocol_is_exactly_the_attributes_written_down_here():
    # An equality, not a ceiling: an attribute added to SlideshowHost without a line here
    # reds, and so does one deleted from it that is still listed.
    assert set(SlideshowHost.__protocol_attrs__) == set(TRANSPORT + THE_SET)


@pytest.fixture
def slideshow(qtbot):
    view = SlideshowView([("a.png", "image")], engine=FakeEngine(),
                         shuffle=lambda order: None)
    qtbot.addWidget(view)
    return view


@pytest.fixture
def on_a_funestra(qtbot, tmp_path):
    slideshow = FunestraSlideshow([("a.png", "image")], side="portrait", channel=FunestraChannel(
        playlist=tmp_path / "portrait.tsv", command_file=tmp_path / "portrait_cmd.txt",
        status_file=tmp_path / "portrait_status.txt",
        hud_file=tmp_path / "origenerator_portrait_hud.json"),
        frames=FrameFiles(tmp_path / "frames"))
    slideshow._timer.stop()
    return slideshow


@pytest.mark.parametrize("attribute", TRANSPORT + THE_SET)
def test_a_slideshow_answers_every_attribute_of_the_protocol(slideshow, attribute):
    # The full host: it has a set, so it answers all of it itself. Asked of an
    # instance rather than the class, because two of the attributes are settled
    # when the slideshow is built rather than declared on it.
    assert hasattr(slideshow, attribute)


@pytest.mark.parametrize("attribute", TRANSPORT + THE_SET)
def test_a_slideshow_on_a_funestra_answers_every_attribute_of_the_protocol(on_a_funestra, attribute):
    # The other host: a slideshow handed to a session's Funestra.  It has a set, so it
    # answers all of it itself, the same as the window does.
    assert hasattr(on_a_funestra, attribute)


def test_a_slideshow_with_nothing_to_map_has_no_hud_model(slideshow, monkeypatch):
    monkeypatch.setattr(slideshow, "hud_map", lambda: None)

    assert slideshow_hud_model("portrait", slideshow) is None


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
