from __future__ import annotations

from shared_ui.icons import qt_icon

from origenerator.gui.change_mark import ChangeMark

_LOOKED_AT = 24


def shows_the_delta(mark: ChangeMark) -> bool:
    drawn, delta = (icon.pixmap(_LOOKED_AT).toImage() for icon in (mark.icon(), qt_icon("delta")))
    return not delta.isNull() and drawn == delta
