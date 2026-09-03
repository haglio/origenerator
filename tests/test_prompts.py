"""What the local LLM is told, and where that text is allowed to live.

`config.py` is the highest-fan-in module in the repo — twenty-four importers —
and 95 of its 242 lines, 39% of the file, were four multi-paragraph system
prompts. Those are the part most likely to change often and the part least like
configuration: they are behaviour, tuned by reading what the model does with
them, so a prompt reworded for the search widener showed up in the blame of the
same file as the UDP port the OSR2 broker pins.

They live in `origenerator/prompts.py` now, and this holds the line: no
assignment in config.py evaluates to prose.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
import ast
from pathlib import Path

import pytest

from origenerator import config, prompts

PACKAGE = Path(__file__).resolve().parents[1] / "origenerator"

# The four, by name. Each is re-exported from config so no importer had to move.
SYSTEM_PROMPTS = (
    "SEARCH_EXPANSION_SYSTEM_PROMPT",
    "VIDEO_SCENE_MATCH_SYSTEM_PROMPT",
    "VOICE_REQUEST_MATCH_SYSTEM_PROMPT",
    "VOICE_REWRITE_SYSTEM_PROMPT",
)

# Longer than any setting has cause to be. The shortest of the four prompts is
# over a thousand characters; the longest thing config.py legitimately holds is
# a localhost URL.
_PROSE = 200


def _assigned_strings(module: str) -> dict[str, str]:
    """Module-level ``NAME = "..."`` assignments, by name.

    Implicit concatenation inside parentheses is folded by the parser into one
    constant, which is exactly how all four prompts are written.
    """
    tree = ast.parse((PACKAGE / module).read_text(encoding="utf-8"))
    return {
        target.id: node.value.value
        for node in tree.body if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }


def test_config_declares_settings_and_not_prose():
    """Held at zero. A fifth prompt written into config would fail here rather
    than land in the file every path, port and device constant shares."""
    verbose = {name: len(value)
               for name, value in _assigned_strings("config.py").items()
               if len(value) > _PROSE}

    assert verbose == {}


@pytest.mark.parametrize("name", SYSTEM_PROMPTS)
def test_each_system_prompt_is_written_in_the_module_that_owns_them(name):
    assert name in _assigned_strings("prompts.py")


@pytest.mark.parametrize("name", SYSTEM_PROMPTS)
def test_config_still_answers_for_every_one_of_them(name):
    """The re-export, which is what let the move touch no importer: the gui
    package and the voice package both reach them through config today."""
    assert getattr(config, name) is getattr(prompts, name)

