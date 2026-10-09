from __future__ import annotations

from tests.funestra_fakes import FakePlayer


def funestra_of(show):
    """The show's Funestra -- opened on a stand-in engine where the suite's
    platform has no window for the pane to open the real one in."""
    pane = show._pane
    if pane._funestra is None:
        pane._player_for = lambda wid: FakePlayer()
        pane._open_if_ready()
    return pane._funestra


def engine_of(show) -> FakePlayer:
    funestra_of(show)
    return show._pane._player


def panel_targets(show):
    """What the panel the show's Funestra drew put where."""
    funestra = funestra_of(show)
    show._pane.tick()
    return funestra._panel.targets


def hud_button_names(show) -> list[str]:
    """The buttons on that panel, by their own names."""
    return [button.command.removeprefix(f"{show.hud_side}_")
            for _rect, button in panel_targets(show).buttons]
