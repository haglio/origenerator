from __future__ import annotations

from shared_ui.asking import asked


def deleting_a_folder(label: str, held: str) -> str:
    return f"Delete “{label}” and its {held}?"


def deleting_folders(count: int, held: str) -> str:
    return f"Delete {count} folders and their {held}?"


def asked_to_delete(parent, text: str) -> bool:
    return asked(parent, "Delete", text)
