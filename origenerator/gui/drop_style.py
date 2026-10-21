"""The style a drop zone wears while a drag it would take is under way: edged in
blue and lit, and one step lighter still while the drag is over it."""
from __future__ import annotations

from shared_ui.colors import BG_TERTIARY, BLUE, hovered

LIT = "dragActive"
AIMED = "dropTarget"
GROUNDS = {LIT: BG_TERTIARY, AIMED: hovered(BG_TERTIARY)}
EDGE = BLUE


def ground_rules() -> str:
    return "".join(f"""
    QWidget[{state}="true"] {{
        background-color: {GROUNDS[state].name()};
    }}""" for state in (LIT, AIMED))
