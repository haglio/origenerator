from __future__ import annotations

import shiboken6


def is_closed(window) -> bool:
    return not shiboken6.isValid(window) or not window.isVisible()
