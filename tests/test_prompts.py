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


def test_a_complaint_that_something_asked_for_is_missing_is_taught_as_more_of_it():
    prompt = _request_prompt()
    rule = prompt[prompt.index("When he wants more of something"):].split("\n")[0]

    assert "didn't appear" in rule
    assert "never remove X for a complaint like that" in rule
    example = prompt[prompt.index("- \"the dog didn't appear\""):].split("\n")[0]
    answer = example.split("->")[1]
    assert '"more": "a dog"' in answer
    assert '"remove": "animals"' in answer


def test_a_complaint_that_something_unwanted_is_still_there_is_taught_as_wanting_it_gone():
    prompt = _request_prompt()
    rule = prompt[prompt.index("Positive prompts cannot negate"):].split("\n")[0]

    assert "X is still there" in rule
    assert "Never remove X from the negative prompt" in rule
    assert "weigh more" in rule
    assert "a raincoat is a coat" in rule
    example = prompt[prompt.index('- "they still have hats"'):].split("\n")[0]
    assert '"gone": "hats", "in_positive": "straw hats"' in example


def test_something_unwanted_the_positive_prompt_never_named_is_taught_as_gone_with_nothing_to_take_out():
    prompt = _request_prompt()

    for asked in ('- "no scarf please"', '- "she shouldn\'t have gloves"'):
        answer = prompt[prompt.index(asked):].split("\n")[0].split("->")[1]
        assert '"gone":' in answer
        assert '"in_positive": ""' in answer


def test_his_prompts_that_touch_the_request_are_the_model_for_writing_what_he_asks():
    rule = _request_prompt()[_request_prompt().index("When PROMPTS OF HIS THAT TOUCH"):].split("\n")[0]

    assert "the way those prompts" in rule.lower() or "the way they" in rule.lower()
    assert "one person" in rule
    assert "singular" in rule
    assert "never" in rule.lower()
    assert "end" in rule.lower()


def test_portrait_and_landscape_are_taught_as_width_and_height_never_as_prompt_words():
    prompt = _request_prompt()
    rule = prompt[prompt.index("Portrait, landscape"):].split("\n")[0]

    assert "are the Width and Height settings" in rule
    assert "never write the shape into a prompt" in rule
    assert "the word itself" in rule
    assert "leave Width and Height alone" in rule
    assert "never put another shape's word" in rule
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


def test_a_word_he_names_is_taught_as_taken_out_alone_with_the_words_around_it_kept():
    prompt = _request_prompt()
    rule = prompt[prompt.index("When he names one word"):].split("\n")[0]

    assert "only that word" in rule
    assert "keep the words around it" in rule
    answer = prompt[prompt.index("- \"maybe the word 'vintage'"):].split("\n")[0].split("->")[1]
    assert '"replace": "vintage photo of a lake", "with": "photo of a lake"' in answer


def test_more_of_something_is_taught_as_his_stronger_words_and_its_opposite_with_the_app_doing_the_rest():
    prompt = _request_prompt()
    rule = prompt[prompt.index("When he wants more of something"):].split("\n")[0]

    assert '{"more":' in rule
    assert "The stronger words are his" in rule
    assert "what his prompts put beside it for more of it" in rule
    assert "what his prompts keep out for more of it" in rule
    assert "the app keeps the part as it is" in rule
    assert "never words of your own" in rule
    assert "a silver ring stays a silver ring" in rule
    for the_apps in ("moves the part to the front of the positive prompt", "raises its weight",
                     "puts the opposite into the negative prompt", "never takes an opposite back out"):
        assert the_apps in rule
    assert "never no X" in rule
    assert "an opposite does not fight it" in rule
