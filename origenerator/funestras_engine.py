from __future__ import annotations

import os

from origenerator.config import project_dir


def offer_the_copy_beside_the_checkouts() -> None:
    """Put the engine copy beside the checkouts first in PATH: Windows has answered "nothing here" from the machine-wide folder while it held the file, and while answering every other process from it."""
    beside = project_dir("funestra") / "vendor"
    try:
        if not (beside / "libmpv-2.dll").is_file():
            return
    except OSError:
        return
    rest = [entry for entry in os.environ.get("PATH", "").split(os.pathsep)
            if entry != str(beside)]
    os.environ["PATH"] = os.pathsep.join([str(beside), *rest])
