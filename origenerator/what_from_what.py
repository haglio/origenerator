from __future__ import annotations

import re

KINDS = re.compile(r"\b(T2I|I2I|I2V|T2V|TI2V|FLF2V|S2V)\b")


def kind_first(name: str) -> str:
    found = KINDS.search(name)
    if found is None or found.start() == 0:
        return name
    rest = " ".join((name[:found.start()] + name[found.end():]).split())
    return f"{found[0]} {rest}"
