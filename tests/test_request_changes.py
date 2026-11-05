from __future__ import annotations

import pytest

from origenerator import request_settings
from origenerator.request_changes import apply_changes
from origenerator.trigger_words import with_trigger_words_swapped
from origenerator.workflows.base import ParamDef, ParamType, story_of

_SIZE = request_settings.settings_to_tell(
    [ParamDef("width", "Width", ParamType.INT, 1280, min_val=512, max_val=2048, step=16),
     ParamDef("height", "Height", ParamType.INT, 720, min_val=512, max_val=2048, step=16)],
    {"width": 1280, "height": 720})


def _applied(changes, pair=("a woman on a couch", "blurry"), *, asked=("portrait",),
             settings=_SIZE, note=""):
    return apply_changes({"changes": changes, "note": note}, pair, asked=list(asked),
                         settings=settings)


def test_a_setting_change_is_taken_in_its_own_kind_and_said_with_what_it_was():
    outcome = _applied([{"setting": "width", "to": "720", "for": "portrait"},
                        {"setting": "Height", "to": 1280, "for": "portrait"}])

    assert outcome.settings == {"width": 720, "height": 1280}
    assert (outcome.positive, outcome.negative) == ("a woman on a couch", "blurry")
    assert outcome.line == "Set Width to 720 (was 1280). Set Height to 1280 (was 720)."


def test_a_setting_or_value_the_app_cannot_read_is_said_so_instead_of_vanishing():
    outcome = _applied([{"setting": "steps", "to": 30, "for": "portrait"},
                        {"setting": "width", "to": "wider", "for": "portrait"},
                        {"setting": "width", "to": 1280, "for": "portrait"}])

    assert outcome.settings == {}
    assert outcome.line == ('There is no setting called "steps". Width can\'t be "wider". '
                            "Width is already 1280.")


def test_a_change_that_answers_nothing_he_asked_for_is_left_out_and_said_so():
    outcome = _applied([{"setting": "width", "to": 720},
                        {"setting": "height", "to": 1280, "for": "natural lighting"},
                        {"setting": "height", "to": 1280, "for": "Make it portrait"}],
                       asked=("make it portrait, please", "no you didn't"))

    assert outcome.settings == {"height": 1280}
    assert outcome.line == ("Didn't set Width to 720: you didn't ask for that. Didn't set Height "
                            "to 1280: you didn't ask for that. Set Height to 1280 (was 720).")


def test_words_of_a_prompt_are_replaced_where_they_stand_whatever_their_case():
    outcome = _applied([{"prompt": "positive", "replace": "A Woman", "with": "two women",
                         "for": "two women"},
                        {"prompt": "negative", "replace": "blurry", "with": "(blurry:1.2)",
                         "for": "less blurry"},
                        {"prompt": "positive", "replace": "a cat", "with": "a dog", "for": "dog"}],
                       asked=("two women, less blurry, and a dog",))

    assert (outcome.positive, outcome.negative) == ("two women on a couch", "(blurry:1.2)")
    assert outcome.line == (
        'Replaced "A Woman" with "two women" in the Positive Prompt. Replaced "blurry" with '
        '"(blurry:1.2)" in the Negative Prompt. Couldn\'t find "a cat" in the Positive Prompt.')


def test_words_are_added_after_the_part_they_belong_with_or_at_the_end_and_never_twice():
    outcome = _applied([{"prompt": "positive", "add": "freckles", "after": "a woman", "for": "freckles"},
                        {"prompt": "positive", "add": "soft light", "after": "a beach", "for": "light"},
                        {"prompt": "negative", "add": "Blurry", "for": "blurry"},
                        {"prompt": "negative", "add": "hat", "for": "no hat"}],
                       pair=("a woman on a couch, (smiling:1.2)", "blurry"),
                       asked=("freckles, soft light, less blurry, no hat",))

    assert (outcome.positive, outcome.negative) == (
        "a woman on a couch, freckles, (smiling:1.2), soft light", "blurry, hat")
    assert outcome.line == (
        'Added "freckles" to the Positive Prompt. Added "soft light" to the Positive Prompt. '
        'The Negative Prompt already has "Blurry". Added "hat" to the Negative Prompt.')


def test_words_are_taken_out_of_a_prompt_and_the_commas_close_over_them():
    outcome = _applied([{"prompt": "positive", "remove": "on a couch", "for": "no couch"},
                        {"prompt": "negative", "remove": "blurry", "for": "blurry is fine"},
                        {"prompt": "negative", "remove": "grain", "for": "grain"}],
                       asked=("no couch, blurry is fine, grain",))

    assert (outcome.positive, outcome.negative) == ("a woman", "")
    assert outcome.line == (
        'Removed "on a couch" from the Positive Prompt. Removed "blurry" from the Negative Prompt. '
        'Couldn\'t find "grain" in the Negative Prompt.')


def test_a_prompt_change_answering_nothing_he_asked_for_is_left_out_too():
    outcome = _applied([{"prompt": "positive", "replace": "a woman", "with": "a grumpy woman"},
                        {"prompt": "negative", "add": "doll", "for": "natural lighting"},
                        {"prompt": "positive", "remove": "on a couch", "for": "natural lighting"}],
                       asked=("use the newer LoRA",))

    assert (outcome.positive, outcome.negative) == ("a woman on a couch", "blurry")
    assert outcome.line == (
        'Didn\'t replace "a woman" with "a grumpy woman" in the Positive Prompt: you didn\'t ask '
        'for that. Didn\'t add "doll" to the Negative Prompt: you didn\'t ask for that. '
        'Didn\'t remove "on a couch" from the Positive Prompt: you didn\'t ask for that.')


def test_no_change_at_all_says_so_with_whatever_note_the_model_left():
    assert _applied([]).line == "Nothing changed."
    assert _applied([], note="The image is portrait already.").line == (
        "Nothing changed. The image is portrait already.")
    assert _applied([{"setting": "width", "to": 1280, "for": "portrait"}],
                    note="ignored once something was said").line == "Width is already 1280."


def test_a_change_the_app_cannot_read_is_said_so():
    outcome = _applied([{"prompt": "positive", "for": "portrait"}, "portrait", {"mood": "sad"}])

    assert outcome.line == ("Couldn't read one of the model's changes. Couldn't read one of the "
                            "model's changes. Couldn't read one of the model's changes.")


_LORA_ROW = ParamDef("lora", "LoRA 1", ParamType.DROPDOWN, "None",
                     options=["None", "example_style.safetensors", "example_style_11.safetensors"],
                     folder="loras")


@pytest.fixture
def versioned_style(titled_models, worded_loras):
    titled_models({"example_style": "Example Style 1.0", "example_style_11": "Example Style 1.1"})
    worded_loras({"example_style": ["exmplstyle"], "example_style_11": ["exmplnew"]})


def _lora_switched(picked: str, to: str, positive: str, **how):
    settings = request_settings.settings_to_tell([_LORA_ROW], {"lora": picked})
    return apply_changes({"changes": [{"setting": "lora", "to": to, "for": "newer version"}]},
                         (positive, "blurry"), asked=["use the newer version"], settings=settings,
                         **how)


def test_switching_a_lora_swaps_its_trigger_word_where_it_stands_as_the_warnings_click_does(
        versioned_style):
    prompt = "a woman, (exmplstyle:1.1), soft light, exmplstyle"
    outcome = _lora_switched("example_style.safetensors", "Example Style 1.1", prompt)

    assert outcome.settings == {"lora": "example_style_11.safetensors"}
    assert outcome.positive == "a woman, (exmplnew:1.1), soft light, exmplnew"
    assert outcome.positive == with_trigger_words_swapped(prompt, ("exmplstyle",), ("exmplnew",))
    assert outcome.line == ("Set LoRA 1 to Example Style 1.1 (was Example Style 1.0), and swapped "
                            "its trigger word exmplstyle for exmplnew in the Positive Prompt.")


def test_picking_a_lora_puts_its_trigger_word_in_and_dropping_one_takes_its_word_out(
        versioned_style):
    picked = _lora_switched("None", "Example Style 1.0", "a woman")
    dropped = _lora_switched("example_style_11.safetensors", "None", "exmplnew, a woman")

    assert picked.positive == "exmplstyle, a woman"
    assert picked.line == ("Set LoRA 1 to Example Style 1.0 (was None), and put its trigger word "
                           "exmplstyle in the Positive Prompt.")
    assert dropped.positive == "a woman"
    assert dropped.line == ("Set LoRA 1 to None (was Example Style 1.1), and took its trigger "
                            "word exmplnew out of the Positive Prompt.")


def test_a_trigger_word_already_where_it_belongs_is_left_as_it_is_and_unmentioned(versioned_style):
    outcome = _lora_switched("example_style.safetensors", "Example Style 1.1", "exmplnew, a woman")

    assert outcome.positive == "exmplnew, a woman"
    assert outcome.line == "Set LoRA 1 to Example Style 1.1 (was Example Style 1.0)."


def test_a_storys_scenes_each_get_the_trigger_word_swapped(versioned_style):
    outcome = _lora_switched("example_style.safetensors", "Example Style 1.1",
                             story_of(["exmplstyle, a dog", "a cat"]), in_scenes=True)

    assert outcome.positive == story_of(["exmplnew, a dog", "exmplnew, a cat"])


def test_an_edit_riding_inside_a_replacement_he_asked_for_is_left_out_and_said_so():
    outcome = _applied(
        [{"prompt": "positive", "replace": "exmplstyle, two women on a couch, soft light",
          "with": "(exmplstyle:1.2), one woman on a couch, soft light, natural lighting",
          "for": "have only one woman"}],
        pair=("exmplstyle, two women on a couch, soft light", "blurry"),
        asked=("please make it portrait and have only one woman",))

    assert outcome.positive == "exmplstyle, one woman on a couch, soft light"
    assert outcome.line == (
        'Replaced "two women" with "one woman" in the Positive Prompt. Didn\'t replace '
        '"exmplstyle" with "(exmplstyle:1.2)" in the Positive Prompt: you didn\'t ask for that. '
        'Didn\'t add "natural lighting" to the Positive Prompt: you didn\'t ask for that.')


def test_a_replacement_in_words_that_are_not_his_at_all_is_the_models_to_make_whole():
    outcome = _applied([{"prompt": "positive", "replace": "silver ear studs, a necklace",
                         "with": "bare ears, a bare neck", "for": "no jewelry"}],
                       pair=("a woman, silver ear studs, a necklace", "blurry"),
                       asked=("no jewelry",))

    assert outcome.positive == "a woman, bare ears, a bare neck"
    assert outcome.line == ('Replaced "silver ear studs, a necklace" with "bare ears, a bare neck" '
                            "in the Positive Prompt.")


def test_a_part_the_replacement_drops_without_his_asking_stays_and_is_said_so():
    outcome = _applied([{"prompt": "positive", "replace": "a woman, a hat, soft light",
                         "with": "two women, soft light", "for": "two women"}],
                       pair=("a woman, a hat, soft light", "blurry"), asked=("two women",))

    assert outcome.positive == "two women, a hat, soft light"
    assert outcome.line == (
        'Replaced "a woman" with "two women" in the Positive Prompt. Didn\'t remove "a hat" '
        "from the Positive Prompt: you didn't ask for that.")


def test_each_part_of_a_replacement_he_asked_for_is_said_as_what_it_was():
    outcome = _applied([{"prompt": "positive", "replace": "a red hat, a dog, grass",
                         "with": "a blue hat, grass, a cat", "for": "a blue hat"}],
                       pair=("a red hat, a dog, grass", "blurry"),
                       asked=("a blue hat, no dog, add a cat",))

    assert outcome.positive == "a blue hat, grass, a cat"
    assert outcome.line == (
        'Replaced "red" with "blue" in the Positive Prompt. Removed "a dog" from the Positive '
        'Prompt. Added "a cat" to the Positive Prompt.')
