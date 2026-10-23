from __future__ import annotations

from funestra.hud_overlay import HUD_OVERLAY_ID
from funestra.timeline import TIMELINE_HEIGHT
from funestra.volume import CHIP_H, chip_xy
from PyQt6.QtCore import QPoint

from origenerator.fun_time_mode import SIDES
from tests.funestra_fakes import FakeEngine


def open_both_sides(gallery_or_director) -> None:
    for side in SIDES:
        gallery_or_director.fill_the_region(side)


def funestra_of(slideshow):
    """The slideshow's Funestra -- opened on a stand-in engine where the suite's
    platform has no window for the pane to open the real one in."""
    pane = slideshow._pane
    if pane._funestra is None:
        pane._engine_for = lambda wid: FakeEngine()
        pane._open_if_ready()
    return pane._funestra


def engine_of(slideshow) -> FakeEngine:
    funestra_of(slideshow)
    return slideshow._pane._engine


def panel_targets(slideshow):
    """What the panel the slideshow's Funestra drew put where."""
    funestra = funestra_of(slideshow)
    slideshow._pane.tick()
    return funestra._panel.targets


def hud_button_names(slideshow) -> list[str]:
    """The buttons on that panel, by their own names."""
    return [button.command.removeprefix(f"{slideshow.hud_side}_")
            for _rect, button in panel_targets(slideshow).buttons]


def _on_screen(slideshow, rect) -> QPoint:
    """The middle of a rect of the panel, in the slideshow's window's own pixels."""
    left, top, _pixels = engine_of(slideshow).overlays[HUD_OVERLAY_ID]
    x, y, width, height = rect
    scale = slideshow._pane._window.devicePixelRatioF()
    return QPoint(round((left + x + width / 2) / scale), round((top + y + height / 2) / scale))


def button_on_screen(slideshow, command) -> QPoint:
    rect, = [rect for rect, button in panel_targets(slideshow).buttons if button.command == command]
    return _on_screen(slideshow, rect)


def thumbnail_on_screen(slideshow, path) -> QPoint:
    rect, = [rect for rect, target in panel_targets(slideshow).click if target == path]
    return _on_screen(slideshow, rect)


def speaker_on_screen(pane) -> QPoint:
    """The speaker on the panel a pane's Funestra drew, in its window's own pixels."""
    left, top, _pixels = pane._engine.overlays[HUD_OVERLAY_ID]
    x, y, width, height = pane._funestra._panel.row.rect
    cx, cy = chip_xy(win_w=width, win_h=height, timeline_h=TIMELINE_HEIGHT)
    scale = pane._window.devicePixelRatioF()
    return QPoint(round((left + x + cx + 4) / scale),
                  round((top + y + cy + CHIP_H // 2) / scale))
