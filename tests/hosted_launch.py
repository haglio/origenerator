from __future__ import annotations

from origenerator.fun_time_mode import (
    MODE_FLAG,
    SHAPES,
    funestra_flags,
    headset_flags,
    required_flags,
)

_ANYTHING = "0"


def hosted_launch(
    *, funestras: bool = False, headset: bool = False, **named: str,
) -> list[str]:
    argv = [MODE_FLAG]
    for flag in required_flags():
        if flag != MODE_FLAG:
            argv += [flag, named.get(flag, _ANYTHING)]
    if funestras:
        for shape in SHAPES:
            for flag in funestra_flags(shape):
                argv += [flag, named.get(flag, _ANYTHING)]
    if headset:
        for flag in headset_flags():
            argv += [flag, named.get(flag, _ANYTHING)]
    return argv
