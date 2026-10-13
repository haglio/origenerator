from __future__ import annotations

from funestra.hud_overlay import HUD_OVERLAY_ID
from PyQt6.QtCore import QPoint

from tests.funestra_fakes import FakeEngine


def funestra_of(show):
    """The show's Funestra -- opened on a stand-in engine where the suite's
    platform has no window for the pane to open the real one in."""
    pane = show._pane
    if pane._funestra is None:
        pane._engine_for = lambda wid: FakeEngine()
        pane._open_if_ready()
    return pane._funestra


def engine_of(show) -> FakeEngine:
    funestra_of(show)
    return show._pane._engine


def panel_targets(show):
    """What the panel the show's Funestra drew put where."""
    funestra = funestra_of(show)
    show._pane.tick()
    return funestra._panel.targets


def hud_button_names(show) -> list[str]:
    """The buttons on that panel, by their own names."""
    return [button.command.removeprefix(f"{show.hud_side}_")
            for _rect, button in panel_targets(show).buttons]


def _on_screen(show, rect) -> QPoint:
    """The middle of a rect of the panel, in the show's window's own pixels."""
    left, top, _pixels = engine_of(show).overlays[HUD_OVERLAY_ID]
    x, y, width, height = rect
    scale = show._pane._window.devicePixelRatioF()
    return QPoint(round((left + x + width / 2) / scale), round((top + y + height / 2) / scale))


def button_on_screen(show, command) -> QPoint:
    rect, = [rect for rect, button in panel_targets(show).buttons if button.command == command]
    return _on_screen(show, rect)


def thumbnail_on_screen(show, path) -> QPoint:
    rect, = [rect for rect, target in panel_targets(show).click if target == path]
    return _on_screen(show, rect)
