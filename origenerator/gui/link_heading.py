from __future__ import annotations

from PyQt6.QtWidgets import QLabel


def link_heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("font-weight: bold;")
    return label
