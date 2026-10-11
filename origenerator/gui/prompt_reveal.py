"""Where a find's match is shown: in a prompt field somewhere down a tab's form."""

from __future__ import annotations

from PyQt6.QtWidgets import QScrollArea

from origenerator.gui.collapsible_section import CollapsibleSection
from origenerator.gui.deferred import defer

_ROOM_AROUND_A_REVEALED_PROMPT = 40


def reveal_prompt(field):
    _unfold(field)
    _scroll_into_view(field)
    # A section unfolded a line ago has not been laid out yet, so that scroll
    # aimed at where the field used to be.
    defer(field, lambda: _scroll_into_view(field))


def _unfold(widget):
    node = widget.parent()
    while node is not None:
        if isinstance(node, CollapsibleSection):
            node.set_collapsed(False)
            return
        node = node.parent()


def _scroll_into_view(widget):
    node = widget.parent()
    while node is not None:
        if isinstance(node, QScrollArea):
            node.ensureWidgetVisible(widget, 0, _ROOM_AROUND_A_REVEALED_PROMPT)
            return
        node = node.parent()
