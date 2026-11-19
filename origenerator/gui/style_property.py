from __future__ import annotations

from PySide6.QtWidgets import QWidget


def set_style_property(widget: QWidget, name: str, value) -> None:
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    # Qt reads a stylesheet's property selector again only on a repolish.
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()
