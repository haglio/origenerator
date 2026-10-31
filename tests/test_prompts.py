"""What the local LLM is told lives in prompts.py, the module tuned by reading what
the model does, and never in config.py beside the ports and paths."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "origenerator"

SYSTEM_PROMPTS = (
    "REQUEST_SYSTEM_PROMPT",
    "SEARCH_EXPANSION_SYSTEM_PROMPT",
    "COLLECTION_NOTES_SYSTEM_PROMPT",
)

# Longer than any setting has cause to be. The shortest of the three prompts is
# hundreds of characters; the longest thing config.py legitimately holds is a
# localhost URL.
_PROSE = 200


def _assigned_strings(module: str) -> dict[str, str]:
    """Module-level ``NAME = "..."`` assignments, by name.

    Implicit concatenation inside parentheses is folded by the parser into one
    constant, which is exactly how all three prompts are written.
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
    """Held at zero. A prompt written into config would fail here rather than
    land in the file every path, port and device constant shares."""
    verbose = {name: len(value)
               for name, value in _assigned_strings("config.py").items()
               if len(value) > _PROSE}

    assert verbose == {}


@pytest.mark.parametrize("name", SYSTEM_PROMPTS)
def test_each_system_prompt_is_written_in_the_module_that_owns_them(name):
    assert name in _assigned_strings("prompts.py")


def test_config_imports_nothing_from_prompts():
    tree = ast.parse((PACKAGE / "config.py").read_text(encoding="utf-8"))

    assert not [node for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module == "origenerator.prompts"]


def _request_prompt() -> str:
    return _assigned_strings("prompts.py")["REQUEST_SYSTEM_PROMPT"]


def test_a_complaint_that_something_asked_for_is_missing_is_taught_as_make_it_stronger():
    prompt = _request_prompt()
    rule = prompt[prompt.index("didn't appear"):]

    assert "never remove" in rule.lower()
    assert "weight" in rule.lower()
    example = prompt[prompt.rindex("didn't appear"):]
    assert ":1." in example.split("->")[1].split("negative")[0]


def test_his_prompts_that_touch_the_request_are_the_model_for_writing_what_he_asks():
    rule = _request_prompt()[_request_prompt().index("PROMPTS OF HIS"):].split("\n")[0]

    assert "the way those prompts" in rule.lower() or "the way they" in rule.lower()
    assert "never" in rule.lower() and "end" in rule.lower()
