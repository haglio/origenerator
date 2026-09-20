"""An argv for a hosted launch, built from the contract rather than written out.

A hosted launch carries every flag `fun_time_mode.required_flags` names and is
refused without them, so a test that hand-wrote a handful of them went red the
day one was added.  Built from the contract instead, a test names only what it
actually cares about and the rest follows.
"""
from __future__ import annotations

from origenerator.fun_time_mode import MODE_FLAG, SIDES, player_flags, required_flags

#: A rect, a path, an identity: anything this file does not care about.
_ANYTHING = "0"


def hosted_launch(*, players: bool = False, **named: str) -> list[str]:
    """Every required flag, with *named* overriding the ones a test cares about.

    *players* also hands both satellite players over, the way a session does.
    """
    argv = [MODE_FLAG]
    for flag in required_flags():
        if flag != MODE_FLAG:
            argv += [flag, named.get(flag, _ANYTHING)]
    if players:
        for side in SIDES:
            for flag in player_flags(side):
                argv += [flag, named.get(flag, _ANYTHING)]
    return argv
