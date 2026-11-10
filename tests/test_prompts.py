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

_LONGER_THAN_ANY_SETTING = 200


def _assigned_strings(module: str) -> dict[str, str]:
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
    verbose = {name: len(value)
               for name, value in _assigned_strings("config.py").items()
               if len(value) > _LONGER_THAN_ANY_SETTING}

    assert verbose == {}, (
        "a prompt is behavior, tuned by reading what the model does with it, "
        "and changes for reasons no setting shares")


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
    assert "never" in rule.lower()
    assert "end" in rule.lower()


def test_a_request_about_a_setting_is_taught_to_change_the_setting_and_leave_the_prompts():
    prompt = _request_prompt()
    rule = prompt[prompt.index("SETTINGS HE MAY ALSO CHANGE"):].split("\n")[0].lower()

    assert '"settings"' in rule
    assert "leave" in rule
    assert "prompts" in rule
    assert '"settings": {}' in prompt
