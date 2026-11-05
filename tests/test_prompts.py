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

_PROSE = 200


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
    example = prompt[prompt.index("- \"the dog didn't appear\""):].split("\n")[0]
    answer = example.split("->")[1]
    assert ":1." in answer
    assert '"remove": "animals"' in answer


def test_his_prompts_that_touch_the_request_are_the_model_for_writing_what_he_asks():
    rule = _request_prompt()[_request_prompt().index("PROMPTS OF HIS"):].split("\n")[0]

    assert "the way those prompts" in rule.lower() or "the way they" in rule.lower()
    assert "never" in rule.lower()
    assert "end" in rule.lower()


def test_portrait_and_landscape_are_taught_as_width_and_height_never_as_prompt_words():
    prompt = _request_prompt()
    rule = prompt[prompt.index("Portrait, landscape"):].split("\n")[0]

    assert "Width and Height settings, never words in a prompt" in rule
    assert '"setting": "width"' in prompt


def test_a_lora_is_taught_by_title_with_the_newest_version_marked_and_trigger_words_the_apps():
    prompt = _request_prompt()
    rule = prompt[prompt.index("A LoRA is picked"):].split("\n")[0]

    assert "title" in rule
    assert "newest" in rule
    assert "never edit trigger words" in rule


def test_a_correction_is_taught_as_reversing_the_change_and_then_doing_what_was_asked():
    prompt = _request_prompt()
    rule = prompt[prompt.index("A correction"):].split("\n")[0]

    assert "reverse the change" in rule
    assert "nothing more" in rule
    assert "never about him in the third person" in prompt


def test_the_model_is_taught_to_change_only_what_was_asked():
    prompt = _request_prompt()
    rule = prompt[prompt.index("Change only what"):].split("\n")[0]

    assert "Never add, remove or reword anything he did not ask about" in rule
