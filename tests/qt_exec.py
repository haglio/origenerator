from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any


def faking_exec(monkeypatch, qt_class: type, fake: Callable[..., Any]) -> None:
    """Qt classes under PySide6 ignore an exec set on them, so each module's name for the class is a subclass whose exec is the fake."""
    stand_in = type(qt_class.__name__, (qt_class,), {"exec": fake})
    for module in list(sys.modules.values()):
        if vars(module).get(qt_class.__name__) is qt_class:
            monkeypatch.setattr(module, qt_class.__name__, stand_in)
