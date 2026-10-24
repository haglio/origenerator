"""The words a label is showing, read past a family mark it leads with."""
from __future__ import annotations

import html
import re

from PyQt6.QtCore import Qt

_LEADING_MARK = re.compile(r"^<img[^>]*>&nbsp;")


def words(label) -> str:
    if label.textFormat() != Qt.TextFormat.RichText:
        return label.text()
    return html.unescape(_LEADING_MARK.sub("", label.text()))
