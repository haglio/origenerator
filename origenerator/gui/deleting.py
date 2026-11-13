from __future__ import annotations

from PySide6.QtWidgets import QMessageBox


def deleting_a_folder(label: str, count: int) -> str:
    return f"Delete “{label}” and its {count} item{'s' if count != 1 else ''}?"


def deleting_folders(count: int, items: int) -> str:
    return f"Delete {count} folders and their {items} item{'s' if items != 1 else ''}?"


def asked_to_delete(parent, text: str) -> bool:
    reply = QMessageBox.question(
        parent, "Delete", text,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    return reply == QMessageBox.StandardButton.Yes
