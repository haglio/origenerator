from __future__ import annotations

from PyQt6.QtWidgets import QApplication, QMenu


def offer_copy_names(menu: QMenu, names: list[str]) -> None:
    names = [name for name in names if name]
    if not names:
        return
    wording = "Copy name" if len(names) == 1 else f"Copy {len(names)} names"
    menu.addAction(wording).triggered.connect(
        lambda: QApplication.clipboard().setText("\n".join(names)))
