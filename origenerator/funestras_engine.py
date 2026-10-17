"""Where this app finds the Funestras' engine: the one file every Funestra plays through."""
from __future__ import annotations

import os

from origenerator.config import project_dir


def offer_the_copy_beside_the_checkouts() -> None:
    """Put the copy of the engine's file that sits beside the checkouts first.

    The engine is one ~117 MB file, fetched once into a folder for the whole
    machine, and a funestra checkout keeps its own copy beside it.  The
    engine is found by walking the folders in PATH, and the machine-wide one
    has answered "nothing here" to this app while answering for every other
    process on the same machine -- with the file plainly sitting in it.  So the
    copy beside the checkouts goes in front of it.
    """
    beside = project_dir("funestra") / "vendor"
    try:
        if not (beside / "libmpv-2.dll").is_file():
            return
    except OSError:
        return
    rest = [entry for entry in os.environ.get("PATH", "").split(os.pathsep)
            if entry != str(beside)]
    os.environ["PATH"] = os.pathsep.join([str(beside), *rest])
