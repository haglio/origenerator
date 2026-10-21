"""Which drop style a drop zone on screen wears, read off its pixels."""
from __future__ import annotations

from PyQt6.QtCore import QPoint

from origenerator.gui.drop_style import AIMED, EDGE, GROUNDS, LIT


def worn(image, rect, ground_at: QPoint | None = None) -> str | None:
    """:data:`LIT` or :data:`AIMED` when ``rect`` of ``image`` is edged in the
    style's blue on that state's ground, read at ``ground_at`` or just inside its
    left edge; None when it wears neither."""
    middle = rect.center()
    edge = {image.pixelColor(middle.x(), rect.top()).name(),
            image.pixelColor(middle.x(), rect.bottom()).name(),
            image.pixelColor(rect.left(), middle.y()).name(),
            image.pixelColor(rect.right(), middle.y()).name()}
    ground = image.pixelColor(ground_at or QPoint(rect.left() + 3, middle.y())).name()
    if edge != {EDGE.name()}:
        return None
    return next((state for state in (LIT, AIMED) if GROUNDS[state].name() == ground), None)
