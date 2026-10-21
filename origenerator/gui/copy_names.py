from __future__ import annotations

from PyQt6.QtWidgets import QApplication, QMenu


def copy_names(names: list[str]) -> None:
    text = "\n".join(name for name in names if name)
    if text:
        QApplication.clipboard().setText(text)


def offer_copy_names(menu: QMenu, names: list[str]) -> None:
    names = [name for name in names if name]
    if not names:
        return
    wording = "Copy name" if len(names) == 1 else f"Copy {len(names)} names"
    menu.addAction(wording).triggered.connect(lambda: copy_names(names))
