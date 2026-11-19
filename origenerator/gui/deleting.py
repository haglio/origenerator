from __future__ import annotations

from PySide6.QtWidgets import QMessageBox


def deleting_a_folder(label: str, held: str) -> str:
    return f"Delete “{label}” and its {held}?"


def deleting_folders(count: int, held: str) -> str:
    return f"Delete {count} folders and their {held}?"


def asked_to_delete(parent, text: str) -> bool:
    reply = QMessageBox.question(
        parent, "Delete", text,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    return reply == QMessageBox.StandardButton.Yes
