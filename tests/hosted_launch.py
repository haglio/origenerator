from __future__ import annotations

from pathlib import Path

from origenerator.fun_time_mode import (
    MODE_FLAG,
    SHAPES,
    FunTimeSession,
    funestra_flags,
    headset_flags,
    parse_app_args,
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


def a_headset_session_publishing_into(folder: Path) -> FunTimeSession:
    return parse_app_args(hosted_launch(headset=True, **{
        "--frames-file": str(folder / "frame.bin"),
        "--input-file": str(folder / "input.txt"),
        "--width": "200",
        "--height": "100",
    })).fun_time
