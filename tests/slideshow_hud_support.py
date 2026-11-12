from __future__ import annotations

from funestra.hud_overlay import HUD_OVERLAY_ID
from funestra.scrubber_bar import SCRUBBER_HEIGHT
from funestra.testing import FakeEngine
from funestra.volume import VOLUME_CONTROL_H, volume_control_xy
from PySide6.QtCore import QPoint

from origenerator.fun_time_mode import SHAPES


def open_both_shapes(gallery_or_director) -> None:
    for shape in SHAPES:
        gallery_or_director.fill_the_region(shape)


def funestra_of(slideshow):
    pane = slideshow._pane
    if pane._funestra is None:
        pane._engine_for = lambda wid: FakeEngine()
        pane._open_if_ready()
    return pane._funestra


def engine_of(slideshow) -> FakeEngine:
    funestra_of(slideshow)
    return slideshow._pane._engine


def hud_targets(slideshow):
    funestra = funestra_of(slideshow)
    slideshow._pane.tick()
    return funestra._hud.targets


def hud_button_names(slideshow) -> list[str]:
    return [button.command.removeprefix(f"{slideshow.hud_shape}_")
            for _rect, button in hud_targets(slideshow).buttons]


def _on_screen(slideshow, rect) -> QPoint:
    left, top, _pixels = engine_of(slideshow).overlays[HUD_OVERLAY_ID]
    x, y, width, height = rect
    scale = slideshow._pane._window.devicePixelRatioF()
    return QPoint(round((left + x + width / 2) / scale), round((top + y + height / 2) / scale))


def button_on_screen(slideshow, command) -> QPoint:
    rect, = [rect for rect, button in hud_targets(slideshow).buttons if button.command == command]
    return _on_screen(slideshow, rect)


def thumbnail_on_screen(slideshow, path) -> QPoint:
    rect, = [rect for rect, target in hud_targets(slideshow).click if target == path]
    return _on_screen(slideshow, rect)


def speaker_on_screen(pane) -> QPoint:
    left, top, _pixels = pane._engine.overlays[HUD_OVERLAY_ID]
    x, y, width, height = pane._funestra._hud.row.rect
    cx, cy = volume_control_xy(viewport_w=width, viewport_h=height, timeline_h=SCRUBBER_HEIGHT)
    scale = pane._window.devicePixelRatioF()
    return QPoint(round((left + x + cx + 4) / scale),
                  round((top + y + cy + VOLUME_CONTROL_H // 2) / scale))
